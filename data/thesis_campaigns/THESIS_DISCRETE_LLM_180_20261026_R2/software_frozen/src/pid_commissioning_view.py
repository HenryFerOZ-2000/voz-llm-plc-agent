"""Native commissioning has no side effects until an operator presses a button."""
import tkinter as tk
import customtkinter as ctk


class PidCommissioningPanel(ctk.CTkFrame):
    def __init__(self,master,bindings,on_write,on_read,on_test=None,on_cancel_test=None,on_save=None,on_evaluate=None):
        super().__init__(master)
        self.bindings,self.on_write,self.on_read=bindings,on_write,on_read
        self.columnconfigure((0,1),weight=1)
        self.status_var=tk.StringVar(value='Sin lectura. '+bindings['controller']['status'])
        self.sp_var=tk.StringVar(value='50');self.manual_var=tk.StringVar(value='0')
        self.tuning_var=tk.BooleanVar(value=False)
        ctk.CTkLabel(self,text='PID · '+bindings['instance_db']).grid(row=0,column=0,columnspan=2,padx=12,pady=8)
        ctk.CTkLabel(self,textvariable=self.status_var,wraplength=470,justify='left').grid(row=1,column=0,columnspan=2,padx=12,pady=8)
        ctk.CTkEntry(self,textvariable=self.sp_var).grid(row=2,column=0,padx=8,pady=6,sticky='ew')
        ctk.CTkButton(self,text='Aplicar consigna ('+bindings['unit']+')',command=lambda:self._number('SP',self.sp_var)).grid(row=2,column=1,padx=8,pady=6)
        for i,(text,name) in enumerate([('Marcha','CmdStart'),('Parar / cancelar ajuste','CmdStop'),('Rearme','CmdReset')]):
            ctk.CTkButton(self,text=text,command=lambda n=name:self._write(n,True)).grid(row=3+i,column=0,padx=8,pady=6,sticky='ew')
        ctk.CTkButton(self,text='Leer estado',command=on_read).grid(row=3,column=1,padx=8,pady=6,sticky='ew')
        ctk.CTkCheckBox(self,text='Autorizar sintonizacion',variable=self.tuning_var).grid(row=6,column=0,columnspan=2,padx=12,pady=8)
        ctk.CTkButton(self,text='Presintonizar',command=lambda:self._write('CmdPretune',True)).grid(row=7,column=0,padx=8,pady=6)
        ctk.CTkButton(self,text='Sintonizacion fina',command=lambda:self._write('CmdFinetune',True)).grid(row=7,column=1,padx=8,pady=6)
        ctk.CTkEntry(self,textvariable=self.manual_var).grid(row=8,column=0,padx=8,pady=6,sticky='ew')
        ctk.CTkButton(self,text='Mando manual (%)',command=lambda:self._number('ManualValue',self.manual_var)).grid(row=8,column=1,padx=8,pady=6)
        ctk.CTkButton(self,text='Modo manual',command=lambda:self._write('CmdManual',True)).grid(row=9,column=0,padx=8,pady=6)
        ctk.CTkButton(self,text='Modo automatico',command=lambda:self._write('CmdManual',False)).grid(row=9,column=1,padx=8,pady=6)
        self.test_status_var=tk.StringVar(value='El modelo externo solo se inicia al pulsar Probar. Luego rearme e inicie el PID con los mandos de arriba.')
        ctk.CTkLabel(self,textvariable=self.test_status_var,wraplength=500,justify='left').grid(row=10,column=0,columnspan=2,padx=12,pady=8)
        self.test_button=ctk.CTkButton(self,text='Probar con modelo de tanque',command=on_test,
            state='normal' if on_test else 'disabled')
        self.test_button.grid(row=11,column=0,padx=8,pady=6,sticky='ew')
        self.cancel_test_button=ctk.CTkButton(self,text='Detener modelo',command=on_cancel_test,
            state='normal' if on_cancel_test else 'disabled')
        self.cancel_test_button.grid(row=11,column=1,padx=8,pady=6,sticky='ew')
        self.operation=None;self.parameter_state='UNVERIFIED'
        self.on_save,self.on_evaluate=on_save,on_evaluate
        self.parameter_status_var=tk.StringVar(value='UNVERIFIED · Lea el estado de la CPU antes de guardar.')
        self.signal_status_var=tk.StringVar(value=self._signal_description())
        ctk.CTkLabel(self,textvariable=self.signal_status_var,wraplength=570,justify='left').grid(row=12,column=0,columnspan=2,padx=12,pady=6)
        ctk.CTkLabel(self,textvariable=self.parameter_status_var,wraplength=570,justify='left').grid(row=13,column=0,columnspan=2,padx=12,pady=6)
        self.save_button=ctk.CTkButton(self,text='Verificar ajustes guardados en TIA',command=on_save,state='disabled')
        self.save_button.grid(row=14,column=0,columnspan=2,padx=8,pady=6,sticky='ew')
        self.evaluate_button=ctk.CTkButton(self,text='Evaluar PID en PLCSIM',command=on_evaluate,state='normal' if on_evaluate else 'disabled')
        self.evaluate_button.grid(row=15,column=0,columnspan=2,padx=8,pady=6,sticky='ew')
        ctk.CTkLabel(self,text='Después de sintonizar: en TIA, abra Commissioning del PID, inicie la lectura, '
            'pulse Upload PID parameters y guarde el proyecto. Después verifique aquí los ajustes. '
            'Se compararán con la CPU; será necesario recompilar antes de otra descarga.',
            wraplength=570,justify='left').grid(row=16,column=0,columnspan=2,padx=12,pady=6)
        self._normal_states={w:w.cget('state') for w in self.winfo_children() if isinstance(w,(ctk.CTkButton,ctk.CTkEntry,ctk.CTkCheckBox))}
        self._runtime_verified=False
        self._commands=[w for w in self._normal_states if isinstance(w,ctk.CTkButton)
            and w not in (self.test_button,self.cancel_test_button,self.save_button,self.evaluate_button)
            and w.cget('text')!='Leer estado']
        for button in self._commands:button.configure(state='disabled')

    def _signal_description(self):
        parts=[]
        for key,label in [('input_binding','Sensor'),('output_binding','Actuador')]:
            b=self.bindings.get(key) or {}
            if b:parts.append(label+': '+str(b.get('resource') or b.get('name') or b.get('symbol') or b.get('address') or b.get('representation')))
        return ' | '.join(parts+['Unidad: '+self.bindings['unit']])

    def show_parameter_state(self,state):
        self.parameter_state=state['state']
        self.parameter_status_var.set(state['state']+' · '+str(state.get('reason','')))
        self.save_button.configure(state='normal' if self.on_save and not self.operation and self.parameter_state=='PENDING_SAVE' else 'disabled')
        if self.parameter_state=='INCOMPATIBLE':self.invalidate_runtime()

    def invalidate_runtime(self):
        self._runtime_verified=False
        for button in self._commands:button.configure(state='disabled')

    def set_operation_state(self,operation):
        self.operation=operation
        for widget,state in self._normal_states.items():
            widget.configure(state='disabled' if operation or widget in self._commands and not self._runtime_verified else state)
        if operation=='EVALUATING' and self.cancel_test_button.cget('command'):
            self.cancel_test_button.configure(state='normal')
        self.save_button.configure(state='normal' if not operation and self.on_save and self.parameter_state=='PENDING_SAVE' else 'disabled')

    def _write(self,name,value):
        if name in {'CmdPretune','CmdFinetune'} and not self.tuning_var.get():
            self.status_var.set('Autorice la sintonizacion antes de solicitarla.');return
        self.on_write(name,value,self.tuning_var.get())

    def _number(self,name,var):
        try: self._write(name,float(var.get()))
        except ValueError as error:self.status_var.set(str(error))

    def show_values(self,values):
        self._runtime_verified=True
        if not self.operation:
            for button in self._commands:button.configure(state='normal')
        self.status_var.set(' | '.join(f'{name}: {value}' for name,value in values.items()))

    def show_test_status(self,report):
        parts=[str(report.get('status',''))]
        if 'cleanup' in report:parts.append('Parada y restauracion verificadas: '+str(report['cleanup'].get('cleanup_verified',False)))
        parts.extend(str(error) for error in report.get('errors',[]))
        if report.get('evidence'):parts.append('Evidencia: '+str(report['evidence']))
        self.test_status_var.set(' | '.join(parts))
