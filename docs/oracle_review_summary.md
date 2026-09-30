# Revision de Oracles (D01-D20, P01-P12)

Generado: 2026-09-30T14:19:44. Fuente: `data/experiment_oracles/*.json` (la especificacion formal es el JSON; este resumen solo facilita la revision).

- Oracles: 32 · schema valid 32/32 · review items abiertos 0 · discretos ejecutables 20/20 · PID ejecutables 0/12 · capability gaps 18
- Listos para aprobacion humana: ninguno
- Sin review items abiertos: 32 - D01, D02, D03, D04, D05, D06, D07, D08, D09, D10, D11, D12, D13, D14, D15, D16, D17, D18, D19, D20, P01, P02, P03, P04, P05, P06, P07, P08, P09, P10, P11, P12
- Con review items abiertos: 0 - 
- Ejecutables hoy: D01, D02, D03, D04, D05, D06, D07, D08, D09, D10, D11, D12, D13, D14, D15, D16, D17, D18, D19, D20
- Requieren extension del Runtime: P01, P02, P03, P04, P05, P06, P07, P08, P09, P10, P11, P12

Estados: `DRAFT_REVIEWED` = revisado por IA (schema + revision semantica), SIN aprobacion formal. `FROZEN` = aprobado por el investigador.

## D01 - Salida temporizada de 5 s

- **Estado:** FROZEN v1 · complejidad LOW · hash `a16544902b49`
- **Objetivo original:** Activar una salida digital durante 5 segundos al presionar un pulsador.
- **Comando canonico:** Activa una salida digital durante 5 segundos al presionar un pulsador.
- **Comportamiento evaluado:** Al presionar el pulsador de disparo, la salida auxiliar se activa y permanece activa 5 s; despues se desactiva.
- **Roles:** START (I), AUX_OUTPUT (O)
- **Prueba principal:**
  1. START=ON -> AUX_OUTPUT=ON
  2. START=OFF -> AUX_OUTPUT=OFF [transicion AUX_OUTPUT a 5000 ms, -300/+700 ms]
- **Condicion de exito:** Todas las expectativas evaluables de test_sequence (incluidas ventanas temporales) deben cumplirse.
- **Invariante critica:** ninguna
- **Runtime:** EXECUTABLE_NOW (BOOL)
- **Convenciones experimentales (para hacerlo medible):**
  - C-PULSE: Un 'pulsador' se modela como un pulso de 300 ms (ON y luego OFF).
  - C-TIMING: Temporizaciones: transicion nominal con tolerancia -300 ms / +700 ms medida en el bridge (reloj monotono); las ventanas de evaluacion dejan libre esa banda.
  - C-D01-START: 'Activar durante 5 s cuando se presione' implica que la salida se activa al presionar (en <= 300 ms) y dura 5 s desde la pulsacion, aunque el pulsador se suelte antes.
  - C-D01-SCOPE: No se evalua el redisparo ni mantener el pulsador mas de 5 s (no definidos por el caso).
- **Review items:** ninguno abierto
- **SYSTEM_CAPABILITY_GAP (HIGH):** INT_TIMED_PULSE usa TON: la salida se activa DESPUES de 5 s con la entrada mantenida; con un pulsador breve no se activa.

## D02 - Piloto que sigue al sensor

- **Estado:** FROZEN v1 · complejidad LOW · hash `bc3e29558b2b`
- **Objetivo original:** Encender una lampara cuando una entrada digital este activa.
- **Comando canonico:** Enciende una lámpara mientras una entrada digital esté activa.
- **Comportamiento evaluado:** El piloto luminoso esta encendido mientras el sensor este activo y apagado en caso contrario.
- **Roles:** SENSOR (I), LAMP (O)
- **Prueba principal:**
  1. espera -> LAMP=OFF
  2. SENSOR=ON -> LAMP=ON
  3. SENSOR=OFF -> LAMP=OFF
  4. SENSOR=ON -> LAMP=ON
  5. SENSOR=OFF -> LAMP=OFF
- **Condicion de exito:** Todas las expectativas evaluables de test_sequence (incluidas ventanas temporales) deben cumplirse.
- **Invariante critica:** ninguna
- **Runtime:** EXECUTABLE_NOW (BOOL)
- **Convenciones experimentales (para hacerlo medible):**
  - C-D02: 'Mientras el sensor este activo' se verifica en dos ciclos ON/OFF para detectar memoria indebida.
- **Review items:** ninguno abierto

## D03 - Arranque/parada de motor con memoria de marcha

- **Estado:** FROZEN v1 · complejidad LOW · hash `b444a550d900`
- **Objetivo original:** Arranque y paro de un motor con pulsadores independientes START y STOP. Un pulso de START enciende el motor y este permanece encendido al soltar START (memoria de marcha); STOP lo apaga y tiene prioridad.
- **Comando canonico:** Enciende un motor con Start, mantenlo encendido al soltar el pulsador y apágalo con Stop.
- **Comportamiento evaluado:** Arranque y paro de un motor con pulsadores independientes START y STOP. Un pulso de START enciende el motor y este permanece encendido al soltar START (memoria de marcha); STOP lo apaga y tiene prioridad.
- **Roles:** START (I), STOP (I), MOTOR_MAIN (O)
- **Prueba principal:**
  1. START=ON -> MOTOR_MAIN=ON
  2. START=OFF -> MOTOR_MAIN=ON
  3. STOP=ON -> MOTOR_MAIN=OFF
  4. STOP=OFF -> MOTOR_MAIN=OFF
- **Condicion de exito:** Todas las expectativas evaluables de test_sequence deben cumplirse.
- **Invariante critica:** ninguna
- **Runtime:** EXECUTABLE_NOW (BOOL)
- **Convenciones experimentales (para hacerlo medible):** ninguna
- **Review items:** ninguno abierto

## D04 - Motor enclavado con memoria de marcha

- **Estado:** FROZEN v1 · complejidad MEDIUM · hash `ecd6568dd2a0`
- **Objetivo original:** Arranque enclavado de motor con memoria de marcha.
- **Comando canonico:** Enclava un motor con Start para que permanezca encendido al soltar el pulsador, y apágalo con Stop.
- **Comportamiento evaluado:** Un pulso de arranque mantiene el motor en marcha (memoria de enclavamiento) hasta que se presiona el paro.
- **Roles:** START (I), STOP (I), MOTOR_MAIN (O)
- **Prueba principal:**
  1. START=ON -> MOTOR_MAIN=ON
  2. START=OFF -> MOTOR_MAIN=ON
  3. STOP=ON -> MOTOR_MAIN=OFF
  4. STOP=OFF -> MOTOR_MAIN=OFF
  5. START=ON -> MOTOR_MAIN=ON
  6. START=OFF -> MOTOR_MAIN=ON
- **Condicion de exito:** Todas las expectativas evaluables de test_sequence (incluidas ventanas temporales) deben cumplirse.
- **Invariante critica:** ninguna
- **Runtime:** EXECUTABLE_NOW (BOOL)
- **Convenciones experimentales (para hacerlo medible):**
  - C-PULSE: Un 'pulsador' se modela como un pulso de 300 ms (ON y luego OFF).
  - C-D04: El segundo ciclo detecta memorias que no se rearman tras el paro.
- **Review items:** ninguno abierto

## D05 - Prioridad del disparo de seguridad sobre el arranque

- **Estado:** FROZEN v1 · complejidad MEDIUM · hash `e5cc1a4d71c2`
- **Objetivo original:** Paro de emergencia con prioridad sobre cualquier orden de arranque.
- **Comando canonico:** Enciende un motor con Start solo si la condición de seguridad está normal. Si se activa la condición de emergencia, apaga el motor y bloquea el arranque mientras permanezca activa.
- **Comportamiento evaluado:** Un disparo de seguridad apaga el motor y tiene prioridad sobre cualquier orden de arranque: mientras esta activo el motor nunca marcha.
- **Roles:** START_REQUEST (I), SAFETY_TRIP (I), MOTOR_MAIN (O)
- **Prueba principal:**
  1. START_REQUEST=ON -> MOTOR_MAIN=ON
  2. SAFETY_TRIP=ON -> MOTOR_MAIN=OFF
  3. START_REQUEST=OFF -> MOTOR_MAIN=OFF
  4. START_REQUEST=ON -> MOTOR_MAIN=OFF
  5. SAFETY_TRIP=OFF, START_REQUEST=OFF -> no especificado: MOTOR_MAIN
- **Condicion de exito:** Todas las expectativas evaluables de test_sequence (incluidas ventanas temporales) deben cumplirse.
- **Invariante critica:** INV_TRIP_MOTOR: SAFETY_TRIP => NOT MOTOR_MAIN (100 ms de propagacion).
- **Runtime:** EXECUTABLE_NOW (BOOL)
- **Convenciones experimentales (para hacerlo medible):**
  - C-D05-TRIP: SAFETY_TRIP es una senal LOGICA de seguridad simulada/autorizada para el ensayo (activa = TRUE). No es el E-stop fisico real (externo al PLC en el banco) y el Oracle nunca exige una I_Emergency en el mapa fisico.
  - C-D05-START: START_REQUEST explicito: hace observable que el disparo APAGA un motor en marcha y que ignora nuevas ordenes de arranque.
- **Review items:** ninguno abierto
- **SYSTEM_CAPABILITY_GAP (HIGH):** INT_EMERGENCY_PRIORITY no tiene logica de arranque: el motor nunca se activa y step_1 falla.

## D06 - Alarma por intento de arranque sin condicion de seguridad

- **Estado:** FROZEN v1 · complejidad MEDIUM · hash `ee564bbaf58f`
- **Objetivo original:** Activar alarma si se intenta arrancar sin condicion de seguridad.
- **Comando canonico:** Si se intenta arrancar el sistema sin cumplir la condición de seguridad, activa una alarma.
- **Comportamiento evaluado:** Un intento de arranque sin la condicion de seguridad activa la alarma; con la condicion presente, el arranque no genera alarma.
- **Roles:** START_REQUEST (I), SAFETY_OK (I), ALARM (O)
- **Prueba principal:**
  1. START_REQUEST=ON -> ALARM=OFF
  2. START_REQUEST=OFF -> -
  3. SAFETY_OK=OFF -> no especificado: ALARM
  4. START_REQUEST=ON -> ALARM=ON
- **Condicion de exito:** Todas las expectativas evaluables de test_sequence (incluidas ventanas temporales) deben cumplirse.
- **Invariante critica:** ninguna
- **Runtime:** EXECUTABLE_NOW (BOOL)
- **Convenciones experimentales (para hacerlo medible):**
  - C-D06-SCOPE: Solo se evalua la ACTIVACION de la alarma. La politica de borrado de alarma y la habilitacion del motor estan fuera del alcance de D06.
  - C-D06-ORDER: El arranque seguro se prueba primero (alarma apagada) y el inseguro despues, para no depender de como se borra la alarma.
- **Review items:** ninguno abierto

## D07 - Arranque retardado de 3 segundos

- **Estado:** FROZEN v2 · complejidad MEDIUM · hash `e1aeae2999ce`
- **Objetivo original:** Arranque retardado 3 s.
- **Comando canonico:** Mientras Start permanezca activo, espera 3 segundos antes de encender el motor.
- **Comportamiento evaluado:** Con la orden de arranque activa, el motor permanece apagado durante 3 s y despues se enciende.
- **Roles:** START (I), MOTOR_MAIN (O)
- **Prueba principal:**
  1. START=ON -> MOTOR_MAIN=ON [transicion MOTOR_MAIN a 3000 ms, -300/+700 ms]
- **Condicion de exito:** Todas las expectativas evaluables de test_sequence (incluidas ventanas temporales) deben cumplirse.
- **Invariante critica:** ninguna
- **Runtime:** EXECUTABLE_NOW (BOOL)
- **Convenciones experimentales (para hacerlo medible):**
  - C-D07-HELD: START permanece ON durante toda la prueba (senal mantenida). No se exige memoria de marcha: el comportamiento al retirar START no se evalua (no solicitado por el caso).
  - C-TIMING: Temporizaciones: transicion nominal con tolerancia -300 ms / +700 ms medida en el bridge (reloj monotono); las ventanas de evaluacion dejan libre esa banda.
- **Review items:** ninguno abierto

## D08 - Apagar el motor tras 10 s de operacion continua

- **Estado:** FROZEN v1 · complejidad MEDIUM · hash `5fbb25e9b5f9`
- **Objetivo original:** Apagar motor despues de 10 segundos de operacion continua.
- **Comando canonico:** Al activar Start, enciende el motor y apágalo automáticamente después de 10 segundos de funcionamiento continuo.
- **Comportamiento evaluado:** Al activar Start (pulso) el motor se enciende y se apaga automaticamente tras 10 s de funcionamiento continuo.
- **Roles:** START (I), MOTOR_MAIN (O)
- **Prueba principal:**
  1. START=ON -> MOTOR_MAIN=ON
  2. START=OFF -> MOTOR_MAIN=OFF [transicion MOTOR_MAIN a 10000 ms, -500/+1000 ms]
- **Condicion de exito:** Todas las expectativas evaluables de test_sequence (incluidas ventanas temporales) deben cumplirse.
- **Invariante critica:** ninguna
- **Runtime:** EXECUTABLE_NOW (BOOL)
- **Convenciones experimentales (para hacerlo medible):**
  - C-D08-PULSE: 'Al activar Start' = pulso de 300 ms; los 10 s de funcionamiento continuo se cuentan desde la activacion.
  - C-D08-TOLERANCE: Tolerancia FUNCIONAL, no metrologica: transicion nominal 10000 ms, -500/+1000 ms (5 %/10 % del tiempo), que cubre el ciclo del PLC, el muestreo de 50 ms y la temporizacion de PLCSIM. Ventanas: ON [300, 9500] ms, OFF [11000, 12000] ms.
  - C-PULSE: Un 'pulsador' se modela como un pulso de 300 ms (ON y luego OFF).
- **Review items:** ninguno abierto

## D09 - Contar 5 pulsos y activar una salida

- **Estado:** FROZEN v1 · complejidad MEDIUM · hash `f84e7a9449f0`
- **Objetivo original:** Contar 5 pulsos y activar una salida.
- **Comando canonico:** Cuenta 5 pulsos de una entrada digital y, al llegar al quinto, activa una salida.
- **Comportamiento evaluado:** Cada pulso del sensor incrementa un contador; al alcanzar 5 pulsos se activa la salida.
- **Roles:** PULSE_INPUT (I), RESET (I, opcional), COUNT_OUTPUT (O)
- **Prueba principal:**
  1. PULSE_INPUT=ON -> -
  2. PULSE_INPUT=OFF -> COUNT_OUTPUT=OFF
  3. PULSE_INPUT=ON -> -
  4. PULSE_INPUT=OFF -> COUNT_OUTPUT=OFF
  5. PULSE_INPUT=ON -> -
  6. PULSE_INPUT=OFF -> COUNT_OUTPUT=OFF
  7. PULSE_INPUT=ON -> -
  8. PULSE_INPUT=OFF -> COUNT_OUTPUT=OFF
  9. PULSE_INPUT=ON -> COUNT_OUTPUT=ON
  10. PULSE_INPUT=OFF -> COUNT_OUTPUT=ON
- **Condicion de exito:** Todas las expectativas evaluables de test_sequence (incluidas ventanas temporales) deben cumplirse.
- **Invariante critica:** ninguna
- **Runtime:** EXECUTABLE_NOW (BOOL)
- **Convenciones experimentales (para hacerlo medible):**
  - C-D09-PULSE: Pulsos de 200 ms ON / 200 ms OFF (flancos claros para cualquier detector de flanco).
  - C-D09-HOLD: 'Activar una salida al alcanzar el umbral': la salida permanece activa tras el quinto pulso.
  - C-D09-INIT: El contador parte de cero: con RESET ligado se pulsa; sin RESET se confia en el reinicio no retentivo de la descarga (si la salida ya estuviera activa, la precondicion falla -> REVIEW).
- **Review items:** ninguno abierto

## D10 - Reinicio del contador mediante pulsador

- **Estado:** FROZEN v1 · complejidad MEDIUM · hash `816f458b0ee7`
- **Objetivo original:** Resetear contador mediante pulsador.
- **Comando canonico:** Cuenta 5 pulsos y activa una salida; al presionar Reset, reinicia el contador a cero y apaga la salida.
- **Comportamiento evaluado:** Tras contar hasta el umbral (salida activa), el pulsador de reinicio devuelve el contador a su estado inicial.
- **Roles:** PULSE_INPUT (I), RESET (I), COUNT_OUTPUT (O)
- **Prueba principal:**
  1. PULSE_INPUT=ON -> -
  2. PULSE_INPUT=OFF -> COUNT_OUTPUT=OFF
  3. PULSE_INPUT=ON -> -
  4. PULSE_INPUT=OFF -> COUNT_OUTPUT=OFF
  5. PULSE_INPUT=ON -> -
  6. PULSE_INPUT=OFF -> COUNT_OUTPUT=OFF
  7. PULSE_INPUT=ON -> -
  8. PULSE_INPUT=OFF -> COUNT_OUTPUT=OFF
  9. PULSE_INPUT=ON -> COUNT_OUTPUT=ON
  10. PULSE_INPUT=OFF -> COUNT_OUTPUT=ON
  11. RESET=ON -> COUNT_OUTPUT=OFF
  12. RESET=OFF -> COUNT_OUTPUT=OFF
  13. PULSE_INPUT=ON -> -
  14. PULSE_INPUT=OFF -> COUNT_OUTPUT=OFF
  15. PULSE_INPUT=ON -> -
  16. PULSE_INPUT=OFF -> COUNT_OUTPUT=OFF
  17. PULSE_INPUT=ON -> -
  18. PULSE_INPUT=OFF -> COUNT_OUTPUT=OFF
  19. PULSE_INPUT=ON -> -
  20. PULSE_INPUT=OFF -> COUNT_OUTPUT=OFF
- **Condicion de exito:** Todas las expectativas evaluables de test_sequence (incluidas ventanas temporales) deben cumplirse.
- **Invariante critica:** ninguna
- **Runtime:** EXECUTABLE_NOW (BOOL)
- **Convenciones experimentales (para hacerlo medible):**
  - C-D10-D09: D10 se evalua como extension del contador de D09: umbral 5 pulsos, salida activa al alcanzarlo.
  - C-D10-COUNTED: Antes del reset se comprueba que existio un estado contado (salida activa tras 5 pulsos).
  - C-D10-INITIAL: 'Estado inicial' se verifica con 4 pulsos tras el reset: la salida no se activa (el conteo parte de cero y no continua desde 5).
  - C-D09-PULSE: Pulsos de 200 ms ON / 200 ms OFF.
- **Review items:** ninguno abierto
- **SYSTEM_CAPABILITY_GAP (MEDIUM):** Con el comando v2 la plantilla INT_COUNTER_PULSES (con reset_input) cumple el caso; si el interprete elige INT_COUNTER_RESET (referencia legacy) no hay conteo ni salida.

## D11 - Contactor con enclavamiento logico y proteccion de emergencia

- **Estado:** FROZEN v1 · complejidad HIGH · hash `29fcc4038f50`
- **Objetivo original:** Control de contactor con enclavamiento electrico/logico.
- **Comando canonico:** Controla un contactor con Start y Stop usando enclavamiento de marcha.
- **Comportamiento evaluado:** Start activa el contactor, que queda enclavado al soltar Start; Stop lo desactiva.
- **Roles:** START (I), STOP (I), CONTACTOR (O)
- **Prueba principal:**
  1. START=ON -> CONTACTOR=ON
  2. START=OFF -> CONTACTOR=ON
  3. STOP=ON -> CONTACTOR=OFF
  4. STOP=OFF -> CONTACTOR=OFF
- **Condicion de exito:** Todas las expectativas evaluables de test_sequence (incluidas ventanas temporales) deben cumplirse.
- **Invariante critica:** ninguna
- **Runtime:** EXECUTABLE_NOW (BOOL)
- **Convenciones experimentales (para hacerlo medible):**
  - C-PULSE: Un 'pulsador' se modela como un pulso de 300 ms (ON y luego OFF).
- **Review items:** ninguno abierto

## D12 - Evitar la activacion simultanea de dos contactores

- **Estado:** FROZEN v2 · complejidad HIGH · hash `ae4562d0acfb`
- **Objetivo original:** Interlock: evitar activacion simultanea de dos contactores.
- **Comando canonico:** Controla dos contactores con órdenes independientes e impide que ambos estén activos al mismo tiempo.
- **Comportamiento evaluado:** Cada contactor sigue su propia solicitud; nunca pueden estar activos los dos a la vez. No se define prioridad ni transferencia.
- **Roles:** REQUEST_A (I), REQUEST_B (I), CONTACTOR_A (O), CONTACTOR_B (O)
- **Prueba principal:**
  1. REQUEST_A=ON, REQUEST_B=OFF -> CONTACTOR_A=ON, CONTACTOR_B=OFF
  2. REQUEST_A=OFF, REQUEST_B=ON -> CONTACTOR_A=OFF, CONTACTOR_B=ON
  3. REQUEST_A=OFF, REQUEST_B=OFF -> CONTACTOR_A=OFF, CONTACTOR_B=OFF
  4. REQUEST_A=ON, REQUEST_B=ON -> no especificado: CONTACTOR_A, CONTACTOR_B
- **Condicion de exito:** Todas las expectativas evaluables de test_sequence (incluidas ventanas temporales) deben cumplirse.
- **Invariante critica:** INV_AB_EXCLUSIVE: CONTACTOR_A y CONTACTOR_B nunca activos a la vez (todas las muestras).
- **Runtime:** EXECUTABLE_NOW (BOOL)
- **Convenciones experimentales (para hacerlo medible):**
  - C-D12-REQ: Las solicitudes son senales mantenidas; cada contactor sigue su solicitud (tests 1-3, definidos por el investigador). No se exige transferencia, prioridad A/B, Stop general ni enclavamiento mantenido.
- **Review items:** ninguno abierto
- **SYSTEM_CAPABILITY_GAP (HIGH):** INT_MUTUAL_INTERLOCK usa trigger_input/stop_input como ordenes y enclava los contactores (nunca los desactiva).

## D13 - Variador habilitado solo sin alarma

- **Estado:** FROZEN v1 · complejidad MEDIUM · hash `49452454c072`
- **Objetivo original:** Activar variador solo si no existe alarma.
- **Comando canonico:** Ante una orden de marcha, habilita el variador solo si no existe una alarma activa.
- **Comportamiento evaluado:** Con solicitud de marcha, el variador se habilita solo si no existe alarma activa; con alarma activa nunca se habilita.
- **Roles:** RUN_REQUEST (I), ALARM_ACTIVE (I), VFD_ENABLE (O)
- **Prueba principal:**
  1. espera -> VFD_ENABLE=OFF
  2. RUN_REQUEST=ON, ALARM_ACTIVE=OFF -> VFD_ENABLE=ON
  3. ALARM_ACTIVE=ON -> VFD_ENABLE=OFF
- **Condicion de exito:** Todas las expectativas evaluables de test_sequence (incluidas ventanas temporales) deben cumplirse.
- **Invariante critica:** INV_ALARM_VFD: ALARM_ACTIVE => NOT VFD_ENABLE.
- **Runtime:** EXECUTABLE_NOW (BOOL)
- **Convenciones experimentales (para hacerlo medible):**
  - C-D13-ALARM: ALARM_ACTIVE es una condicion de ENTRADA del ensayo (simulada). No se exige como se genera. Corrige la convencion legacy que trataba la alarma como salida (Q_Alarm).
  - C-D13-REQUEST: RUN_REQUEST es la orden de habilitacion: sin ella el variador no se habilita (step_0).
- **Review items:** ninguno abierto
- **SYSTEM_CAPABILITY_GAP (HIGH):** INT_VFD_ENABLE_NO_ALARM lee alarm_output (una salida que nadie escribe): ALARM_ACTIVE no se resuelve -> REVIEW.

## D14 - Seleccion de velocidad baja/media/alta

- **Estado:** FROZEN v1 · complejidad HIGH · hash `40c19b18cdc0`
- **Objetivo original:** Seleccionar velocidad baja/media/alta mediante entradas digitales.
- **Comando canonico:** Selecciona velocidad baja, media o alta mediante tres entradas digitales, activando únicamente la velocidad seleccionada.
- **Comportamiento evaluado:** Tres entradas digitales seleccionan una velocidad discreta; solo la salida de la velocidad seleccionada se activa.
- **Roles:** SPEED_LOW_CMD (I), SPEED_MEDIUM_CMD (I), SPEED_HIGH_CMD (I), SPEED_LOW (O), SPEED_MEDIUM (O), SPEED_HIGH (O)
- **Prueba principal:**
  1. SPEED_LOW_CMD=ON -> SPEED_LOW=ON, SPEED_MEDIUM=OFF, SPEED_HIGH=OFF
  2. SPEED_LOW_CMD=OFF, SPEED_MEDIUM_CMD=ON -> SPEED_LOW=OFF, SPEED_MEDIUM=ON, SPEED_HIGH=OFF
  3. SPEED_MEDIUM_CMD=OFF, SPEED_HIGH_CMD=ON -> SPEED_LOW=OFF, SPEED_MEDIUM=OFF, SPEED_HIGH=ON
  4. SPEED_LOW_CMD=ON, SPEED_HIGH_CMD=ON -> no especificado: SPEED_LOW, SPEED_MEDIUM, SPEED_HIGH
- **Condicion de exito:** Todas las expectativas evaluables de test_sequence (incluidas ventanas temporales) deben cumplirse.
- **Invariante critica:** ninguna
- **Runtime:** EXECUTABLE_NOW (BOOL)
- **Convenciones experimentales (para hacerlo medible):**
  - C-D14-ONEHOT: Seleccion discreta one-hot: tres salidas digitales SPEED_*; sin frecuencia en Hz ni arranque/paro. Sin ningun comando la salida no se evalua.
- **Review items:** ninguno abierto
- **SYSTEM_CAPABILITY_GAP (HIGH):** No existe intent para D14 en el parser/IR (profiles.json: 'trabajo futuro').

## D15 - Modo manual/automatico para la habilitacion del motor

- **Estado:** FROZEN v1 · complejidad HIGH · hash `4c4d43dcb25f`
- **Objetivo original:** Modo manual/automatico para habilitacion del motor.
- **Comando canonico:** Implementa modo Manual y Automático para el motor: en Manual responde a una orden manual y en Automático a una orden automática.
- **Comportamiento evaluado:** MODE_AUTO elige que orden habilita el motor: en manual solo MANUAL_COMMAND, en automatico solo AUTO_COMMAND; la orden del modo no seleccionado se ignora.
- **Roles:** MODE_AUTO (I), MANUAL_COMMAND (I), AUTO_COMMAND (I), MOTOR_MAIN (O)
- **Prueba principal:**
  1. MANUAL_COMMAND=ON, AUTO_COMMAND=OFF -> MOTOR_MAIN=ON
  2. MANUAL_COMMAND=OFF, AUTO_COMMAND=ON -> MOTOR_MAIN=OFF
  3. MODE_AUTO=ON, AUTO_COMMAND=OFF -> -
  4. AUTO_COMMAND=ON, MANUAL_COMMAND=OFF -> MOTOR_MAIN=ON
  5. AUTO_COMMAND=OFF, MANUAL_COMMAND=ON -> MOTOR_MAIN=OFF
- **Condicion de exito:** Todas las expectativas evaluables de test_sequence (incluidas ventanas temporales) deben cumplirse.
- **Invariante critica:** ninguna
- **Runtime:** EXECUTABLE_NOW (BOOL)
- **Convenciones experimentales (para hacerlo medible):**
  - C-D15-MODES: MODE_AUTO selecciona el modo; cada modo tiene su propia orden (mantenida). La orden del modo NO seleccionado se ignora. No se define ninguna secuencia automatica especifica.
- **Review items:** ninguno abierto
- **SYSTEM_CAPABILITY_GAP (HIGH):** INT_MANUAL_AUTO_MODE usa selectores de modo manual/auto y START/STOP comunes: MANUAL_COMMAND/AUTO_COMMAND no se resolveran -> REVIEW.

## D16 - Secuencia: arranque, espera de 3 s y salida auxiliar

- **Estado:** FROZEN v1 · complejidad HIGH · hash `d5c2e360ca5a`
- **Objetivo original:** Secuencia: arranque -> espera -> salida auxiliar.
- **Comando canonico:** Al recibir Start, activa una salida principal y, después de 3 segundos, activa una salida auxiliar.
- **Comportamiento evaluado:** Al recibir Start (pulso) se activa la salida principal y, 3 s despues, la salida auxiliar.
- **Roles:** START (I), MAIN_OUTPUT (O), AUX_OUTPUT (O)
- **Prueba principal:**
  1. START=ON -> MAIN_OUTPUT=ON, AUX_OUTPUT=OFF
  2. START=OFF -> MAIN_OUTPUT=ON, AUX_OUTPUT=ON [transicion AUX_OUTPUT a 3000 ms, -300/+700 ms]
- **Condicion de exito:** Todas las expectativas evaluables de test_sequence (incluidas ventanas temporales) deben cumplirse.
- **Invariante critica:** ninguna
- **Runtime:** EXECUTABLE_NOW (BOOL)
- **Convenciones experimentales (para hacerlo medible):**
  - C-D16-WAIT: Espera nominal de 3 s: CONVENCION experimental del benchmark v1 que el comando canonico v2 ya explicita ('despues de 3 segundos'); se mide con tolerancia -300/+700 ms.
  - C-D16-PULSE: 'Al recibir Start' = pulso de 300 ms; la espera de 3 s se cuenta desde Start.
  - C-TIMING: Temporizaciones: transicion nominal con tolerancia -300 ms / +700 ms medida en el bridge (reloj monotono); las ventanas de evaluacion dejan libre esa banda.
  - C-PULSE: Un 'pulsador' se modela como un pulso de 300 ms (ON y luego OFF).
- **Review items:** ninguno abierto
- **SYSTEM_CAPABILITY_GAP (HIGH):** INT_SEQUENCE_THREE_STEPS no tiene espera ni salida principal: avanza un paso por ciclo de PLC.

## D17 - Supervision de sensor 5 s tras Start

- **Estado:** FROZEN v1 · complejidad HIGH · hash `3c701f0d4bbc`
- **Objetivo original:** Alarma si el sensor no cambia de estado en 5 s.
- **Comando canonico:** Al activar Start, supervisa un sensor; si no cambia de estado durante 5 segundos, activa una alarma.
- **Comportamiento evaluado:** Tras activar Start se supervisa el sensor: si no cambia de estado durante 5 s se activa la alarma; antes de Start no hay supervision.
- **Roles:** START (I), SENSOR (I), ALARM (O)
- **Prueba principal:**
  1. espera -> ALARM=OFF
  2. START=ON -> -
  3. SENSOR=ON -> ALARM=OFF
  4. SENSOR=OFF -> ALARM=OFF
  5. SENSOR=ON -> ALARM=ON [transicion ALARM a 5000 ms, -300/+700 ms]
- **Condicion de exito:** Todas las expectativas evaluables de test_sequence (incluidas ventanas temporales) deben cumplirse.
- **Invariante critica:** ninguna
- **Runtime:** EXECUTABLE_NOW (BOOL)
- **Convenciones experimentales (para hacerlo medible):**
  - C-D17-START: Start se mantiene activo durante la supervision (valido tanto si la supervision arranca con el flanco como con el nivel de Start).
  - C-D17-CHANGES: Cambios cada 2 s (< 5 s) no generan alarma; no se evalua el borrado de la alarma.
  - C-TIMING: Temporizaciones: transicion nominal con tolerancia -300 ms / +700 ms medida en el bridge (reloj monotono); las ventanas de evaluacion dejan libre esa banda.
- **Review items:** ninguno abierto
- **SYSTEM_CAPABILITY_GAP (HIGH):** INT_SENSOR_TIMEOUT_ALARM supervisa desde el arranque del PLC sin Start: t0_idle generaria alarma.

## D18 - Bloqueo del arranque en mantenimiento

- **Estado:** FROZEN v1 · complejidad MEDIUM · hash `b319465d3d22`
- **Objetivo original:** Bloquear arranque en modo mantenimiento.
- **Comando canonico:** Bloquea el arranque del motor mientras el sistema esté en modo mantenimiento.
- **Comportamiento evaluado:** Mientras el modo mantenimiento esta activo, la orden de arranque no pone en marcha el motor; fuera de mantenimiento si.
- **Roles:** MAINTENANCE (I), START (I), MOTOR_MAIN (O)
- **Prueba principal:**
  1. espera -> MOTOR_MAIN=OFF
  2. MAINTENANCE=ON, START=ON -> MOTOR_MAIN=OFF
  3. START=OFF -> MOTOR_MAIN=OFF
  4. MAINTENANCE=OFF -> MOTOR_MAIN=OFF
  5. START=ON -> MOTOR_MAIN=ON
  6. START=OFF -> no especificado: MOTOR_MAIN
- **Condicion de exito:** Todas las expectativas evaluables de test_sequence (incluidas ventanas temporales) deben cumplirse.
- **Invariante critica:** ninguna
- **Runtime:** EXECUTABLE_NOW (BOOL)
- **Convenciones experimentales (para hacerlo medible):**
  - C-D18: No se evalua activar mantenimiento con el motor ya en marcha (el caso solo bloquea el ARRANQUE).
- **Review items:** ninguno abierto

## D19 - Pilotos de estado: detenido, marcha y falla

- **Estado:** FROZEN v1 · complejidad MEDIUM · hash `ef23fb253cf4`
- **Objetivo original:** Pilotos: detenido, marcha, falla.
- **Comando canonico:** Controla tres pilotos para indicar detenido, marcha y falla, manteniendo activo únicamente el correspondiente al estado actual.
- **Comportamiento evaluado:** Exactamente un piloto indica el estado actual: detenido, marcha o falla.
- **Roles:** RUN_STATE (I), FAULT_ACTIVE (I), PILOT_STOPPED (O), PILOT_RUN (O), PILOT_FAULT (O)
- **Prueba principal:**
  1. espera -> PILOT_STOPPED=ON, PILOT_RUN=OFF, PILOT_FAULT=OFF
  2. RUN_STATE=ON -> PILOT_STOPPED=OFF, PILOT_RUN=ON, PILOT_FAULT=OFF
  3. FAULT_ACTIVE=ON -> no especificado: PILOT_STOPPED, PILOT_RUN, PILOT_FAULT
  4. RUN_STATE=OFF -> PILOT_STOPPED=OFF, PILOT_RUN=OFF, PILOT_FAULT=ON
- **Condicion de exito:** Todas las expectativas evaluables de test_sequence (incluidas ventanas temporales) deben cumplirse.
- **Invariante critica:** ninguna
- **Runtime:** EXECUTABLE_NOW (BOOL)
- **Convenciones experimentales (para hacerlo medible):**
  - C-D19-INPUTS: RUN_STATE y FAULT_ACTIVE son condiciones de entrada/logicas simuladas del ensayo; no se exige como se generan.
- **Review items:** ninguno abierto
- **SYSTEM_CAPABILITY_GAP (HIGH):** No hay intent de referencia para D19; INT_STATUS_PILOTS no genera el piloto de detenido y deriva la falla de la emergencia.

## D20 - Ciclo automatico minimo: inicio, ejecucion, fin y reset

- **Estado:** FROZEN v1 · complejidad HIGH · hash `94bc6d4b64cc`
- **Objetivo original:** Ciclo automatico: inicio -> ejecucion -> parada -> reset.
- **Comando canonico:** Al activar Start, inicia un ciclo automático de 3 segundos. Al terminar, detén la ejecución y marca el ciclo como finalizado. Reset debe devolverlo al estado inicial.
- **Comportamiento evaluado:** START inicia la ejecucion (RUN_OUTPUT activa); al terminar la ejecucion el ciclo queda completo; RESET vuelve al reposo.
- **Roles:** START (I), RESET (I), RUN_OUTPUT (O), COMPLETE_STATE (O)
- **Prueba principal:**
  1. START=ON -> RUN_OUTPUT=ON, COMPLETE_STATE=OFF
  2. START=OFF -> RUN_OUTPUT=OFF, COMPLETE_STATE=ON [transicion RUN_OUTPUT a 3000 ms, -300/+700 ms]
  3. RESET=ON -> RUN_OUTPUT=OFF, COMPLETE_STATE=OFF
  4. RESET=OFF -> RUN_OUTPUT=OFF, COMPLETE_STATE=OFF
- **Condicion de exito:** Todas las expectativas evaluables de test_sequence (incluidas ventanas temporales) deben cumplirse.
- **Invariante critica:** ninguna
- **Runtime:** EXECUTABLE_NOW (BOOL)
- **Convenciones experimentales (para hacerlo medible):**
  - C-D20-CYCLE: Ciclo minimo IDLE -> RUNNING (RUN_OUTPUT) -> COMPLETE (COMPLETE_STATE) -> RESET -> IDLE. La 'parada' es el fin automatico de la ejecucion. Sin alarmas (el caso no las solicita).
  - C-D20-DURATION: Duracion de ejecucion de 3 s: CONVENCION experimental (la definicion no fija el tiempo).
  - C-PULSE: Un 'pulsador' se modela como un pulso de 300 ms (ON y luego OFF).
  - C-TIMING: Temporizaciones: transicion nominal con tolerancia -300 ms / +700 ms medida en el bridge (reloj monotono); las ventanas de evaluacion dejan libre esa banda.
- **Review items:** ninguno abierto
- **SYSTEM_CAPABILITY_GAP (HIGH):** INT_AUTO_CYCLE avanza un estado por ciclo de PLC mientras AUTO y START estan activos y no tiene estado COMPLETE.

## P01 - Modo automatico al seleccionar Automatico

- **Estado:** FROZEN v1 · complejidad LOW · hash `b461e15510b4`
- **Objetivo original:** Habilitar modo automatico.
- **Comando canonico:** Habilita el modo automático del sistema de nivel cuando se seleccione Automático.
- **Comportamiento evaluado:** El modo automatico del sistema de nivel se habilita cuando se selecciona Automatico.
- **Roles:** AUTO_SELECT (I), AUTO_MODE (O)
- **Prueba principal:**
  1. espera -> AUTO_MODE=OFF
  2. AUTO_SELECT=ON -> AUTO_MODE=ON
- **Condicion de exito:** Todas las expectativas evaluables de test_sequence (incluidas ventanas temporales) deben cumplirse.
- **Invariante critica:** ninguna
- **Runtime:** REQUIRES_RUNTIME_EXTENSION (BOOL, INTERNAL_TAG_READ)
- **Convenciones experimentales (para hacerlo medible):**
  - C-PID: El PID es estandar y prevalidado: solo se evalua la logica SUPERVISORA. Los limites son los del comando canonico de cada caso. Level_PV se inyecta como valor de proceso simulado (test harness).
  - C-PID-RUNTIME: Requiere extension del Runtime (REAL + lectura/escritura de variables internas). Escribir Level_PV/Auto_Mode exige ademas ampliar explicitamente la politica de seguridad de la Fase 2B (hoy solo se escriben entradas). Hasta entonces el Runner devuelve REVIEW (ORACLE_RUNTIME_EXTENSION_REQUIRED), nunca PASS/FAIL.
- **Review items:** ninguno abierto
- **SYSTEM_CAPABILITY_GAP (MEDIUM):** set_auto_mode activa Auto_Mode incondicionalmente (sin entrada de seleccion): step_0 fallaria.

## P02 - Cambiar el setpoint de nivel a 60 %

- **Estado:** FROZEN v1 · complejidad LOW · hash `31c9eaa5c27e`
- **Objetivo original:** Cambiar setpoint a 60 %.
- **Comando canonico:** Cambia el setpoint del nivel al 60 %.
- **Comportamiento evaluado:** El supervisor fija el setpoint de nivel en 60 %, dentro del rango seguro configurado.
- **Roles:** LEVEL_SP (O, REAL)
- **Prueba principal:**
  1. espera -> LEVEL_SP~60.0
- **Condicion de exito:** Todas las expectativas evaluables de test_sequence (incluidas ventanas temporales) deben cumplirse.
- **Invariante critica:** ninguna
- **Runtime:** REQUIRES_RUNTIME_EXTENSION (REAL, INTERNAL_TAG_READ)
- **Convenciones experimentales (para hacerlo medible):**
  - C-PID: El PID es estandar y prevalidado: solo se evalua la logica SUPERVISORA. Los limites son los del comando canonico de cada caso. Level_PV se inyecta como valor de proceso simulado (test harness).
  - C-PID-RUNTIME: Requiere extension del Runtime (REAL + lectura/escritura de variables internas). Escribir Level_PV/Auto_Mode exige ademas ampliar explicitamente la politica de seguridad de la Fase 2B (hoy solo se escriben entradas). Hasta entonces el Runner devuelve REVIEW (ORACLE_RUNTIME_EXTENSION_REQUIRED), nunca PASS/FAIL.
- **Review items:** ninguno abierto

## P03 - Rechazo de un setpoint fuera del rango seguro

- **Estado:** FROZEN v1 · complejidad LOW · hash `a68ddd4e92dc`
- **Objetivo original:** Rechazar setpoint fuera de rango seguro.
- **Comando canonico:** Acepta setpoints de nivel entre 0 % y 100 %. Si se solicita un valor fuera de ese rango, recházalo y conserva el último valor válido.
- **Comportamiento evaluado:** La logica supervisora acepta setpoints de 0 % a 100 %; una solicitud de 150 % se rechaza y el setpoint conserva el ultimo valor valido (60 %).
- **Roles:** LEVEL_SP_COMMAND (I, REAL), LEVEL_SP (O, REAL)
- **Prueba principal:**
  1. LEVEL_SP_COMMAND=150.0 -> LEVEL_SP~60.0
- **Condicion de exito:** Todas las expectativas evaluables de test_sequence (incluidas ventanas temporales) deben cumplirse.
- **Invariante critica:** INV_SP_RANGE: El setpoint efectivo nunca sale del rango aceptado (0-100 %).
- **Runtime:** REQUIRES_RUNTIME_EXTENSION (REAL, INTERNAL_TAG_READ, INTERNAL_TAG_WRITE)
- **Convenciones experimentales (para hacerlo medible):**
  - C-PID: El PID es estandar y prevalidado: solo se evalua la logica SUPERVISORA. Los limites son los del comando canonico de cada caso. Level_PV se inyecta como valor de proceso simulado (test harness).
  - C-PID-RUNTIME: Requiere extension del Runtime (REAL + lectura/escritura de variables internas). Escribir Level_PV/Auto_Mode exige ademas ampliar explicitamente la politica de seguridad de la Fase 2B (hoy solo se escriben entradas). Hasta entonces el Runner devuelve REVIEW (ORACLE_RUNTIME_EXTENSION_REQUIRED), nunca PASS/FAIL.
  - C-P03: Rango aceptado 0-100 % (comando canonico). Test harness: solicitud inicial de 60 % como ultimo valor valido; luego 150 %, que debe rechazarse.
- **Review items:** ninguno abierto
- **SYSTEM_CAPABILITY_GAP (MEDIUM):** INT_PID_SUPERVISOR escribe Level_SP con la constante del comando: no hay variable de comando ni validacion en PLC.

## P04 - Alarma de nivel alto (> 90 %)

- **Estado:** FROZEN v1 · complejidad LOW · hash `4cb7eea2706b`
- **Objetivo original:** Alarma si nivel > 90 %.
- **Comando canonico:** Activa una alarma de nivel alto cuando el nivel supere el 90 %.
- **Comportamiento evaluado:** Cuando el nivel supera el 90 % se activa la alarma de nivel alto (y la salida de alarma).
- **Roles:** LEVEL_PV (I, REAL), HIGH_LEVEL_ALARM (O)
- **Prueba principal:**
  1. LEVEL_PV=95.0 -> HIGH_LEVEL_ALARM=ON
  2. LEVEL_PV=89.0 -> HIGH_LEVEL_ALARM=OFF
  3. LEVEL_PV=91.0 -> HIGH_LEVEL_ALARM=ON
- **Condicion de exito:** Todas las expectativas evaluables de test_sequence (incluidas ventanas temporales) deben cumplirse.
- **Invariante critica:** ninguna
- **Runtime:** REQUIRES_RUNTIME_EXTENSION (BOOL, REAL, INTERNAL_TAG_READ, INTERNAL_TAG_WRITE)
- **Convenciones experimentales (para hacerlo medible):**
  - C-PID: El PID es estandar y prevalidado: solo se evalua la logica SUPERVISORA. Los limites son los del comando canonico de cada caso. Level_PV se inyecta como valor de proceso simulado (test harness).
  - C-PID-RUNTIME: Requiere extension del Runtime (REAL + lectura/escritura de variables internas). Escribir Level_PV/Auto_Mode exige ademas ampliar explicitamente la politica de seguridad de la Fase 2B (hoy solo se escriben entradas). Hasta entonces el Runner devuelve REVIEW (ORACLE_RUNTIME_EXTENSION_REQUIRED), nunca PASS/FAIL.
  - C-P04: 'Supere el 90 %' es estricto; se prueban 89/91/95 % para no depender del valor frontera.
- **Review items:** ninguno abierto

## P05 - Alarma de nivel bajo (< 10 %)

- **Estado:** FROZEN v1 · complejidad LOW · hash `1e7ef1c0624a`
- **Objetivo original:** Alarma si nivel < 10 %.
- **Comando canonico:** Activa una alarma de nivel bajo cuando el nivel sea inferior al 10 %.
- **Comportamiento evaluado:** Cuando el nivel cae por debajo del 10 % se activa la alarma de nivel bajo (y la salida de alarma).
- **Roles:** LEVEL_PV (I, REAL), LOW_LEVEL_ALARM (O)
- **Prueba principal:**
  1. LEVEL_PV=5.0 -> LOW_LEVEL_ALARM=ON
  2. LEVEL_PV=11.0 -> LOW_LEVEL_ALARM=OFF
  3. LEVEL_PV=9.0 -> LOW_LEVEL_ALARM=ON
- **Condicion de exito:** Todas las expectativas evaluables de test_sequence (incluidas ventanas temporales) deben cumplirse.
- **Invariante critica:** ninguna
- **Runtime:** REQUIRES_RUNTIME_EXTENSION (BOOL, REAL, INTERNAL_TAG_READ, INTERNAL_TAG_WRITE)
- **Convenciones experimentales (para hacerlo medible):**
  - C-PID: El PID es estandar y prevalidado: solo se evalua la logica SUPERVISORA. Los limites son los del comando canonico de cada caso. Level_PV se inyecta como valor de proceso simulado (test harness).
  - C-PID-RUNTIME: Requiere extension del Runtime (REAL + lectura/escritura de variables internas). Escribir Level_PV/Auto_Mode exige ademas ampliar explicitamente la politica de seguridad de la Fase 2B (hoy solo se escriben entradas). Hasta entonces el Runner devuelve REVIEW (ORACLE_RUNTIME_EXTENSION_REQUIRED), nunca PASS/FAIL.
  - C-P05: 'Por debajo del 10 %' es estricto; se prueban 5/9/11 %.
- **Review items:** ninguno abierto

## P06 - PID habilitado solo en automatico

- **Estado:** FROZEN v1 · complejidad MEDIUM · hash `240ffee73cb7`
- **Objetivo original:** PID habilitado solo en automatico.
- **Comando canonico:** Habilita el PID únicamente cuando el sistema esté en modo Automático.
- **Comportamiento evaluado:** PID_Enable solo esta activo con el modo Automatico activo.
- **Roles:** AUTO_MODE (I), PID_ENABLE (O)
- **Prueba principal:**
  1. AUTO_MODE=ON -> PID_ENABLE=ON
  2. AUTO_MODE=OFF -> PID_ENABLE=OFF
- **Condicion de exito:** Todas las expectativas evaluables de test_sequence (incluidas ventanas temporales) deben cumplirse.
- **Invariante critica:** INV_PID_ONLY_AUTO: PID_Enable implica Auto_Mode.
- **Runtime:** REQUIRES_RUNTIME_EXTENSION (BOOL, INTERNAL_TAG_READ, INTERNAL_TAG_WRITE)
- **Convenciones experimentales (para hacerlo medible):**
  - C-PID: El PID es estandar y prevalidado: solo se evalua la logica SUPERVISORA. Los limites son los del comando canonico de cada caso. Level_PV se inyecta como valor de proceso simulado (test harness).
  - C-PID-RUNTIME: Requiere extension del Runtime (REAL + lectura/escritura de variables internas). Escribir Level_PV/Auto_Mode exige ademas ampliar explicitamente la politica de seguridad de la Fase 2B (hoy solo se escriben entradas). Hasta entonces el Runner devuelve REVIEW (ORACLE_RUNTIME_EXTENSION_REQUIRED), nunca PASS/FAIL.
  - C-P06: Auto_Mode lo fija el test harness (orden de operador simulada).
- **Review items:** ninguno abierto

## P07 - PID deshabilitado por disparo de seguridad

- **Estado:** FROZEN v1 · complejidad LOW · hash `fe7c515b70d3`
- **Objetivo original:** Deshabilitar PID ante condicion de emergencia/seguridad autorizada.
- **Comando canonico:** Si se activa una condición de emergencia mientras el PID está funcionando, deshabilítalo inmediatamente.
- **Comportamiento evaluado:** Con el PID habilitado en automatico, un disparo de seguridad deshabilita el PID.
- **Roles:** AUTO_MODE (I), SAFETY_TRIP (I), PID_ENABLE (O)
- **Prueba principal:**
  1. SAFETY_TRIP=ON -> PID_ENABLE=OFF
  2. SAFETY_TRIP=OFF -> no especificado: PID_ENABLE
- **Condicion de exito:** Todas las expectativas evaluables de test_sequence (incluidas ventanas temporales) deben cumplirse.
- **Invariante critica:** INV_TRIP_PID: SAFETY_TRIP => NOT PID_ENABLE.
- **Runtime:** REQUIRES_RUNTIME_EXTENSION (BOOL, INTERNAL_TAG_READ, INTERNAL_TAG_WRITE)
- **Convenciones experimentales (para hacerlo medible):**
  - C-PID: El PID es estandar y prevalidado: solo se evalua la logica SUPERVISORA. Los limites son los del comando canonico de cada caso. Level_PV se inyecta como valor de proceso simulado (test harness).
  - C-PID-RUNTIME: Requiere extension del Runtime (REAL + lectura/escritura de variables internas). Escribir Level_PV/Auto_Mode exige ademas ampliar explicitamente la politica de seguridad de la Fase 2B (hoy solo se escriben entradas). Hasta entonces el Runner devuelve REVIEW (ORACLE_RUNTIME_EXTENSION_REQUIRED), nunca PASS/FAIL.
  - C-P07-TRIP: SAFETY_TRIP es una condicion logica simulada/autorizada (activa = TRUE), no el E-stop fisico.
  - C-P07-PRE: Precondicion: AUTO_MODE=TRUE y sin disparo -> PID habilitado, para que 'deshabilitar' sea observable.
- **Review items:** ninguno abierto
- **SYSTEM_CAPABILITY_GAP (MEDIUM):** Una orden solo de 'deshabilitar ante emergencia' puede no generar enable_pid: la precondicion fallaria (REVIEW).

## P08 - Modo manual: habilitacion ON/OFF de la bomba

- **Estado:** FROZEN v1 · complejidad MEDIUM · hash `b760f3a0f7eb`
- **Objetivo original:** Modo manual con operacion limitada de bomba.
- **Comando canonico:** En modo Manual, permite encender y apagar la bomba mediante una orden manual, sin que el control automático la gobierne.
- **Comportamiento evaluado:** En modo manual, la orden manual habilita y deshabilita la bomba (operacion limitada a ON/OFF).
- **Roles:** AUTO_MODE (I), MANUAL_PUMP_COMMAND (I), PUMP_ENABLE (O)
- **Prueba principal:**
  1. MANUAL_PUMP_COMMAND=ON -> PUMP_ENABLE=ON
  2. MANUAL_PUMP_COMMAND=OFF -> PUMP_ENABLE=OFF
- **Condicion de exito:** Todas las expectativas evaluables de test_sequence (incluidas ventanas temporales) deben cumplirse.
- **Invariante critica:** ninguna
- **Runtime:** REQUIRES_RUNTIME_EXTENSION (BOOL, INTERNAL_TAG_READ, INTERNAL_TAG_WRITE)
- **Convenciones experimentales (para hacerlo medible):**
  - C-PID: El PID es estandar y prevalidado: solo se evalua la logica SUPERVISORA. Los limites son los del comando canonico de cada caso. Level_PV se inyecta como valor de proceso simulado (test harness).
  - C-PID-RUNTIME: Requiere extension del Runtime (REAL + lectura/escritura de variables internas). Escribir Level_PV/Auto_Mode exige ademas ampliar explicitamente la politica de seguridad de la Fase 2B (hoy solo se escriben entradas). Hasta entonces el Runner devuelve REVIEW (ORACLE_RUNTIME_EXTENSION_REQUIRED), nunca PASS/FAIL.
  - C-P08: 'Operacion limitada' = habilitacion manual ON/OFF controlada por MANUAL_PUMP_COMMAND; sin control analogico ni continuo de la bomba.
- **Review items:** ninguno abierto
- **SYSTEM_CAPABILITY_GAP (HIGH):** set_manual_mode solo escribe Manual_Mode/Auto_Mode: no hay orden manual de bomba (MANUAL_PUMP_COMMAND no se resuelve).

## P09 - Fallo de sensor por valor fuera de rango

- **Estado:** FROZEN v1 · complejidad MEDIUM · hash `6a4583cb069d`
- **Objetivo original:** Fallo de sensor por valor fuera de rango.
- **Comando canonico:** Detecta un fallo del sensor si el nivel medido está fuera del rango de 0 % a 100 %.
- **Comportamiento evaluado:** Un nivel medido fuera de 0-100 % se detecta como fallo de sensor.
- **Roles:** LEVEL_PV (I, REAL), SENSOR_FAULT (O)
- **Prueba principal:**
  1. LEVEL_PV=150.0 -> SENSOR_FAULT=ON
  2. LEVEL_PV=50.0 -> SENSOR_FAULT=OFF
  3. LEVEL_PV=-5.0 -> SENSOR_FAULT=ON
- **Condicion de exito:** Todas las expectativas evaluables de test_sequence (incluidas ventanas temporales) deben cumplirse.
- **Invariante critica:** ninguna
- **Runtime:** REQUIRES_RUNTIME_EXTENSION (BOOL, REAL, INTERNAL_TAG_READ, INTERNAL_TAG_WRITE)
- **Convenciones experimentales (para hacerlo medible):**
  - C-PID: El PID es estandar y prevalidado: solo se evalua la logica SUPERVISORA. Los limites son los del comando canonico de cada caso. Level_PV se inyecta como valor de proceso simulado (test harness).
  - C-PID-RUNTIME: Requiere extension del Runtime (REAL + lectura/escritura de variables internas). Escribir Level_PV/Auto_Mode exige ademas ampliar explicitamente la politica de seguridad de la Fase 2B (hoy solo se escriben entradas). Hasta entonces el Runner devuelve REVIEW (ORACLE_RUNTIME_EXTENSION_REQUIRED), nunca PASS/FAIL.
- **Review items:** ninguno abierto

## P10 - Reset de alarma solo cuando desaparece la falla

- **Estado:** FROZEN v1 · complejidad MEDIUM · hash `932a229e3d4e`
- **Objetivo original:** Reset de alarma solo si desaparecio la falla.
- **Comando canonico:** Si existe una alarma por fallo del sensor, no permitas resetearla mientras la falla continúe; permite el Reset cuando la medición vuelva al rango válido.
- **Comportamiento evaluado:** Con una falla de sensor activa el reset no borra la alarma; al desaparecer la falla, el reset la borra.
- **Roles:** LEVEL_PV (I, REAL), SENSOR_FAULT (O), RESET (I), ALARM (O)
- **Prueba principal:**
  1. RESET=ON -> ALARM=ON
  2. RESET=OFF -> ALARM=ON
  3. LEVEL_PV=50.0 -> SENSOR_FAULT=OFF
  4. RESET=ON -> ALARM=OFF
  5. RESET=OFF -> ALARM=OFF
- **Condicion de exito:** Todas las expectativas evaluables de test_sequence (incluidas ventanas temporales) deben cumplirse.
- **Invariante critica:** ninguna
- **Runtime:** REQUIRES_RUNTIME_EXTENSION (BOOL, REAL, INTERNAL_TAG_READ, INTERNAL_TAG_WRITE)
- **Convenciones experimentales (para hacerlo medible):**
  - C-PID: El PID es estandar y prevalidado: solo se evalua la logica SUPERVISORA. Limites tomados de config/pid_supervisor_config.json (setpoint 10-90 %, alarma alta 90 %, baja 10 %, sobrellenado 95 %, rango valido del sensor 0-100 %). Level_PV se inyecta como valor de proceso simulado.
  - C-PID-RUNTIME: Requiere extension del Runtime (REAL + lectura/escritura de variables internas). Escribir Level_PV/Auto_Mode exige ademas ampliar explicitamente la politica de seguridad de la Fase 2B (hoy solo se escriben entradas). Hasta entonces el Runner devuelve REVIEW (ORACLE_RUNTIME_EXTENSION_REQUIRED), nunca PASS/FAIL.
  - C-P10: La falla es la de P09 (sensor fuera de rango): Level_PV = 150 % provoca SENSOR_FAULT y ALARM.
  - C-PULSE: Un 'pulsador' se modela como un pulso de 300 ms (ON y luego OFF).
- **Review items:** ninguno abierto
- **SYSTEM_CAPABILITY_GAP (MEDIUM):** En INT_PID_SUPERVISOR Q_Alarm la activan las alarmas de nivel/sobrellenado, no Sensor_Fault: la precondicion fallaria.

## P11 - Parada segura por sobrellenado

- **Estado:** FROZEN v1 · complejidad MEDIUM · hash `b846d98d2a99`
- **Objetivo original:** Parada segura ante sobrellenado.
- **Comando canonico:** Si el nivel alcanza o supera el 95 %, considera sobrellenado y apaga la bomba mientras esa condición permanezca activa.
- **Comportamiento evaluado:** Con nivel >= 95 % (sobrellenado) la bomba se apaga mientras dure la condicion.
- **Roles:** LEVEL_PV (I, REAL), PUMP_ENABLE (O)
- **Prueba principal:**
  1. LEVEL_PV=96.0 -> PUMP_ENABLE=OFF
  2. LEVEL_PV=50.0 -> no especificado: PUMP_ENABLE
- **Condicion de exito:** Todas las expectativas evaluables de test_sequence (incluidas ventanas temporales) deben cumplirse.
- **Invariante critica:** INV_OVERFILL_PUMP: OVERFILL (Level_PV >= 95 %) => NOT PUMP_ENABLE.
- **Runtime:** REQUIRES_RUNTIME_EXTENSION (BOOL, REAL, INTERNAL_TAG_READ, INTERNAL_TAG_WRITE)
- **Convenciones experimentales (para hacerlo medible):**
  - C-PID: El PID es estandar y prevalidado: solo se evalua la logica SUPERVISORA. Los limites son los del comando canonico de cada caso. Level_PV se inyecta como valor de proceso simulado (test harness).
  - C-PID-RUNTIME: Requiere extension del Runtime (REAL + lectura/escritura de variables internas). Escribir Level_PV/Auto_Mode exige ademas ampliar explicitamente la politica de seguridad de la Fase 2B (hoy solo se escriben entradas). Hasta entonces el Runner devuelve REVIEW (ORACLE_RUNTIME_EXTENSION_REQUIRED), nunca PASS/FAIL.
  - C-P11: Test harness: nivel normal con la bomba habilitada antes del sobrellenado, para que 'apaga la bomba' sea observable. No se exige un indicador de sobrellenado ni se redefine el PID.
- **Review items:** ninguno abierto
- **SYSTEM_CAPABILITY_GAP (MEDIUM):** INT_PID_SUPERVISOR solo fuerza Q_Pump_Enable a FALSE: no la habilita en condicion normal (la precondicion fallaria).

## P12 - Automatico con SP 60 %, alarma > 90 % y recuperacion

- **Estado:** FROZEN v1 · complejidad HIGH · hash `08877566a210`
- **Objetivo original:** Secuencia completa: automatico -> setpoint -> alarma -> recuperacion.
- **Comando canonico:** En modo Automático, habilita el PID con un setpoint del 60 %. Si el nivel supera el 90 %, activa la alarma y lleva el proceso a condición segura. Cuando el nivel vuelva al rango permitido, permite recuperar la operación automática.
- **Comportamiento evaluado:** En Automatico el PID esta habilitado con setpoint 60 %. Con nivel > 90 % se activa la alarma y el proceso pasa a condicion segura (PID deshabilitado y bomba apagada); al volver el nivel al rango permitido se recupera la operacion automatica.
- **Roles:** AUTO_MODE (I), LEVEL_PV (I, REAL), LEVEL_SP (O, REAL), PID_ENABLE (O), ALARM (O), PUMP_ENABLE (O)
- **Prueba principal:**
  1. espera -> PID_ENABLE=ON, LEVEL_SP~60.0
  2. LEVEL_PV=92.0 -> ALARM=ON, PID_ENABLE=OFF, PUMP_ENABLE=OFF
  3. LEVEL_PV=50.0 -> PID_ENABLE=ON
- **Condicion de exito:** Todas las expectativas evaluables de test_sequence (incluidas ventanas temporales) deben cumplirse.
- **Invariante critica:** ninguna
- **Runtime:** REQUIRES_RUNTIME_EXTENSION (BOOL, REAL, INTERNAL_TAG_READ, INTERNAL_TAG_WRITE)
- **Convenciones experimentales (para hacerlo medible):**
  - C-PID: El PID es estandar y prevalidado: solo se evalua la logica SUPERVISORA. Los limites son los del comando canonico de cada caso. Level_PV se inyecta como valor de proceso simulado (test harness).
  - C-PID-RUNTIME: Requiere extension del Runtime (REAL + lectura/escritura de variables internas). Escribir Level_PV/Auto_Mode exige ademas ampliar explicitamente la politica de seguridad de la Fase 2B (hoy solo se escriben entradas). Hasta entonces el Runner devuelve REVIEW (ORACLE_RUNTIME_EXTENSION_REQUIRED), nunca PASS/FAIL.
  - C-P12-SAFE: 'Condicion segura' = PID deshabilitado y bomba apagada (aclaracion del catalogo, misma nocion que P07/P11).
  - C-P12-RECOVERY: 'Rango permitido' = nivel <= 90 %; la recuperacion es automatica (el comando no pide Reset). La alarma tras la recuperacion no se evalua.
- **Review items:** ninguno abierto
- **SYSTEM_CAPABILITY_GAP (HIGH):** INT_PID_SUPERVISOR solo lleva a condicion segura en sobrellenado (>= 95 %) y la recuperacion exige Reset (conditional_alarm_reset).
