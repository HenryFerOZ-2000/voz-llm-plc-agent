# 04 Paso 2: Mapa I/O

## Propósito del mapa I/O

El archivo `config/io_map.json` define el conjunto autorizado de señales que el agente puede usar durante la generación de código PLC. Este mapa funciona como una **whitelist**, evitando que el sistema invente variables no declaradas.

## Convención de nombres

- `I_` para entradas
- `Q_` para salidas
- `M_` para memorias internas
- `T_` para temporizadores
- `C_` para contadores
- `R_` para auxiliares (detectores de flanco)

## Señales autorizadas actuales

### Entradas

| Tipo | Señales |
|---|---|
| `BOOL` | `I_Start`, `I_Stop`, `I_Emergency`, `I_Reset`, `I_Sensor1`, `I_Mode_Manual`, `I_Mode_Auto`, `I_Maintenance` |

### Salidas

| Tipo | Señales |
|---|---|
| `BOOL` | `Q_Motor_Enable`, `Q_Alarm`, `Q_Pilot_Run`, `Q_Pilot_Fault`, `Q_Aux_Output`, `Q_Contactor_A`, `Q_Contactor_B` |

### Memorias internas

| Tipo | Señales |
|---|---|
| `BOOL` | `M_RunLatch`, `M_FaultLatch`, `M_AutoMode`, `M_ManualMode`, `M_StopDelayActive`, `M_SensorLastState` |
| `INT` | `M_Step` |

### Temporizadores

| Tipo | Señales |
|---|---|
| `TP` | `T_Pulse5s` |
| `TON` | `T_DelayStart`, `T_OperationLimit`, `T_SensorTimeout`, `T_StopDelay`, `T_CycleOn`, `T_CycleOff` |

### Contadores

| Tipo | Señales |
|---|---|
| `CTU` | `C_PulseCount` |

### Auxiliares

| Tipo | Señales |
|---|---|
| `R_TRIG` | `R_SensorPulse`, `R_CycleStart` |

## Función del mapa como whitelist

El mapa I/O cumple tres funciones de control:

1. limitar el espacio de generación del agente,
2. asegurar coherencia con el dominio de automatización modelado,
3. facilitar la verificación posterior del código generado.

En la práctica, el parser y el generador deben construir sus resultados usando únicamente este conjunto de señales.

## Regla de validación asociada

El verificador debe rechazar código PLC si detecta tags fuera del mapa. Esto permite prevenir:

- errores de escritura,
- variables inexistentes,
- suposiciones incorrectas del agente,
- salidas no autorizadas en lógica crítica.

## Relación con seguridad industrial

La lista blanca no es solo una decisión de orden técnico. También es un control de seguridad, porque reduce el riesgo de producir código que manipule elementos no contemplados en el diseño del sistema bajo estudio.
