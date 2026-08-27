# 19 Mapas y Perfiles Experimentales D01-D20

## Proposito

Organiza el banco discreto de pruebas D01-D20 dentro del Mapa Maestro PLC (`18_mapa_maestro_plc.md`) sin crear un sistema paralelo: reutiliza el mismo formato de mapa, la misma biblioteca y la misma GUI. Introduce el concepto de **perfil**: un subconjunto minimo de variables fisicas autorizadas para un caso experimental especifico, aplicado como filtro sobre el mapa activo.

## Mapas nuevos

- **`MAPA_SIMULACION_COMPLETO`** (`data/plc_maps/mapa_simulacion_completo.json`, 20 variables externas, sin timers/counters/flags): cubre todas las variables fisicas necesarias para simular D01-D20. Usa los nombres ya establecidos del proyecto (`I_Sensor1`, `Q_Aux_Output`, `Q_Contactor_A/B`) mas las genuinamente nuevas (`I_Sensor2`, `I_Speed_Low/Medium/High`, `Q_Pilot_Stop`).
- **`MAPA_BANCO_FISICO`** (`data/plc_maps/mapa_banco_fisico.json`, 15 variables externas): copia exacta de las variables externas de `config/io_map.json`, sin inventar direcciones. Le faltan por diseno las 5 senales nuevas — editable desde la GUI cuando se confirme el cableado real.

Ambos son mapas normales (`schema_version/metadata/naming_convention/variables`), descubiertos automaticamente por `list_plc_maps()` sin ningun cambio de codigo.

## Perfiles

`data/plc_maps/profiles.json` contiene los 20 perfiles en un solo archivo (no 20 mapas). Cada uno:

```json
{
  "profile_id": "D03", "case_id": "D03", "name": "D03 - Arranque/parada de motor",
  "description": "...", "complexity": "baja", "reference_intent": "INT_MOTOR_START_STOP",
  "allowed_variables": ["I_Emergency","I_Reset","I_Start","I_Stop","Q_Alarm","Q_Motor_Enable","Q_Pilot_Fault","Q_Pilot_Run"],
  "notes": "..."
}
```

`simulation_ready`/`hardware_ready`/`missing_hardware_variables` **no se guardan**: se calculan siempre en el momento (`plc_maps.profiles.profile_readiness_summary`) contra los mapas `MAPA_SIMULACION_COMPLETO`/`MAPA_BANCO_FISICO` vigentes en la biblioteca, para que nunca queden desactualizados si el mapa fisico se edita despues.

### Correccion importante sobre `allowed_variables`

La lista original que definia cada perfil (segun la descripcion funcional del caso) no siempre coincidia con lo que la intencion de referencia exige realmente en `ir_builder.get_required_variables_for_intent`. En particular, casi todas las intenciones de motor exigen `I_Emergency` como entrada externa por defecto, y varias tambien exigen `I_Reset`, `Q_Alarm`, `Q_Pilot_Run`, `Q_Pilot_Fault` aunque el caso no las mencione explicitamente. `allowed_variables` se recalculo como la union de la lista original con lo que la intencion realmente requiere (verificado generando cada perfil de punta a punta), documentando cada adicion en el campo `notes` del propio perfil.

### Tabla definitiva

| Perfil | Complejidad | allowed_variables | Intencion de referencia |
|---|---|---|---|
| D01 | baja | I_Emergency, I_Start, Q_Aux_Output | INT_TIMED_PULSE |
| D02 | baja | I_Emergency, I_Sensor1, Q_Pilot_Run | INT_DIRECT_OUTPUT |
| D03 | baja | I_Emergency, I_Reset, I_Start, I_Stop, Q_Alarm, Q_Motor_Enable, Q_Pilot_Fault, Q_Pilot_Run | INT_MOTOR_START_STOP |
| D04 | media | I_Emergency, I_Start, I_Stop, Q_Motor_Enable | INT_MOTOR_LATCH |
| D05 | media | I_Emergency, I_Start, Q_Alarm, Q_Aux_Output, Q_Motor_Enable | INT_EMERGENCY_PRIORITY |
| D06 | media | I_Emergency, I_Reset, I_Sensor1, I_Start, Q_Alarm, Q_Motor_Enable | INT_SAFE_START_ALARM |
| D07 | media | I_Emergency, I_Start, I_Stop, Q_Motor_Enable | INT_DELAYED_START |
| D08 | media | I_Emergency, I_Start, I_Stop, Q_Motor_Enable | INT_DELAYED_STOP |
| D09 | media | I_Emergency, I_Reset, I_Sensor1, Q_Alarm, Q_Aux_Output | INT_COUNTER_PULSES |
| D10 | media | I_Reset, I_Sensor1, Q_Aux_Output | INT_COUNTER_RESET |
| D11 | alta | I_Emergency, I_Reset, I_Start, I_Stop, Q_Alarm, Q_Contactor_A, Q_Pilot_Fault, Q_Pilot_Run | INT_MOTOR_START_STOP (motor_output -> Q_Contactor_A) |
| D12 | alta | I_Emergency, I_Start, I_Stop, Q_Contactor_A, Q_Contactor_B | INT_MUTUAL_INTERLOCK |
| D13 | media | I_Emergency, I_Start, I_Stop, Q_Alarm, Q_Motor_Enable | INT_VFD_ENABLE_NO_ALARM |
| D14 | alta | I_Start, I_Stop, I_Speed_Low, I_Speed_Medium, I_Speed_High, Q_Motor_Enable | *(no implementada)* |
| D15 | alta | I_Emergency, I_Mode_Auto, I_Mode_Manual, I_Start, I_Stop, Q_Motor_Enable | INT_MANUAL_AUTO_MODE |
| D16 | alta | I_Emergency, I_Reset, I_Start, I_Stop, Q_Aux_Output, Q_Motor_Enable | INT_SEQUENCE_THREE_STEPS |
| D17 | alta | I_Emergency, I_Reset, I_Sensor1, I_Start, Q_Alarm | INT_SENSOR_TIMEOUT_ALARM |
| D18 | media | I_Emergency, I_Maintenance, I_Start, Q_Motor_Enable | INT_MAINTENANCE_BLOCK |
| D19 | media | I_Emergency, I_Start, I_Stop, Q_Pilot_Fault, Q_Pilot_Run, Q_Pilot_Stop | *(no implementada)* |
| D20 | alta | I_Emergency, I_Mode_Auto, I_Reset, I_Start, I_Stop, Q_Alarm, Q_Aux_Output, Q_Motor_Enable | INT_AUTO_CYCLE |

Verificado generando cada perfil de punta a punta (`generate_project_package`) contra `MAPA_SIMULACION_COMPLETO` filtrado por su propio perfil: los 18 perfiles con intencion de referencia producen `is_valid=True`. D02, D05 y D11 se verificaron construyendo el `semantic_output` directamente porque el parser por reglas actual tiene ambiguedades de vocabulario preexistentes (`apaga`/`para` mapean siempre a `I_Stop`; no existe la palabra clave `contactor`) que dificultan alcanzarlos con una frase libre — no es una falla del perfil, es una limitacion ya presente en `semantic_parser.py`.

### D14 y D19: sin intencion implementada

`I_Speed_Low/Medium/High` (D14, seleccion de velocidad) y `Q_Pilot_Stop` (D19, piloto de "detenido") no son parametros de ninguna intencion actual en `ir_builder.py`/`semantic_parser.py`. Los perfiles quedan definidos y su `hardware_ready` es calculable, pero generar la logica real requiere una intencion nueva — trabajo futuro, mismo alcance que quedó pendiente para `Level_SP` en la correccion arquitectonica anterior.

## Filtro de perfil (`apply_profile_filter`)

`src/plc_maps/profiles.py::apply_profile_filter(io_map, profile)`: si `profile` es `None` ("GENERAL / SIN FILTRO"), devuelve el mapa sin cambios. Si hay perfil activo, conserva **todas** las variables internas (`M_/T_/C_/R_/F_`, nunca filtradas) y restringe las externas (`I_/Q_`) a `allowed_variables`. Se inyecta en `gui.py::_load_runtime_configuration()`, el unico punto de entrada del mapa al pipeline — por eso `semantic_validator.py`, `ir_builder.py`, `llm_context_builder.py` y el puente C# no necesitaron ningun cambio: el gate de "tags no autorizados" que ya existia rechaza automaticamente cualquier variable fisica fuera del perfil.

## GUI

En el panel "Mapa PLC activo" se agrego un selector "Perfil de prueba" (`GENERAL / SIN FILTRO` + los 20 perfiles) con una etiqueta de estado:

```text
Perfil: D14 - Seleccion de velocidad baja/media/alta
Variables mapa: 20   Variables perfil: 6
Simulation: Ready
Hardware: Faltan 3 variables
```

Cambiar de perfil no modifica el mapa activo en disco — solo afecta que variables ve el parser/LLM en la siguiente generacion, via `_load_runtime_configuration()`.

## Limitaciones conocidas

- D14 y D19 no tienen intencion implementada todavia (ver arriba).
- El parser por reglas actual tiene ambiguedades de vocabulario preexistentes que dificultan alcanzar D02/D05/D11 con frases completamente libres (documentado en el `notes` de cada perfil); estructuralmente los tres estan verificados correctos.
- Los perfiles no reasignan variables fisicas automaticamente (seccion 8 del pedido original): si dos pruebas comparten fisicamente el mismo pulsador con nombres distintos, esa reasignacion queda para un incremento futuro cuando se conozca el cableado final.
