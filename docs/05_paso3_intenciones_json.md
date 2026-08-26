# 05 Paso 3: Intenciones, Normalizacion y JSON

## Proposito de esta etapa

La tercera etapa del sistema transforma un comando industrial en lenguaje natural a una representacion semantica controlada. En el MVP actual esta etapa no usa todavia un LLM externo; se basa en un parser local por reglas.

El flujo interno es:

`texto del usuario -> normalizacion -> extraccion de tiempo -> extraccion de tags -> deteccion de intencion -> JSON semantico`

## El JSON semantico no depende de la plataforma

El mismo JSON semantico puede alimentar la generacion de artefactos para:

- `OPENPLC_ST`
- `CODESYS_ST`

La plataforma seleccionada no cambia la intencion detectada. Solo cambia la forma de renderizar declaraciones, ubicaciones fisicas y archivos de salida.

## Diferencia entre intencion detectada y plantilla implementada

Esta correccion del proyecto introduce una distincion explicita:

- `intent_id` indica la intencion semantica detectada por el parser.
- `template_implemented` indica si el generador dispone de una plantilla ST funcional para esa intencion.

Si una intencion es detectada pero no tuviera plantilla implementada, el sistema no debe aceptar un fallback seguro como si fuera una solucion funcional. En ese caso:

- el generador marca `TEMPLATE_NOT_IMPLEMENTED`,
- el verificador responde `is_valid = false`,
- el artefacto puede guardarse para trazabilidad, pero no se considera apto para PLC.

## Funciones principales del parser

El archivo `src/semantic_parser.py` mantiene estas funciones:

- `normalize_text(text: str) -> str`
- `extract_time(text: str) -> str | None`
- `extract_tags(text: str) -> dict`
- `detect_intent(normalized_text, tags, time_value) -> tuple[str, float]`
- `parse_command(command_text: str) -> dict`

## Contrato JSON del parser

El parser devuelve una estructura como la siguiente:

```json
{
  "intent_id": "INT_MOTOR_START_STOP",
  "case_id": null,
  "command_text": "Haz que el motor se encienda con Start y se apague con Stop",
  "parameters": {
    "trigger_input": "I_Start",
    "stop_input": "I_Stop",
    "emergency_input": "I_Emergency",
    "reset_input": "I_Reset",
    "motor_output": "Q_Motor_Enable",
    "alarm_output": "Q_Alarm",
    "run_indicator": "Q_Pilot_Run",
    "fault_indicator": "Q_Pilot_Fault",
    "run_latch": "M_RunLatch",
    "fault_latch": "M_FaultLatch"
  },
  "confidence": 0.97
}
```

Si el sistema no reconoce una intencion:

```json
{
  "intent_id": "INT_UNKNOWN",
  "case_id": null,
  "command_text": "Comando no reconocido",
  "parameters": {},
  "confidence": 0.0
}
```

## Normalizacion linguistica

`normalize_text(...)`:

- convierte a minusculas,
- elimina tildes,
- elimina signos innecesarios,
- reemplaza sinonimos industriales,
- convierte numeros escritos a numeros canonicos cuando aparecen en contextos de tiempo o pulsos.

Ejemplos:

- `inicio`, `arranque`, `marcha` -> `start`
- `paro`, `parada`, `detener`, `apaga` -> `stop`
- `emergencia`, `paro de emergencia` -> `emergency`
- `prende`, `activa`, `activar` -> `enciende`
- `cinco segundos` -> `5 segundos`

## Extraccion de tiempos

`extract_time(...)` detecta:

- `5 segundos`, `5 s`, `5 seg`
- `10 segundos`
- `1 minuto`
- `2 minutos`
- `uno`, `dos`, `tres`, `cuatro`, `cinco`, `seis`, `siete`, `ocho`, `nueve`, `diez`

Salida IEC:

- `T#5s`
- `T#10s`
- `T#1m`
- `T#2m`

## Extraccion de tags autorizados

`extract_tags(...)` mapea expresiones del usuario a tags del `io_map.json`.

Mapeos principales:

- `start`, `inicio`, `marcha` -> `I_Start`
- `stop`, `paro`, `parada` -> `I_Stop`
- `emergency`, `emergencia` -> `I_Emergency`
- `reset`, `reinicio` -> `I_Reset`
- `sensor` -> `I_Sensor1`
- `motor` -> `Q_Motor_Enable`
- `alarma` -> `Q_Alarm`
- `piloto marcha` -> `Q_Pilot_Run`
- `piloto falla` -> `Q_Pilot_Fault`
- `salida auxiliar`, `salida` -> `Q_Aux_Output`

## Intenciones relevantes del MVP actual

### `INT_TIMED_PULSE`

Descripcion:
Activa una salida durante un tiempo determinado al recibir un disparo.

Ejemplo semantico:

```json
{
  "trigger_input": "I_Start",
  "emergency_input": "I_Emergency",
  "output": "Q_Aux_Output",
  "duration": "T#8s",
  "timer": "T_Pulse5s"
}
```

### `INT_MOTOR_START_STOP`

Descripcion:
Arranque y parada de motor con Start, Stop, emergencia y reset de falla.

### `INT_DELAYED_START`

Descripcion:
El motor arranca despues de un retardo programado.

Ejemplo:

```json
{
  "trigger_input": "I_Start",
  "stop_input": "I_Stop",
  "emergency_input": "I_Emergency",
  "motor_output": "Q_Motor_Enable",
  "delay_time": "T#10s",
  "timer": "T_DelayStart"
}
```

### `INT_DELAYED_STOP`

Descripcion:
El motor arranca con Start, pero cuando se presiona Stop se apaga despues de un tiempo. La emergencia apaga de inmediato.

Ejemplo:

```json
{
  "trigger_input": "I_Start",
  "stop_input": "I_Stop",
  "emergency_input": "I_Emergency",
  "motor_output": "Q_Motor_Enable",
  "run_latch": "M_RunLatch",
  "stop_delay_active": "M_StopDelayActive",
  "stop_delay_time": "T#10s",
  "timer": "T_StopDelay"
}
```

### `INT_EMERGENCY_PRIORITY`

Descripcion:
La emergencia apaga salidas criticas inmediatamente.

### `INT_COUNTER_PULSES`

Descripcion:
Cuenta pulsos del sensor y activa una salida al alcanzar un preset.

Ejemplo:

```json
{
  "pulse_input": "I_Sensor1",
  "reset_input": "I_Reset",
  "emergency_input": "I_Emergency",
  "output": "Q_Alarm",
  "counter": "C_PulseCount",
  "edge_detector": "R_SensorPulse",
  "preset": 5
}
```

## Criterio de interpretacion actual

El parser trabaja por significado, no por frase exacta. Por eso reconoce parafrasis como:

- `Haz que el motor se encienda con Start y se apague con Stop`
- `Programa arranque y paro de motor`
- `Con inicio prende el motor y con paro lo detienes`
- `Arranca el motor despues de 10 segundos`
- `Cuando presione stop el motor debe apagarse despues de 10 segundos`
- `Cuenta cinco pulsos del sensor y activa la alarma`
