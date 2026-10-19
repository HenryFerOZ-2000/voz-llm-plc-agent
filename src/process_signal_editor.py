"""Engineering signals stored in generated DBs; no electrical or destination settings."""
from __future__ import annotations

import copy
import tkinter as tk

import customtkinter as ctk

from engineering_units import QUANTITY_UNITS, convert_unit, quantity_label
from process_signals import process_configuration_report


class ProcessSignalConfigurationPanel(ctk.CTkScrollableFrame):
    def __init__(self, master, entry: dict):
        super().__init__(master, fg_color='transparent')
        self.original = copy.deepcopy(entry.get('process_config') or {})
        storage = self.original.get('storage') or {}
        defaults = dict(role='MEASUREMENT', quantity='Nivel', engineering_unit='%', engineering_min='',
                        engineering_max='', db='', member='', validity_member='', fault_value='0')
        defaults.update(self.original)
        defaults.update(db=storage.get('db', ''), member=storage.get('member', ''))
        self.variables = {key: tk.StringVar(self, value=str(defaults[key])) for key in
                          ('role', 'quantity', 'engineering_unit', 'engineering_min', 'engineering_max',
                           'db', 'member', 'validity_member', 'fault_value')}
        self.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self, text='El proveedor escribe la medición y su calidad. El controlador escribe el mando.',
                     wraplength=500, justify='left').grid(row=0, column=0, columnspan=2, padx=8, pady=10)
        self.role_menu = ctk.CTkOptionMenu(self, variable=self.variables['role'],
                                          values=['MEASUREMENT', 'MANIPULATED'], command=self._on_role_selected)
        self.quantity_menu = ctk.CTkOptionMenu(self, variable=self.variables['quantity'],
                                              values=list(QUANTITY_UNITS), command=self._on_quantity_selected)
        self.unit_menu = ctk.CTkOptionMenu(self, variable=self.variables['engineering_unit'],
                                          values=['%'], command=self._on_unit_selected)
        special = {'role': self.role_menu, 'quantity': self.quantity_menu, 'engineering_unit': self.unit_menu}
        self.widgets = {}
        for row, (field, label) in enumerate([
            ('role', 'Función de la señal'), ('quantity', 'Magnitud'), ('engineering_unit', 'Unidad'),
            ('engineering_min', 'Mínimo de ingeniería'), ('engineering_max', 'Máximo de ingeniería'),
            ('db', 'Nombre del DB propio'), ('member', 'Miembro REAL'),
            ('validity_member', 'Miembro BOOL de calidad'), ('fault_value', 'Mando ante fallo')], 1):
            ctk.CTkLabel(self, text=label).grid(row=row, column=0, padx=8, pady=7, sticky='w')
            widget = special.get(field) or ctk.CTkEntry(self, textvariable=self.variables[field])
            widget.grid(row=row, column=1, padx=8, pady=7, sticky='ew')
            self.widgets[field] = widget
        self.notice = tk.StringVar(self)
        ctk.CTkLabel(self, textvariable=self.notice, wraplength=500, justify='left').grid(
            row=10, column=0, columnspan=2, padx=8, pady=8)
        self._refresh()

    def _refresh(self):
        quantity = quantity_label(self.variables['quantity'].get())
        units = list(QUANTITY_UNITS.get(quantity, (self.variables['engineering_unit'].get() or '%',)))
        self.unit_menu.configure(values=units)
        measurement = self.variables['role'].get() == 'MEASUREMENT'
        self.widgets['validity_member'].configure(state='normal' if measurement else 'disabled')
        self.widgets['fault_value'].configure(state='disabled' if measurement else 'normal')

    def _on_role_selected(self, role):
        self.variables['role'].set(role)
        self._refresh()

    def _on_quantity_selected(self, quantity):
        old = self.variables['quantity'].get()
        # OptionMenu has already updated its variable when called by Tk.
        self.variables['quantity'].set(quantity)
        self.variables['engineering_unit'].set('')
        for field in ('engineering_min', 'engineering_max', 'fault_value'):
            self.variables[field].set('')
        self.notice.set('Magnitud modificada: seleccione unidad e introduzca el rango nuevamente.')
        self._refresh()

    def _on_unit_selected(self, unit):
        old = self._unit_before_selection
        self.variables['engineering_unit'].set(unit)
        if old and old != unit:
            try:
                values = {field: convert_unit(float(self.variables[field].get()), old, unit)
                          for field in ('engineering_min', 'engineering_max', 'fault_value')
                          if self.variables[field].get().strip()}
            except ValueError:
                for field in ('engineering_min', 'engineering_max', 'fault_value'):
                    self.variables[field].set('')
                self.notice.set('La unidad requiere un rango nuevo; no hay conversión directa.')
            else:
                for field, value in values.items():
                    self.variables[field].set(str(value))
        self._unit_before_selection = unit

    def get_config(self) -> dict:
        config = copy.deepcopy(self.original)
        config.update(schema_version=1, role=self.variables['role'].get(), quantity=self.variables['quantity'].get(),
                      engineering_unit=self.variables['engineering_unit'].get(),
                      storage=dict(kind='GENERATED_DB', db=self.variables['db'].get().strip(),
                                   member=self.variables['member'].get().strip()))
        for field in ('engineering_min', 'engineering_max'):
            try:
                config[field] = float(self.variables[field].get())
            except ValueError as error:
                raise ValueError(f'{field}: requiere número finito.') from error
        if config['role'] == 'MEASUREMENT':
            config['validity_member'] = self.variables['validity_member'].get().strip()
            config.pop('fault_value', None)
        else:
            try:
                config['fault_value'] = float(self.variables['fault_value'].get())
            except ValueError as error:
                raise ValueError('fault_value: requiere número finito.') from error
            config.pop('validity_member', None)
        report = process_configuration_report(dict(name='Señal', type='REAL', **{'class': 'internal'},
                                                   location='', process_config=config))
        if report['errors']:
            raise ValueError('\n'.join(report['errors']))
        return config

    def set_active(self, active: bool):
        for widget in self.widgets.values():
            widget.configure(state='normal' if active else 'disabled')
        if active:
            self._refresh()
        self._unit_before_selection = self.variables['engineering_unit'].get()
