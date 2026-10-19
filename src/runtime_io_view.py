"""Visible, typed PLCSIM bench controls for the downloaded program."""
import queue
import threading
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk
import plcsim_runtime_io as rio
from runtime_io_controls import ManualIOSession,signals,scale,decode_value

class RuntimeIOTestWindow(ctk.CTkToplevel):
    def __init__(self,app,program,target_type,runtime_report,report_dir,trial_directory):
        super().__init__(app)
        self.app,self.program=app,program
        self.target_type,self.report_dir,self.trial_directory=target_type,report_dir,trial_directory
        config=app._normal_runtime_config() if (app._io_program_context or {}).get('purpose','normal')=='normal' else None
        self.session=ManualIOSession(program,target_type,runtime_report,app.project_root,runtime_config=config)
        self._busy=False;self._closing=False;self._queue=queue.Queue();self._timer=None
        self.title('Prueba de I/O · PLCSIM Advanced');self.geometry('690x860');self.minsize(620,700)
        self.grid_columnconfigure(0,weight=1);self.grid_rowconfigure(1,weight=1)
        self.protocol('WM_DELETE_WINDOW',self.close)
        state=runtime_report.get('cpu_state','?')
        header=f"{self.session.config['instance_name']} · CPU {state}\nPrograma descargado: {program.get('path','?')}"
        ctk.CTkLabel(self,text=header,wraplength=640,justify='left').grid(row=0,column=0,padx=16,pady=12,sticky='w')
        body=ctk.CTkScrollableFrame(self);body.grid(row=1,column=0,sticky='nsew',padx=12);body.grid_columnconfigure(0,weight=1)
        inputs=[s['name'] for s in signals(program,'I')];outputs=[s['name'] for s in signals(program,'Q')]
        self._inputs_available=bool(inputs);self._outputs_available=bool(outputs)
        self._buttons=[];self._controls=[]
        self.input_var=tk.StringVar(value=inputs[0] if inputs else '')
        self.output_var=tk.StringVar(value=outputs[0] if outputs else '')
        self.value_var=tk.StringVar(value='OFF');self.output_bool=tk.StringVar(value='OFF')
        self.input_number=tk.StringVar(value='0');self.output_number=tk.StringVar(value='0')
        self.manual_var=tk.BooleanVar(value=False);self.auto_var=tk.BooleanVar(value=False)
        for prefix,title,names,var in [('input','Entradas · estímulos al programa en RUN',inputs,self.input_var),
                                       ('output','Salidas · valores reales del programa',outputs,self.output_var)]:
            frame=ctk.CTkFrame(body);frame.grid(row=0 if prefix=='input' else 1,column=0,sticky='ew',pady=6,padx=4);frame.grid_columnconfigure(0,weight=1)
            ctk.CTkLabel(frame,text=title,font=app.button_font).grid(row=0,column=0,padx=12,pady=8,sticky='w')
            menu=ctk.CTkOptionMenu(frame,variable=var,values=names or ['(sin señales compatibles)'],
                command=self.select_input if prefix=='input' else self.select_output)
            menu.grid(row=1,column=0,padx=12,pady=4,sticky='ew');setattr(self,prefix+'_menu',menu);self._controls.append(menu)
            details=tk.StringVar();setattr(self,prefix+'_details',details)
            ctk.CTkLabel(frame,textvariable=details,wraplength=590,justify='left').grid(row=2,column=0,padx=12,pady=4,sticky='w')
            switch=ctk.CTkSegmentedButton(frame,values=['OFF','ON'],variable=self.value_var if prefix=='input' else self.output_bool)
            switch.grid(row=3,column=0,padx=12,pady=4,sticky='ew');setattr(self,prefix+'_switch',switch);self._controls.append(switch)
            slider=ctk.CTkSlider(frame,from_=0,to=100,command=lambda v,p=prefix:self._slider_value(p,v))
            slider.grid(row=4,column=0,padx=18,pady=8,sticky='ew');setattr(self,prefix+'_slider',slider);self._controls.append(slider)
            entry=ctk.CTkEntry(frame,textvariable=self.input_number if prefix=='input' else self.output_number)
            entry.grid(row=5,column=0,padx=12,pady=4,sticky='ew');setattr(self,prefix+'_entry',entry);self._controls.append(entry)
            if prefix=='input':
                self.write_button=ctk.CTkButton(frame,text='APLICAR ENTRADA',command=self.write_input)
                self.write_button.grid(row=6,column=0,padx=12,pady=4,sticky='ew')
                self.pulse_button=ctk.CTkButton(frame,text='PULSAR (ON → OFF)',command=self.pulse_input)
                self.pulse_button.grid(row=7,column=0,padx=12,pady=4,sticky='ew')
                self.readback_var=tk.StringVar(value='Readback: pendiente')
                ctk.CTkLabel(frame,textvariable=self.readback_var,wraplength=590).grid(row=8,column=0,padx=12,pady=6,sticky='w')
                self._buttons.extend([self.write_button,self.pulse_button])
            else:
                self.read_button=ctk.CTkButton(frame,text='LEER SALIDA REAL',command=self.read_output)
                self.read_button.grid(row=6,column=0,padx=12,pady=4,sticky='ew')
                self.output_value_var=tk.StringVar(value='Valor observado: pendiente')
                ctk.CTkLabel(frame,textvariable=self.output_value_var,wraplength=590).grid(row=7,column=0,padx=12,pady=6,sticky='w')
                self.manual_check=ctk.CTkCheckBox(frame,text='Prueba manual de salidas (requiere CPU en STOP)',variable=self.manual_var,command=self._control_states)
                self.manual_check.grid(row=8,column=0,padx=12,pady=6,sticky='w');self._controls.append(self.manual_check)
                self.output_write_button=ctk.CTkButton(frame,text='APLICAR SALIDA MANUAL',command=self.write_output)
                self.output_write_button.grid(row=9,column=0,padx=12,pady=(4,10),sticky='ew')
                self._buttons.extend([self.read_button,self.output_write_button])
        self.restore_button=ctk.CTkButton(body,text='RESTAURAR VALORES INICIALES',command=self.restore_inputs)
        self.restore_button.grid(row=2,column=0,padx=4,pady=8,sticky='ew');self._buttons.append(self.restore_button)
        ctk.CTkCheckBox(body,text='Actualizar la salida seleccionada cada segundo',variable=self.auto_var,command=self._schedule_refresh).grid(row=3,column=0,padx=12,pady=6,sticky='w')
        ctk.CTkLabel(body,text='En RUN, la salida muestra la respuesta del programa. Para probar una salida manualmente,\ncoloque la CPU en STOP y vuelva a abrir esta ventana. La herramienta no cambia el estado de la CPU.',wraplength=600,justify='left').grid(row=4,column=0,padx=12,pady=8,sticky='w')
        self.status_var=tk.StringVar(value='Las señales modificadas vuelven a sus valores iniciales al cerrar.')
        ctk.CTkLabel(self,textvariable=self.status_var,wraplength=640,justify='left').grid(row=2,column=0,padx=16,pady=12,sticky='w')
        self.select_input(self.input_var.get());self.select_output(self.output_var.get())

    def _slider_value(self,prefix,value):
        getattr(self,prefix+'_number').set(f'{value:.5g}')

    def _select(self,prefix,name):
        signal=self.program['signals'].get(name)
        if signal is None:return
        boolean=signal['data_type']=='BOOL';c=scale(signal)
        getattr(self,prefix+'_details').set(f"{signal['address']} · {signal['data_type']} · "+('ON / OFF' if boolean else
            f"{c['engineering_min']:g}–{c['engineering_max']:g} {c['engineering_unit']} · RAW {c['raw_min']:g}–{c['raw_max']:g}"))
        switch=getattr(self,prefix+'_switch');slider=getattr(self,prefix+'_slider');entry=getattr(self,prefix+'_entry')
        if boolean:switch.grid();slider.grid_remove();entry.grid_remove()
        else:
            switch.grid_remove();slider.grid();entry.grid()
            slider.configure(from_=c['engineering_min'],to=c['engineering_max']);slider.set(c['engineering_min'])
            getattr(self,prefix+'_number').set(f"{c['engineering_min']:g}")
        self._control_states()

    def select_input(self,name):self._select('input',name)
    def select_output(self,name):self._select('output',name)

    def _control_states(self):
        disabled=self._busy or self._closing
        for control in self._controls+self._buttons:control.configure(state='disabled' if disabled else 'normal')
        if disabled:return
        run=self.session.runtime_report.get('cpu_state')=='RUN'
        manual=self.manual_var.get() and self.session.runtime_report.get('cpu_state')=='STOP'
        self.write_button.configure(state='normal' if run and self._inputs_available else 'disabled')
        self.pulse_button.configure(state='normal' if run and self.program['signals'].get(self.input_var.get(),{}).get('data_type')=='BOOL' else 'disabled')
        self.read_button.configure(state='normal' if self._outputs_available else 'disabled')
        self.output_write_button.configure(state='normal' if manual and self._outputs_available else 'disabled')
        for control in (self.output_slider,self.output_entry,self.output_switch):control.configure(state='normal' if manual else 'disabled')

    def _run(self,description,work,on_done):
        if self._busy:return
        self._busy=True;self._control_states();self.status_var.set(description+'…')
        def worker():
            try:self._queue.put(('ok',work()))
            except Exception as error:self._queue.put(('error',error))
        threading.Thread(target=worker,name='plcsim-manual-io',daemon=True).start()
        self.after(80,lambda:self._poll(on_done))

    def _poll(self,on_done):
        try:outcome,payload=self._queue.get_nowait()
        except queue.Empty:self.after(80,lambda:self._poll(on_done));return
        self._busy=False;self._control_states()
        if outcome=='ok':on_done(payload)
        else:
            self.status_var.set(str(payload));self.app._log('[PLCSIM IO] '+str(payload))
            if self._closing:
                self._closing=False;self._control_states()
                if getattr(self.app,'_application_close_pending',False):self.app._io_shutdown_error=str(payload)

    def _display(self,name,raw):
        signal=self.program['signals'][name]
        if raw is None:return 'sin lectura verificada'
        if signal['data_type']=='BOOL':return 'ON' if raw else 'OFF'
        return f"{decode_value(signal,raw):.5g} {scale(signal)['engineering_unit']} · RAW {raw}"

    def _write_value(self,prefix,value=None,after=None):
        name=getattr(self,prefix+'_var').get();signal=self.program['signals'].get(name)
        if not signal:return
        try:
            if value is None:
                value=(self.value_var if prefix=='input' else self.output_bool).get()=='ON' if signal['data_type']=='BOOL' else float(getattr(self,prefix+'_number').get())
        except ValueError:self.status_var.set('Introduzca un número válido.');return
        method=self.session.write_input if prefix=='input' else self.session.write_output
        def done(result):
            self.status_var.set('Escritura y readback verificados.')
            label=self.readback_var if prefix=='input' else self.output_value_var
            label.set(f"{name}: {self._display(name,result.get('readback'))} · {'OK' if result['match'] else 'NO COINCIDE'}")
            if after:after()
        self._run(f'Aplicando {name}',lambda:method(name,value),done)

    def write_input(self):self._write_value('input')
    def write_output(self):
        if self.manual_var.get():self._write_value('output')

    def pulse_input(self):
        name=self.input_var.get()
        if self.program['signals'].get(name,{}).get('data_type')!='BOOL':return
        def work():
            import time
            try:
                self.session.write_input(name,True);time.sleep(.15)
            finally:result=self.session.write_input(name,False)
            return result
        self._run('Pulsando '+name,work,lambda result:self.readback_var.set(f'{name}: OFF · pulso verificado'))

    def read_output(self):
        name=self.output_var.get()
        if not name:return
        def done(result):
            value=result['values'][0]['value'];self.output_value_var.set(f'{name}: '+self._display(name,value))
            if self.program['signals'][name]['data_type']=='BOOL':self.output_bool.set('ON' if value else 'OFF')
            elif not self.manual_var.get():
                eu=decode_value(self.program['signals'][name],value);self.output_slider.set(eu);self.output_number.set(f'{eu:.5g}')
            self.status_var.set('Salida real leída y verificada.')
        self._run('Leyendo '+name,lambda:self.session.read_signals([name]),done)

    def _schedule_refresh(self):
        if self._timer:self.after_cancel(self._timer);self._timer=None
        if self.auto_var.get() and not self._closing:
            self._timer=self.after(1000,self._refresh)
    def _refresh(self):
        self._timer=None
        if not self._busy and not self._closing and not self.manual_var.get():self.read_output()
        self._schedule_refresh()

    def restore_inputs(self):
        def done(result):
            if result['status']==rio.SUCCESS:
                self.status_var.set('Valores iniciales restaurados y verificados.')
                if self._closing:self._finish_close()
            else:
                self._closing=False;self._control_states()
                self.status_var.set('Restauración pendiente: '+', '.join(result.get('pending',[]))+'. Conserve esta ventana y restablezca el estado de la CPU para reintentar.')
                if getattr(self.app,'_application_close_pending',False):self.app._io_shutdown_error=self.status_var.get()
        self._run('Restaurando señales',self.session.restore_inputs,done)

    def close(self):
        if self._busy:return
        self._closing=True;self.auto_var.set(False);self._schedule_refresh()
        if self.session.originals:self.restore_inputs()
        else:self._finish_close()

    def _finish_close(self):
        if self.session.writes or self.session.reads:
            report=self.session.build_report();report['report_path']=str(rio.write_io_report(self.report_dir,report))
            self.app._record_runtime_io_report(self.trial_directory,report)
        self.app._io_test_window=None;self.destroy()
