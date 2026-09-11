# 22 Direcciones reales del banco fisico (MAPA_BANCO_FISICO)

## Proposito

Corrige `data/plc_maps/mapa_banco_fisico.json` para que use las direcciones fisicas REALES
observadas en el banco de pruebas (fotos del tablero), en vez de las direcciones genericas
`%IX0.x`/`%QX0.x` que se usaban antes como marcador de posicion. Es una correccion puntual del
mapa fisico - no toca el pipeline (parser/IR/SCL/Openness), ni `MAPA_SIMULACION_COMPLETO`, ni los
perfiles D01-D20/P01-P12 (que siguen filtrando por nombre funcional, no por direccion).

## Hardware confirmado

**Entradas digitales** (24 VDC): `%IX16.0` - `%IX16.7` (8 canales).
**Salidas digitales**: `%QX8.0` - `%QX8.7` (8 canales).
**Entradas analogicas**: `%IW0`/`%IW2` (tension, 0-10 VDC), `%IW4`/`%IW6` (corriente, 0-20 mA).
**Salidas analogicas**: `%QW0`/`%QW2` (tension, 0-10 VDC), `%QW4`/`%QW6` (corriente, 0-20 mA).

`%IX16.x`/`%QX8.x` es la convencion INTERNA de este proyecto para direcciones de bit (el sufijo
`X` se elimina al exportar a Siemens real - ver `SiemensSCLAdapter.to_siemens_address()`, que
convierte `%IX16.0` -> `%I16.0` y `%QX8.0` -> `%Q8.0`, la sintaxis TIA autentica que se ve en el
banco). Las direcciones de palabra analogica (`%IW`/`%QW`) no llevan ese sufijo y pasan sin
cambios.

## Tabla direccion -> nombre funcional (D01-D20, sin cambios de nombre)

| Direccion real | Nombre |
|---|---|
| %IX16.0 (%I16.0) | I_Start |
| %IX16.1 (%I16.1) | I_Stop |
| %IX16.2 (%I16.2) | I_Emergency (safety_level=critical) |
| %IX16.3 (%I16.3) | I_Reset |
| %IX16.4 (%I16.4) | I_Sensor1 |
| %IX16.5 (%I16.5) | I_Mode_Manual |
| %IX16.6 (%I16.6) | I_Mode_Auto |
| %IX16.7 (%I16.7) | I_Maintenance |
| %QX8.0 (%Q8.0) | Q_Motor_Enable |
| %QX8.1 (%Q8.1) | Q_Alarm |
| %QX8.2 (%Q8.2) | Q_Pilot_Run |
| %QX8.3 (%Q8.3) | Q_Pilot_Fault |
| %QX8.4 (%Q8.4) | Q_Aux_Output |
| %QX8.5 (%Q8.5) | Q_Contactor_A |
| %QX8.6 (%Q8.6) | Q_Contactor_B |
| %QX8.7 (%Q8.7) | Q_Pilot_Stop (**nueva** - antes no existia en este mapa; usaba el unico canal digital que quedaba sin documentar) |

Los 8 canales digitales de entrada y los 8 de salida quedan completamente ocupados por los
nombres D01-D20 ya existentes. No queda ningun canal digital libre para asignar nombres nuevos
(p. ej. I_Manual_Fill, Q_Fill_Valve, Q_Pump_Enable) sin desplazar o reemplazar un nombre D0x ya
usado - ver la seccion "Conflicto reportado" mas abajo.

## Canales analogicos: disponibles, sin funcion asignada

| Direccion | Rango | Nombre en el mapa | Estado |
|---|---|---|---|
| %IW0 | 0-10 V | AI_IW0 | disponible, sin sensor confirmado |
| %IW2 | 0-10 V | AI_IW2 | disponible, sin sensor confirmado |
| %IW4 | 0-20 mA | AI_IW4 | disponible, sin sensor confirmado |
| %IW6 | 0-20 mA | AI_IW6 | disponible, sin sensor confirmado |
| %QW0 | 0-10 V | AO_QW0 | disponible, sin actuador confirmado |
| %QW2 | 0-10 V | AO_QW2 | disponible, sin actuador confirmado |
| %QW4 | 0-20 mA | AO_QW4 | disponible, sin actuador confirmado |
| %QW6 | 0-20 mA | AO_QW6 | disponible, sin actuador confirmado |

Cada canal analogico se registro con `llm_allowed=false`: existe fisicamente y pasa la
validacion de whitelist (esta en el mapa), pero el LLM no puede referenciarlo todavia porque no
hay confirmacion de que sensor/actuador esta cableado a cada uno. Cuando se confirme (por ejemplo
"el sensor de nivel va en %IW4"), basta con renombrar esa entrada (p. ej. `AI_IW4` ->
`AI_Level_Raw`) y poner `llm_allowed=true` - la direccion fisica no cambia. **No se hizo esa
asignacion en esta tarea**, tal como se pidio explicitamente.

Las funciones dependen del cableado de cada ensayo: los mismos 8 canales analogicos pueden
usarse para un proceso de nivel, uno de flujo, o cualquier otro, segun que sensor/actuador se
conecte fisicamente antes de confirmar el nombre.

## Recursos externos AI_/AO_: misma disciplina que I_/Q_

`ir_builder.EXTERNAL_PREFIXES` ahora es `("AI_", "AO_", "I_", "Q_")` (antes solo `("I_", "Q_")`),
y el filtro de prefijos reconocidos dentro de `get_required_variables_for_intent()` (una lista
independiente que existia solo para I_/Q_/M_/T_/C_/R_/F_) tambien se amplio para incluir AI_/AO_
- sin ese segundo cambio, cualquier tag AI_/AO_ pasado como parametro de intent se descartaba
silenciosamente antes de llegar al chequeo de whitelist. Con ambos cambios, AI_/AO_:
- deben existir en el mapa activo, o `build_project_ir()` lanza
  `ValueError("Recurso externo no autorizado/no existente en el mapa PLC: ...")`, igual que I_/Q_;
- quedan sujetos al mismo filtro de `allowed_variables` por perfil (`apply_profile_filter`);
- nunca los inventa el LLM (la validacion de tags no reconocidos en `semantic_validator.py` ya
  los cubria automaticamente por no estar en `INTERNAL_PREFIXES`, sin necesitar cambios ahi).

`Level_PV`, `Level_SP`, `PID_Enable`, `Auto_Mode`, y los recursos `M_`/`T_`/`C_`/`R_`/`F_` siguen
sin cambios: variables funcionales/internas, nunca sujetas a esta whitelist.

## Tipos: raw fisico (INT) vs. ingenieria (REAL)

Los canales `AI_`/`AO_` se declararon `type: "INT"` (valor crudo del modulo analogico, en
palabra), no `REAL`. La variable REAL escalada (`Level_PV`, `Pump_Speed_CMD`, etc.) es
funcional y se calcula a partir del valor crudo solo cuando se confirme el escalado - ver
`config/pid_supervisor_config.json` -> `analog_scaling` (`confirmed: false` por ahora). No se
asumio `REAL` directamente sobre `%IWx`/`%QWx` porque el modulo real todavia no tiene su rango
crudo (p. ej. 0-27648) confirmado.

## Conflicto reportado (no aplicado)

La asignacion PID propuesta iniclamente (I_Manual_Fill, I_Manual_Drain, Q_Fill_Valve,
Q_Drain_Valve, Q_Pump_Enable, Q_Pilot_Auto sobre los mismos 8 canales digitales) **no se aplico**
porque los 8 canales de entrada y los 8 de salida ya estan completamente ocupados por nombres
D01-D20 en uso activo (I_Sensor1, I_Maintenance, Q_Motor_Enable, Q_Aux_Output, Q_Contactor_A,
Q_Contactor_B, Q_Pilot_Fault, Q_Pilot_Run). Aplicar esa propuesta habria quitado la direccion
fisica a esos nombres y roto el `hardware_ready` de la mayoria de D01-D20. `MAPA_PID_BANCO_FISICO`
permanece vacio, exactamente como ya estaba documentado en `21_pid_supervisory_control.md`: el
banco fisico del proceso PID (nivel/bomba/valvulas) sigue sin confirmar.

## Validacion de colisiones

`plc_maps/map_validator.py::validate_plc_variable_map()` ya detectaba direcciones duplicadas
(sin cambios necesarios); las reglas de `gui_helpers.py::validate_io_map_variables()` ahora
tambien exigen que `AI_*` use `%IW*` y `AO_*` use `%QW*` (antes solo existian las reglas para
`I_*`/`%IX*` y `Q_*`/`%QX*`), cubriendo "entrada usada como salida" y "digital usada como
analogica" para los nuevos prefijos con el mismo mecanismo ya existente.

## Readiness D01-D20 recalculado

`hardware_ready` se calcula por NOMBRE contra `MAPA_BANCO_FISICO` (`profiles.py::compute_readiness`),
nunca por direccion - por eso corregir las direcciones no cambia el readiness de ningun caso,
excepto D19 (paso de `False` a `True` al agregar `Q_Pilot_Stop`, que faltaba). D14 sigue
`hardware_ready=False`: le faltan `I_Speed_Low`/`I_Speed_Medium`/`I_Speed_High`, que no
corresponden a ningun canal confirmado en el banco actual - limitacion preexistente, no
introducida por esta tarea.
