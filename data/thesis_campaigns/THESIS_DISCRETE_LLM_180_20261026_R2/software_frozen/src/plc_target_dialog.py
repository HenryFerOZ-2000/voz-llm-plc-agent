"""Read-only discovery and explicit selection of a Normal-mode download destination."""
import copy
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import customtkinter as ctk
from plc_targets import normalize_target
from plcsim_runtime import list_plcsim_instances, resolve_instance
from tia_openness import list_tia_connections


class PlcTargetDialog(ctk.CTkToplevel):
    def __init__(self, app, initial_target: dict, revision: dict):
        super().__init__(app)
        self.app=app;self.initial=copy.deepcopy(initial_target);self.revision=revision
        self.result=None;self.closed=False;self.searching=False;self.events=queue.Queue()
        self.instances=[];self.connections=[]
        self.title('Seleccionar destino PLC · Modo Normal');self.geometry('780x650')
        self.grid_columnconfigure(0,weight=1)
        self.kind=tk.StringVar(self,value=initial_target['target_type'])
        self.instance=tk.StringVar(self);self.route=tk.StringVar(self);self.port=tk.StringVar(self,value=initial_target.get('target_interface',''))
        self.address=tk.StringVar(self,value=initial_target.get('target_address',''))
        self.name=tk.StringVar(self,value=initial_target.get('target_name',''))
        self.status=tk.StringVar(self,value='Busque las instancias e interfaces disponibles. La búsqueda no descarga programas.')
        ctk.CTkLabel(self,text=f"Proyecto: {initial_target.get('project_path','-')}\nCPU esperada: {initial_target.get('plc_name') or 'Única en el proyecto'}",wraplength=730,justify='left').grid(row=0,column=0,padx=18,pady=12,sticky='ew')
        self.kind_box=ttk.Combobox(self,textvariable=self.kind,values=('PLCSIM_ADVANCED','PHYSICAL_PLC'),state='readonly')
        self.kind_box.grid(row=1,column=0,padx=18,pady=5,sticky='ew');self.kind_box.bind('<<ComboboxSelected>>',self._kind_changed)
        ctk.CTkLabel(self,text='Instancia virtual (selección explícita)').grid(row=2,column=0,padx=18,sticky='w')
        self.instance_box=ttk.Combobox(self,textvariable=self.instance,state='readonly')
        self.instance_box.grid(row=3,column=0,padx=18,pady=5,sticky='ew');self.instance_box.bind('<<ComboboxSelected>>',self._instance_changed)
        ctk.CTkLabel(self,text='Interfaz PG/PC del proyecto TIA').grid(row=4,column=0,padx=18,sticky='w')
        self.route_box=ttk.Combobox(self,textvariable=self.route,state='readonly')
        self.route_box.grid(row=5,column=0,padx=18,pady=5,sticky='ew');self.route_box.bind('<<ComboboxSelected>>',self._route_changed)
        ctk.CTkLabel(self,text='Puerto del PLC en la plantilla').grid(row=6,column=0,padx=18,sticky='w')
        self.port_box=ttk.Combobox(self,textvariable=self.port,state='readonly');self.port_box.grid(row=7,column=0,padx=18,pady=5,sticky='ew')
        for row,label,var in ((8,'Dirección IPv4 de destino',self.address),(10,'Nombre descriptivo',self.name)):
            ctk.CTkLabel(self,text=label).grid(row=row,column=0,padx=18,sticky='w')
            entry=ttk.Combobox(self,textvariable=var) if row==8 else ctk.CTkEntry(self,textvariable=var)
            entry.grid(row=row+1,column=0,padx=18,pady=5,sticky='ew')
            if row==8:self.address_box=entry
        ctk.CTkLabel(self,text='PLC físico: dirección manual. TIA V18 no ofrece búsqueda de dispositivos en esta integración.\nLa CPU y su compatibilidad física permanecen sin verificar hasta la comprobación correspondiente.',wraplength=730,justify='left').grid(row=12,column=0,padx=18,pady=8,sticky='ew')
        ctk.CTkLabel(self,textvariable=self.status,wraplength=730,justify='left').grid(row=13,column=0,padx=18,pady=8,sticky='ew')
        actions=ctk.CTkFrame(self,fg_color='transparent');actions.grid(row=14,column=0,padx=18,pady=12,sticky='ew');actions.grid_columnconfigure((0,1,2),weight=1)
        self.search_button=ctk.CTkButton(actions,text='Buscar',command=self.search);self.search_button.grid(row=0,column=0,padx=4,sticky='ew')
        ctk.CTkButton(actions,text='Cancelar',command=self.cancel).grid(row=0,column=1,padx=4,sticky='ew')
        self.accept_button=ctk.CTkButton(actions,text='Usar destino',command=self.accept);self.accept_button.grid(row=0,column=2,padx=4,sticky='ew')
        self.protocol('WM_DELETE_WINDOW',self.cancel);self.bind('<Escape>',lambda e:self.cancel());self.transient(app)
        self.grab_set()
        self._kind_changed()

    def _kind_changed(self,event=None):
        self.instance_box.configure(state='readonly' if self.kind.get()=='PLCSIM_ADVANCED' else 'disabled')

    def _instance_changed(self,event=None):
        index=self.instance_box.current()
        if index<0:return
        selected=self.instances[index]
        addresses=selected.get('addresses') or []
        self.address_box.configure(values=addresses)
        self.address.set(addresses[0] if len(addresses)==1 else '')
        self.name.set(selected['instance_name'])
        self.status.set('Direcciones leídas: '+(', '.join(addresses) or 'no disponibles')+' · CPU: '+str(selected.get('cpu_state') or 'sin verificar'))

    def _route_changed(self,event=None):
        index=self.route_box.current()
        if index<0:return
        ports=self.connections[index].get('target_interfaces') or []
        self.port_box.configure(values=ports)
        self.port.set(self.initial.get('target_interface') if self.initial.get('target_interface') in ports else ports[0] if len(ports)==1 else '')

    def search(self):
        if self.searching or self.closed:return
        self.searching=True;self.search_button.configure(state='disabled');self.status.set('Consultando PLCSIM y las interfaces de TIA…')
        def worker():
            for key,provider in (('instances',list_plcsim_instances),('connections',list_tia_connections)):
                try:self.events.put((key,provider(self.app.project_root)))
                except Exception as error:self.events.put((key,{'errors':[str(error)]}))
            self.events.put(('done',{}))
        threading.Thread(target=worker,daemon=True,name='plc-target-discovery').start();self.after(100,self.poll)

    def poll(self):
        if self.closed:return
        while True:
            try:key,report=self.events.get_nowait()
            except queue.Empty:break
            if key=='instances':
                self.instances=report.get('instances') or []
                self.instance_box.configure(values=[f"{r['instance_name']} · ID {r['instance_id']}" for r in self.instances])
                self.instance.set('')
            elif key=='connections':
                self.connections=[{**r,'configuration_mode':r['mode'],'pc_interface_number':r['number']} for r in report.get('connections') or []]
                self.route_box.configure(values=[f"{r['configuration_mode']} · {r['pc_interface']} [{r['pc_interface_number']}]" for r in self.connections]);self.route.set('')
            elif key=='done':
                self.searching=False;self.search_button.configure(state='normal');self.status.set('Seleccione instancia, interfaz, puerto y dirección. No se elige un PLC automáticamente.')
            if report.get('errors'):self.status.set('\n'.join(report['errors']))
        if self.searching:self.after(100,self.poll)

    def accept(self):
        if self.closed or self.searching:return
        try:
            index=self.route_box.current()
            if index<0:raise ValueError('Busque y seleccione una interfaz PG/PC.')
            route=self.connections[index]
            target={**self.initial,**{k:route[k] for k in ('configuration_mode','pc_interface','pc_interface_number')},'target_type':self.kind.get(),'target_interface':self.port.get(),'target_address':self.address.get(),'target_name':self.name.get()}
            if target['target_type']=='PLCSIM_ADVANCED':
                if 'PLCSIM' not in str(route['pc_interface']).upper():
                    raise ValueError('Un destino virtual requiere la interfaz PG/PC de PLCSIM. Para una interfaz física seleccione PLC físico.')
                index=self.instance_box.current()
                if index<0:raise ValueError('Seleccione una instancia de la lista.')
                selected=resolve_instance(self.instances,self.instances[index]);target.update({k:selected[k] for k in ('instance_name','instance_id')})
                if target['target_address'] not in selected.get('addresses',[]):raise ValueError('La dirección no coincide con las direcciones leídas de la instancia.')
            else:
                target.pop('instance_name',None);target.pop('instance_id',None)
            target=normalize_target(target)
            if not target.get('target_address') or not target.get('target_interface'):raise ValueError('Indique dirección y puerto de destino.')
        except ValueError as error:messagebox.showwarning('Destino PLC',str(error),parent=self);return
        self.result=target;self.cancel()

    def cancel(self):
        self.closed=True;self.destroy()
