# 03 Paso 1: Casos de Prueba

## Propósito del banco discreto

El banco inicial de casos discretos permite validar la arquitectura con escenarios industriales básicos y repetibles. Estos casos sirven como referencia para el parser semántico, el catálogo de intenciones y la generación de código PLC.

## Casos iniciales documentados

### D01 - Salida temporizada 5 s

- **Descripción:** activar una salida auxiliar durante un tiempo fijo cuando ocurra una orden de disparo.
- **Intención esperada:** `INT_TIMED_PULSE`
- **Entradas:** `I_Start`, `I_Emergency`
- **Salidas:** `Q_Aux_Output`, `Q_Pilot_Fault`
- **Condición crítica:** la salida no debe mantenerse activada después del tiempo programado ni durante emergencia.
- **Resultado esperado:** el sistema genera un pulso temporizado con literal IEC `T#5s`.
- **Ejemplos de comandos equivalentes:**
  `Activa una salida durante 5 segundos cuando presione Start`
  `Genera un pulso de 5 s con Start`
  `Prende la salida auxiliar por 5 segundos`

### D03 - Arranque/parada de motor

- **Descripción:** controlar el arranque y paro de un motor mediante señales de mando.
- **Intención esperada:** `INT_MOTOR_START_STOP`
- **Entradas:** `I_Start`, `I_Stop`, `I_Emergency`, `I_Reset`
- **Salidas:** `Q_Motor_Enable`, `Q_Alarm`, `Q_Pilot_Run`, `Q_Pilot_Fault`
- **Condición crítica:** `I_Stop` debe tener prioridad sobre `I_Start` y la emergencia debe inhibir la marcha.
- **Resultado esperado:** el sistema produce lógica con enclavamiento de marcha y reset manual después de emergencia.
- **Ejemplos de comandos equivalentes:**
  `Haz que el motor se encienda con Start y se apague con Stop`
  `Programa el arranque y paro del motor`
  `Controla el motor con start y stop`

### D04 - Enclavamiento

- **Descripción:** mantener un estado de marcha o activación mediante memoria interna.
- **Intención esperada:** `INT_MOTOR_LATCH`
- **Entradas:** `I_Start`, `I_Stop`
- **Salidas:** `Q_Motor_Enable`
- **Condición crítica:** la memoria no debe mantenerse ante una condición de paro que invalide la orden.
- **Resultado esperado:** el sistema identifica el caso como lógica de memoria o enclavamiento interno.
- **Ejemplos de comandos equivalentes:**
  `Mantén el motor enclavado hasta que se presione Stop`
  `Haz un latch de marcha para el motor`
  `Activa memoria de marcha para el motor`

### D05 - Paro de emergencia

- **Descripción:** forzar el apagado inmediato de salidas críticas ante condición de emergencia.
- **Intención esperada:** `INT_EMERGENCY_PRIORITY`
- **Entradas:** `I_Emergency`, `I_Reset`
- **Salidas:** `Q_Motor_Enable`, `Q_Alarm`, `Q_Pilot_Fault`, `Q_Contactor_A`, `Q_Contactor_B`
- **Condición crítica:** la emergencia debe tener prioridad absoluta y no debe provocar autoarranque al liberarse.
- **Resultado esperado:** la lógica apaga salidas críticas, activa indicación de fallo y exige reset manual.
- **Ejemplos de comandos equivalentes:**
  `El paro de emergencia debe apagar el motor siempre`
  `Si hay emergencia apaga todo`
  `Con emergencia activa apaga el motor`

### D07 - Arranque con retardo

- **Descripción:** arrancar un motor después de un tiempo de espera programado.
- **Intención esperada:** `INT_DELAYED_START`
- **Entradas:** `I_Start`, `I_Stop`, `I_Emergency`, `I_Reset`
- **Salidas:** `Q_Motor_Enable`, `Q_Pilot_Run`, `Q_Pilot_Fault`
- **Condición crítica:** el retardo debe anularse con stop o emergencia.
- **Resultado esperado:** el sistema genera una llamada a temporizador con literal IEC válido y posterior habilitación del motor.
- **Ejemplos de comandos equivalentes:**
  `Arranca el motor después de un retardo de 3 segundos`
  `Luego de 4 segundos arranca el motor`
  `Tras 3 segundos enciende el motor`

### D09 - Contador de pulsos

- **Descripción:** contar eventos discretos provenientes de un sensor y activar una acción al alcanzar un umbral.
- **Intención esperada:** `INT_COUNTER_PULSES`
- **Entradas:** `I_Sensor1`, `I_Reset`
- **Salidas:** `Q_Alarm`, `Q_Pilot_Fault`
- **Condición crítica:** el conteo debe poder reiniciarse y no debe usar variables fuera del mapa autorizado.
- **Resultado esperado:** se genera un bloque de contador `CTU` con valor preset configurable.
- **Ejemplos de comandos equivalentes:**
  `Cuenta 5 pulsos del sensor y activa la alarma`
  `Cuenta cinco pulsos del sensor y activa alarma`
  `Cuenta 12 pulsos del sensor`

## Observación metodológica

No todos los casos del banco discreto tienen todavía una plantilla ST específica en el MVP. Sin embargo, todos resultan útiles para:

- diseñar el catálogo de intenciones,
- medir cobertura semántica del parser,
- definir prioridades de implementación,
- construir evidencia experimental para la tesis.
