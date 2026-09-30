# Catalogo de comandos experimentales (benchmark v2)

Fuente de verdad: `data/experiment_cases/canonical_cases.json`. `profiles.json` y `experiment_variants.json` se generan desde este catalogo; los Oracles se validan contra el.

> **Nota metodologica.** Los comandos canonicos mantienen la formulacion original cuando esta es suficientemente inequivoca y anaden unicamente la informacion necesaria para definir un comportamiento PLC evaluable.

Separacion de responsabilidades: los **requisitos del comando** (lo que el usuario pide y el PLC debe cumplir) estan separados de la **preparacion del test harness** (acciones del runner para empezar la prueba en un estado reproducible, que no son requisito del comando).

| ID | Objetivo original | Comando canonico | Complejidad |
|---|---|---|---|
| D01 | Activar una salida digital durante 5 segundos al presionar un pulsador. | Activa una salida digital durante 5 segundos al presionar un pulsador. | LOW |
| D02 | Encender una lampara cuando una entrada digital este activa. | Enciende una lámpara mientras una entrada digital esté activa. | LOW |
| D03 | Arranque y parada de motor con pulsadores independientes. | Enciende un motor con Start, mantenlo encendido al soltar el pulsador y apágalo con Stop. | LOW |
| D04 | Arranque enclavado de motor con memoria de marcha. | Enclava un motor con Start para que permanezca encendido al soltar el pulsador, y apágalo con Stop. | MEDIUM |
| D05 | Paro de emergencia con prioridad sobre cualquier orden de arranque. | Enciende un motor con Start solo si la condición de seguridad está normal. Si se activa la condición de emergencia, apaga el motor y bloquea el arranque mientras permanezca activa. | MEDIUM |
| D06 | Activar alarma si se intenta arrancar sin condicion de seguridad. | Si se intenta arrancar el sistema sin cumplir la condición de seguridad, activa una alarma. | MEDIUM |
| D07 | Arranque retardado 3 s. | Mientras Start permanezca activo, espera 3 segundos antes de encender el motor. | MEDIUM |
| D08 | Apagar motor despues de 10 segundos de operacion continua. | Al activar Start, enciende el motor y apágalo automáticamente después de 10 segundos de funcionamiento continuo. | MEDIUM |
| D09 | Contar 5 pulsos y activar una salida. | Cuenta 5 pulsos de una entrada digital y, al llegar al quinto, activa una salida. | MEDIUM |
| D10 | Resetear contador mediante pulsador. | Cuenta 5 pulsos y activa una salida; al presionar Reset, reinicia el contador a cero y apaga la salida. | MEDIUM |
| D11 | Control de contactor con enclavamiento electrico/logico. | Controla un contactor con Start y Stop usando enclavamiento de marcha. | HIGH |
| D12 | Interlock: evitar activacion simultanea de dos contactores. | Controla dos contactores con órdenes independientes e impide que ambos estén activos al mismo tiempo. | HIGH |
| D13 | Activar variador solo si no existe alarma. | Ante una orden de marcha, habilita el variador solo si no existe una alarma activa. | MEDIUM |
| D14 | Seleccionar velocidad baja/media/alta mediante entradas digitales. | Selecciona velocidad baja, media o alta mediante tres entradas digitales, activando únicamente la velocidad seleccionada. | HIGH |
| D15 | Modo manual/automatico para habilitacion del motor. | Implementa modo Manual y Automático para el motor: en Manual responde a una orden manual y en Automático a una orden automática. | HIGH |
| D16 | Secuencia: arranque -> espera -> salida auxiliar. | Al recibir Start, activa una salida principal y, después de 3 segundos, activa una salida auxiliar. | HIGH |
| D17 | Alarma si el sensor no cambia de estado en 5 s. | Al activar Start, supervisa un sensor; si no cambia de estado durante 5 segundos, activa una alarma. | HIGH |
| D18 | Bloquear arranque en modo mantenimiento. | Bloquea el arranque del motor mientras el sistema esté en modo mantenimiento. | MEDIUM |
| D19 | Pilotos: detenido, marcha, falla. | Controla tres pilotos para indicar detenido, marcha y falla, manteniendo activo únicamente el correspondiente al estado actual. | MEDIUM |
| D20 | Ciclo automatico: inicio -> ejecucion -> parada -> reset. | Al activar Start, inicia un ciclo automático de 3 segundos. Al terminar, detén la ejecución y marca el ciclo como finalizado. Reset debe devolverlo al estado inicial. | HIGH |
| P01 | Habilitar modo automatico. | Habilita el modo automático del sistema de nivel cuando se seleccione Automático. | LOW |
| P02 | Cambiar setpoint a 60 %. | Cambia el setpoint del nivel al 60 %. | LOW |
| P03 | Rechazar setpoint fuera de rango seguro. | Acepta setpoints de nivel entre 0 % y 100 %. Si se solicita un valor fuera de ese rango, recházalo y conserva el último valor válido. | LOW |
| P04 | Alarma si nivel > 90 %. | Activa una alarma de nivel alto cuando el nivel supere el 90 %. | LOW |
| P05 | Alarma si nivel < 10 %. | Activa una alarma de nivel bajo cuando el nivel sea inferior al 10 %. | LOW |
| P06 | PID habilitado solo en automatico. | Habilita el PID únicamente cuando el sistema esté en modo Automático. | MEDIUM |
| P07 | Deshabilitar PID ante condicion de emergencia/seguridad autorizada. | Si se activa una condición de emergencia mientras el PID está funcionando, deshabilítalo inmediatamente. | LOW |
| P08 | Modo manual con operacion limitada de bomba. | En modo Manual, permite encender y apagar la bomba mediante una orden manual, sin que el control automático la gobierne. | MEDIUM |
| P09 | Fallo de sensor por valor fuera de rango. | Detecta un fallo del sensor si el nivel medido está fuera del rango de 0 % a 100 %. | MEDIUM |
| P10 | Reset de alarma solo si desaparecio la falla. | Si existe una alarma por fallo del sensor, no permitas resetearla mientras la falla continúe; permite el Reset cuando la medición vuelva al rango válido. | MEDIUM |
| P11 | Parada segura ante sobrellenado. | Si el nivel alcanza o supera el 95 %, considera sobrellenado y apaga la bomba mientras esa condición permanezca activa. | MEDIUM |
| P12 | Secuencia completa: automatico -> setpoint -> alarma -> recuperacion. | En modo Automático, habilita el PID con un setpoint del 60 %. Si el nivel supera el 90 %, activa la alarma y lleva el proceso a condición segura. Cuando el nivel vuelva al rango permitido, permite recuperar la operación automática. | HIGH |

## D01 - Salida temporizada de 5 s

**Comando canonico:** Activa una salida digital durante 5 segundos al presionar un pulsador.

- **V1:** Al presionar el pulsador, activa la salida digital durante 5 segundos.
- **V2:** Cuando se presione el pulsador, quiero que la salida se encienda durante cinco segundos.
- **V3:** Genera un pulso de salida de 5 segundos cada vez que se presione el pulsador.

Requisitos del comando:
- R1: La salida se activa al presionar el pulsador.
- R2: La salida permanece activa 5 s y despues se desactiva.

Preparacion del test harness (no es requisito del comando):
- Pulsador en OFF y salida apagada antes de la prueba.

## D02 - Lampara mientras la entrada este activa

**Comando canonico:** Enciende una lámpara mientras una entrada digital esté activa.

- **V1:** Enciende la lámpara mientras la entrada digital esté activa.
- **V2:** Quiero que la lámpara esté encendida solo mientras la entrada esté activa.
- **V3:** Haz que la lámpara se encienda con la entrada digital activa y se apague cuando se desactive.

Requisitos del comando:
- R1: Con la entrada activa la lampara esta encendida.
- R2: Con la entrada inactiva la lampara esta apagada ('mientras').

Preparacion del test harness (no es requisito del comando):
- Entrada en OFF antes de la prueba.

## D03 - Arranque y paro con memoria de marcha

**Comando canonico:** Enciende un motor con Start, mantenlo encendido al soltar el pulsador y apágalo con Stop.

- **V1:** Arranca el motor con Start, mantenlo en marcha al soltar el pulsador y detenlo con Stop.
- **V2:** Quiero encender el motor con Start y que siga encendido aunque suelte el botón; con Stop se apaga.
- **V3:** Con memoria de marcha: Start enciende el motor, que permanece encendido al soltar el pulsador, y Stop lo apaga.

Requisitos del comando:
- R1: Start enciende el motor.
- R2: El motor sigue encendido al soltar el pulsador (memoria de marcha).
- R3: Stop apaga el motor.

Preparacion del test harness (no es requisito del comando):
- Antes de la prueba: Start=OFF, Stop=ON y despues Stop=OFF, para garantizar el motor apagado (no es requisito del comando).

## D04 - Motor enclavado con Start y Stop

**Comando canonico:** Enclava un motor con Start para que permanezca encendido al soltar el pulsador, y apágalo con Stop.

- **V1:** Enclava el motor con Start para que siga encendido al soltar el pulsador y apágalo con Stop.
- **V2:** Haz un enclavamiento: el motor arranca con Start, se queda encendido aunque se suelte el botón y se apaga con Stop.
- **V3:** Con Stop se apaga el motor; con Start se enciende y queda enclavado aunque se suelte el pulsador.

Requisitos del comando:
- R1: Start enciende el motor.
- R2: El motor queda enclavado al soltar el pulsador.
- R3: Stop apaga el motor.

Preparacion del test harness (no es requisito del comando):
- Stop pulsado antes de la prueba para garantizar el motor apagado; al final se deja el motor detenido.

## D05 - Prioridad de la condicion de emergencia sobre el arranque

**Comando canonico:** Enciende un motor con Start solo si la condición de seguridad está normal. Si se activa la condición de emergencia, apaga el motor y bloquea el arranque mientras permanezca activa.

- **V1:** Arranca el motor con Start solo si la condición de seguridad es normal; si se activa la emergencia, apágalo y bloquea el arranque mientras siga activa.
- **V2:** Quiero que el motor arranque con Start únicamente con la seguridad normal, y que una emergencia lo apague y no deje arrancarlo mientras dure.
- **V3:** Mientras la condición de emergencia esté activa, el motor debe estar apagado y Start no puede arrancarlo; con la seguridad normal, Start enciende el motor.

Requisitos del comando:
- R1: Con la seguridad normal, Start enciende el motor.
- R2: La emergencia apaga el motor.
- R3: Mientras la emergencia esta activa, el arranque esta bloqueado.

Preparacion del test harness (no es requisito del comando):
- Antes de la prueba se activa y retira la emergencia para garantizar el motor apagado.

Aclaraciones:
- La emergencia es una condicion LOGICA simulada para el ensayo; no es el E-stop fisico ni exige I_Emergency en el mapa real.

## D06 - Alarma por arranque sin condicion de seguridad

**Comando canonico:** Si se intenta arrancar el sistema sin cumplir la condición de seguridad, activa una alarma.

- **V1:** Activa una alarma si se intenta arrancar sin que se cumpla la condición de seguridad.
- **V2:** Quiero que suene una alarma cuando alguien intente arrancar el sistema sin la condición de seguridad cumplida.
- **V3:** Un intento de arranque sin la condición de seguridad debe activar la alarma.

Requisitos del comando:
- R1: Un intento de arranque sin la condicion de seguridad activa la alarma.
- R2: Con la condicion cumplida, el arranque no activa la alarma (condicional 'si').

Preparacion del test harness (no es requisito del comando):
- Condicion de seguridad presente y sin intento de arranque antes de la prueba.

## D07 - Arranque retardado 3 s con Start mantenido

**Comando canonico:** Mientras Start permanezca activo, espera 3 segundos antes de encender el motor.

- **V1:** Con Start activo, espera 3 segundos y luego enciende el motor.
- **V2:** Quiero que el motor arranque tres segundos después de activar Start, siempre que Start siga activo.
- **V3:** Retarda 3 segundos el encendido del motor mientras se mantenga activo Start.

Requisitos del comando:
- R1: Con Start activo, el motor sigue apagado durante los 3 s.
- R2: Tras 3 s con Start activo, el motor se enciende.

Preparacion del test harness (no es requisito del comando):
- Start en OFF antes de la prueba.

## D08 - Paro automatico tras 10 s de funcionamiento continuo

**Comando canonico:** Al activar Start, enciende el motor y apágalo automáticamente después de 10 segundos de funcionamiento continuo.

- **V1:** Enciende el motor con Start y apágalo automáticamente después de 10 segundos de funcionamiento.
- **V2:** Haz que el motor arranque con Start y se detenga solo tras funcionar durante 10 segundos.
- **V3:** Cuando se active Start, mantén el motor funcionando 10 segundos y después apágalo.

Requisitos del comando:
- R1: Al activar Start el motor se enciende.
- R2: Tras 10 s de funcionamiento continuo el motor se apaga automaticamente.

Preparacion del test harness (no es requisito del comando):
- Start en OFF durante 11 s antes de la prueba (cualquier operacion previa expira).

## D09 - Contador de 5 pulsos

**Comando canonico:** Cuenta 5 pulsos de una entrada digital y, al llegar al quinto, activa una salida.

- **V1:** Cuenta 5 pulsos de la entrada digital y activa una salida al llegar al quinto.
- **V2:** Quiero que se cuenten los pulsos de la entrada y que, cuando lleguen a cinco, se active la salida.
- **V3:** Al recibir el quinto pulso de la entrada digital, activa la salida.

Requisitos del comando:
- R1: Antes del quinto pulso la salida no se activa.
- R2: Al llegar al quinto pulso se activa la salida.

Preparacion del test harness (no es requisito del comando):
- Contador a cero antes de la prueba (con Reset si el programa lo tiene; si no, por el reinicio tras la descarga).

## D10 - Contador de 5 pulsos con Reset

**Comando canonico:** Cuenta 5 pulsos y activa una salida; al presionar Reset, reinicia el contador a cero y apaga la salida.

- **V1:** Cuenta 5 pulsos y activa una salida al llegar a cinco; con Reset, pon el contador a cero y apaga la salida.
- **V2:** Quiero contar cinco pulsos para activar la salida, y que al pulsar Reset el contador vuelva a cero y la salida se apague.
- **V3:** Reset debe reiniciar a cero un contador de 5 pulsos que activa una salida al completarse, apagando esa salida.

Requisitos del comando:
- R1: Con 5 pulsos se activa la salida.
- R2: Reset apaga la salida.
- R3: Reset reinicia el contador a cero (4 pulsos despues no activan la salida).

Preparacion del test harness (no es requisito del comando):
- Reset pulsado antes de la prueba y al final (contador a cero).

## D11 - Contactor con enclavamiento de marcha

**Comando canonico:** Controla un contactor con Start y Stop usando enclavamiento de marcha.

- **V1:** Controla el contactor con Start y Stop con enclavamiento de marcha.
- **V2:** Quiero que el contactor se active con Start, quede enclavado y se desactive con Stop.
- **V3:** Usa un enclavamiento de marcha para que Start conecte el contactor y Stop lo desconecte.

Requisitos del comando:
- R1: Start activa el contactor.
- R2: El contactor queda enclavado al soltar Start.
- R3: Stop desactiva el contactor.

Preparacion del test harness (no es requisito del comando):
- Stop pulsado antes de la prueba para garantizar el contactor desactivado.

## D12 - Dos contactores con ordenes independientes e interbloqueo

**Comando canonico:** Controla dos contactores con órdenes independientes e impide que ambos estén activos al mismo tiempo.

- **V1:** Controla dos contactores con órdenes independientes y evita que ambos estén activos a la vez.
- **V2:** Cada uno de los dos contactores tiene su propia orden, pero nunca pueden estar los dos encendidos al mismo tiempo.
- **V3:** Con dos órdenes independientes maneja dos contactores, impidiendo que se activen simultáneamente.

Requisitos del comando:
- R1: Cada contactor responde a su propia orden.
- R2: Nunca estan los dos activos al mismo tiempo.

Preparacion del test harness (no es requisito del comando):
- Ambas ordenes en OFF antes de la prueba.

## D13 - Variador habilitado solo sin alarma

**Comando canonico:** Ante una orden de marcha, habilita el variador solo si no existe una alarma activa.

- **V1:** Ante una orden de marcha, habilita el variador solo si no hay alarma activa.
- **V2:** Quiero que el variador se habilite con la orden de marcha, pero nunca si existe una alarma activa.
- **V3:** Si hay una alarma activa, el variador no debe habilitarse aunque llegue la orden de marcha; sin alarma, habilítalo con esa orden.

Requisitos del comando:
- R1: Con orden de marcha y sin alarma, el variador se habilita.
- R2: Con alarma activa el variador no se habilita.
- R3: Sin orden de marcha el variador no se habilita ('ante una orden de marcha').

Preparacion del test harness (no es requisito del comando):
- Sin orden ni alarma antes de la prueba.

## D14 - Seleccion de velocidad baja/media/alta

**Comando canonico:** Selecciona velocidad baja, media o alta mediante tres entradas digitales, activando únicamente la velocidad seleccionada.

- **V1:** Selecciona velocidad baja, media o alta con tres entradas digitales y activa solo la velocidad seleccionada.
- **V2:** Quiero elegir entre velocidad baja, media y alta con tres entradas, y que solo quede activa la que elija.
- **V3:** Tres entradas digitales eligen la velocidad baja, media o alta; únicamente debe activarse la seleccionada.

Requisitos del comando:
- R1: Entrada baja: solo velocidad baja.
- R2: Entrada media: solo velocidad media.
- R3: Entrada alta: solo velocidad alta.
- R4: Nunca mas de una velocidad activa ('unicamente').

Preparacion del test harness (no es requisito del comando):
- Las tres entradas en OFF antes de la prueba.

## D15 - Modo Manual/Automatico con orden por modo

**Comando canonico:** Implementa modo Manual y Automático para el motor: en Manual responde a una orden manual y en Automático a una orden automática.

- **V1:** Implementa modo Manual y Automático para el motor: en Manual obedece la orden manual y en Automático la orden automática.
- **V2:** Quiero que en modo Manual el motor responda a la orden manual y en modo Automático a la orden automática.
- **V3:** Según el modo seleccionado, Manual o Automático, el motor debe atender la orden manual o la orden automática respectivamente.

Requisitos del comando:
- R1: En Manual el motor responde a la orden manual.
- R2: En Manual la orden automatica no gobierna el motor.
- R3: En Automatico el motor responde a la orden automatica.
- R4: En Automatico la orden manual no gobierna el motor.

Preparacion del test harness (no es requisito del comando):
- Modo Manual y ordenes en OFF antes de la prueba.

## D16 - Secuencia: principal, espera 3 s, auxiliar

**Comando canonico:** Al recibir Start, activa una salida principal y, después de 3 segundos, activa una salida auxiliar.

- **V1:** Con Start activa la salida principal y, 3 segundos después, la salida auxiliar.
- **V2:** Quiero que al dar Start se encienda la salida principal y que tres segundos más tarde se encienda la auxiliar.
- **V3:** Tras recibir Start, activa la salida principal, espera 3 segundos y luego activa la salida auxiliar.

Requisitos del comando:
- R1: Al recibir Start se activa la salida principal.
- R2: La salida auxiliar se activa 3 s despues (no antes).

Preparacion del test harness (no es requisito del comando):
- Start en OFF antes de la prueba.

## D17 - Supervision de sensor 5 s tras Start

**Comando canonico:** Al activar Start, supervisa un sensor; si no cambia de estado durante 5 segundos, activa una alarma.

- **V1:** Al activar Start, vigila el sensor y activa una alarma si no cambia de estado durante 5 segundos.
- **V2:** Quiero que, después de dar Start, se active una alarma si el sensor pasa cinco segundos sin cambiar de estado.
- **V3:** Tras activar Start, si el sensor permanece sin cambios 5 segundos, activa la alarma.

Requisitos del comando:
- R1: Antes de Start no hay supervision (no hay alarma).
- R2: Con cambios del sensor en menos de 5 s no hay alarma.
- R3: Si el sensor no cambia durante 5 s, se activa la alarma.

Preparacion del test harness (no es requisito del comando):
- Start y sensor en OFF antes de la prueba.

## D18 - Bloqueo del arranque en mantenimiento

**Comando canonico:** Bloquea el arranque del motor mientras el sistema esté en modo mantenimiento.

- **V1:** Bloquea el arranque del motor mientras esté activo el modo mantenimiento.
- **V2:** Quiero que el motor no pueda arrancar mientras el sistema esté en mantenimiento.
- **V3:** En modo mantenimiento, impide que el motor arranque.

Requisitos del comando:
- R1: En mantenimiento el motor no arranca.
- R2: Fuera de mantenimiento el arranque funciona ('bloquea el arranque' presupone una orden de arranque).

Preparacion del test harness (no es requisito del comando):
- Sin mantenimiento ni orden antes de la prueba.

## D19 - Pilotos de estado: detenido, marcha y falla

**Comando canonico:** Controla tres pilotos para indicar detenido, marcha y falla, manteniendo activo únicamente el correspondiente al estado actual.

- **V1:** Controla tres pilotos de detenido, marcha y falla, dejando encendido solo el del estado actual.
- **V2:** Quiero tres pilotos, detenido, marcha y falla, y que solo esté encendido el que corresponde al estado actual.
- **V3:** Indica con tres pilotos si el sistema está detenido, en marcha o en falla; únicamente debe encenderse el del estado actual.

Requisitos del comando:
- R1: Detenido: solo el piloto de detenido.
- R2: En marcha: solo el piloto de marcha.
- R3: En falla: solo el piloto de falla.
- R4: Unicamente un piloto activo.

Preparacion del test harness (no es requisito del comando):
- Sin marcha ni falla antes de la prueba.

Aclaraciones:
- El estado (marcha/falla) llega como condicion de entrada del ensayo.

## D20 - Ciclo automatico de 3 s con Reset

**Comando canonico:** Al activar Start, inicia un ciclo automático de 3 segundos. Al terminar, detén la ejecución y marca el ciclo como finalizado. Reset debe devolverlo al estado inicial.

- **V1:** Con Start inicia un ciclo automático de 3 segundos; al terminar, detén la ejecución y marca el ciclo como finalizado. Reset lo devuelve al estado inicial.
- **V2:** Quiero que Start arranque un ciclo de tres segundos que al acabar se detenga y quede marcado como finalizado, y que Reset lo deje en el estado inicial.
- **V3:** Un ciclo automático de 3 segundos empieza al activar Start; cuando termina se detiene y se marca como finalizado, y Reset lo devuelve al estado inicial.

Requisitos del comando:
- R1: Start inicia la ejecucion.
- R2: A los 3 s la ejecucion se detiene y el ciclo queda marcado como finalizado.
- R3: Reset devuelve al estado inicial.

Preparacion del test harness (no es requisito del comando):
- Reset pulsado antes de la prueba (estado inicial).

## P01 - Modo automatico al seleccionar Automatico

**Comando canonico:** Habilita el modo automático del sistema de nivel cuando se seleccione Automático.

- **V1:** Habilita el modo automático del sistema de nivel al seleccionar Automático.
- **V2:** Quiero que el sistema de nivel pase a modo automático cuando se elija Automático.
- **V3:** Cuando se seleccione Automático, activa el modo automático del control de nivel.

Requisitos del comando:
- R1: Al seleccionar Automatico, el modo automatico queda habilitado.
- R2: Sin seleccionar Automatico, el modo automatico no se habilita (condicional 'cuando').

Preparacion del test harness (no es requisito del comando):
- Seleccion de Automatico en OFF antes de la prueba.

Aclaraciones:
- El PID es un bloque estandar prevalidado: solo se evalua la logica supervisora.

## P02 - Setpoint de nivel al 60 %

**Comando canonico:** Cambia el setpoint del nivel al 60 %.

- **V1:** Cambia el setpoint de nivel a 60 %.
- **V2:** Quiero que el setpoint del nivel quede en el sesenta por ciento.
- **V3:** Ajusta al 60 % la consigna de nivel.

Requisitos del comando:
- R1: El setpoint de nivel queda en 60 %.

Aclaraciones:
- El PID es un bloque estandar prevalidado: solo se evalua la logica supervisora.

## P03 - Setpoint validado en el rango 0-100 %

**Comando canonico:** Acepta setpoints de nivel entre 0 % y 100 %. Si se solicita un valor fuera de ese rango, recházalo y conserva el último valor válido.

- **V1:** Acepta setpoints de nivel de 0 % a 100 % y rechaza cualquier valor fuera de ese rango, conservando el último válido.
- **V2:** Quiero que el setpoint de nivel solo admita valores entre cero y cien por ciento; si piden otro valor, se rechaza y se conserva el anterior válido.
- **V3:** Si se solicita un setpoint de nivel fuera del rango de 0 % a 100 %, recházalo y conserva el último valor válido.

Requisitos del comando:
- R1: Un setpoint dentro de 0-100 % se acepta.
- R2: Un valor fuera de rango se rechaza y se conserva el ultimo valido.

Preparacion del test harness (no es requisito del comando):
- Solicitud inicial de 60 % (valor valido de referencia).

Aclaraciones:
- El PID es un bloque estandar prevalidado: solo se evalua la logica supervisora.

## P04 - Alarma de nivel alto > 90 %

**Comando canonico:** Activa una alarma de nivel alto cuando el nivel supere el 90 %.

- **V1:** Activa la alarma de nivel alto cuando el nivel pase del 90 %.
- **V2:** Quiero una alarma de nivel alto si el nivel supera el noventa por ciento.
- **V3:** Con el nivel por encima del 90 %, activa la alarma de nivel alto.

Requisitos del comando:
- R1: Con el nivel por encima de 90 % se activa la alarma de nivel alto.
- R2: Por debajo de 90 % no hay alarma de nivel alto (condicional 'cuando').

Preparacion del test harness (no es requisito del comando):
- Nivel simulado en 50 % antes de la prueba y al final.

Aclaraciones:
- El PID es un bloque estandar prevalidado: solo se evalua la logica supervisora.

## P05 - Alarma de nivel bajo < 10 %

**Comando canonico:** Activa una alarma de nivel bajo cuando el nivel sea inferior al 10 %.

- **V1:** Activa la alarma de nivel bajo cuando el nivel baje del 10 %.
- **V2:** Quiero una alarma de nivel bajo si el nivel es inferior al diez por ciento.
- **V3:** Con el nivel por debajo del 10 %, activa la alarma de nivel bajo.

Requisitos del comando:
- R1: Con el nivel por debajo de 10 % se activa la alarma de nivel bajo.
- R2: Por encima de 10 % no hay alarma de nivel bajo (condicional 'cuando').

Preparacion del test harness (no es requisito del comando):
- Nivel simulado en 50 % antes de la prueba y al final.

Aclaraciones:
- El PID es un bloque estandar prevalidado: solo se evalua la logica supervisora.

## P06 - PID habilitado solo en Automatico

**Comando canonico:** Habilita el PID únicamente cuando el sistema esté en modo Automático.

- **V1:** Habilita el PID solo cuando el sistema esté en modo Automático.
- **V2:** Quiero que el PID funcione únicamente en modo Automático.
- **V3:** El PID debe estar habilitado solamente mientras el sistema esté en Automático.

Requisitos del comando:
- R1: En modo Automatico el PID esta habilitado.
- R2: Fuera de Automatico el PID no esta habilitado ('unicamente').

Preparacion del test harness (no es requisito del comando):
- Modo Automatico en OFF antes de la prueba.

Aclaraciones:
- El PID es un bloque estandar prevalidado: solo se evalua la logica supervisora.

## P07 - PID deshabilitado ante emergencia

**Comando canonico:** Si se activa una condición de emergencia mientras el PID está funcionando, deshabilítalo inmediatamente.

- **V1:** Si se activa una condición de emergencia con el PID funcionando, deshabilítalo de inmediato.
- **V2:** Quiero que, si hay una emergencia mientras el PID trabaja, el PID se deshabilite en el acto.
- **V3:** Ante una condición de emergencia durante el funcionamiento del PID, deshabilítalo inmediatamente.

Requisitos del comando:
- R1: La emergencia deshabilita el PID en funcionamiento.

Preparacion del test harness (no es requisito del comando):
- Automatico activo y sin emergencia para que el PID este funcionando antes de la prueba (estado previo que presupone el comando).

Aclaraciones:
- El PID es un bloque estandar prevalidado: solo se evalua la logica supervisora.

## P08 - Bomba manual ON/OFF en modo Manual

**Comando canonico:** En modo Manual, permite encender y apagar la bomba mediante una orden manual, sin que el control automático la gobierne.

- **V1:** En modo Manual, enciende y apaga la bomba con una orden manual, sin que el control automático intervenga.
- **V2:** Quiero que en Manual la bomba se encienda y se apague solo con la orden manual, no con el control automático.
- **V3:** Con el sistema en Manual, la orden manual decide si la bomba está encendida o apagada; el control automático no la gobierna.

Requisitos del comando:
- R1: En Manual, la orden manual enciende la bomba.
- R2: En Manual, la orden manual apaga la bomba (el control automatico no la mantiene encendida).

Preparacion del test harness (no es requisito del comando):
- Modo Manual y orden en OFF antes de la prueba.

Aclaraciones:
- El PID es un bloque estandar prevalidado: solo se evalua la logica supervisora.

## P09 - Fallo de sensor fuera de 0-100 %

**Comando canonico:** Detecta un fallo del sensor si el nivel medido está fuera del rango de 0 % a 100 %.

- **V1:** Detecta fallo de sensor cuando el nivel medido esté fuera del rango de 0 % a 100 %.
- **V2:** Quiero que se marque un fallo del sensor si el nivel medido sale del rango de cero a cien por ciento.
- **V3:** Si el nivel medido no está entre 0 % y 100 %, indica un fallo del sensor.

Requisitos del comando:
- R1: Nivel por encima de 100 %: fallo de sensor.
- R2: Nivel por debajo de 0 %: fallo de sensor.
- R3: Nivel dentro del rango: sin fallo (condicional 'si').

Preparacion del test harness (no es requisito del comando):
- Nivel simulado en 50 % antes de la prueba y al final.

Aclaraciones:
- El PID es un bloque estandar prevalidado: solo se evalua la logica supervisora.

## P10 - Reset de alarma de sensor solo sin falla

**Comando canonico:** Si existe una alarma por fallo del sensor, no permitas resetearla mientras la falla continúe; permite el Reset cuando la medición vuelva al rango válido.

- **V1:** Si hay una alarma por fallo del sensor, no permitas su Reset mientras la falla siga; permítelo cuando la medición vuelva al rango válido.
- **V2:** Quiero que la alarma por fallo del sensor no se pueda resetear mientras dure la falla, y que sí se pueda cuando la medición vuelva a ser válida.
- **V3:** El Reset de la alarma por fallo del sensor solo debe funcionar cuando la medición haya vuelto al rango válido, no mientras continúe la falla.

Requisitos del comando:
- R1: Con la falla presente, Reset no borra la alarma.
- R2: Con la medicion en rango, Reset borra la alarma.

Preparacion del test harness (no es requisito del comando):
- Nivel simulado fuera de rango (150 %) para provocar la falla y la alarma que el comando presupone.

Aclaraciones:
- El PID es un bloque estandar prevalidado: solo se evalua la logica supervisora.

## P11 - Bomba apagada por sobrellenado >= 95 %

**Comando canonico:** Si el nivel alcanza o supera el 95 %, considera sobrellenado y apaga la bomba mientras esa condición permanezca activa.

- **V1:** Si el nivel llega o supera el 95 %, trátalo como sobrellenado y apaga la bomba mientras dure esa condición.
- **V2:** Quiero que la bomba se apague mientras el nivel esté en el noventa y cinco por ciento o más, porque es sobrellenado.
- **V3:** Considera sobrellenado un nivel igual o superior al 95 % y mantén la bomba apagada mientras siga así.

Requisitos del comando:
- R1: Con nivel >= 95 % la bomba esta apagada mientras dure la condicion.

Preparacion del test harness (no es requisito del comando):
- Nivel simulado normal (50 %) con la bomba habilitada antes de la prueba (estado previo que presupone 'apaga la bomba').

Aclaraciones:
- El PID es un bloque estandar prevalidado: solo se evalua la logica supervisora.

## P12 - Automatico con SP 60 %, alarma > 90 % y recuperacion

**Comando canonico:** En modo Automático, habilita el PID con un setpoint del 60 %. Si el nivel supera el 90 %, activa la alarma y lleva el proceso a condición segura. Cuando el nivel vuelva al rango permitido, permite recuperar la operación automática.

- **V1:** En modo Automático, habilita el PID con setpoint del 60 %; si el nivel supera el 90 %, activa la alarma y lleva el proceso a condición segura, y cuando vuelva al rango permitido deja recuperar la operación automática.
- **V2:** Quiero que en Automático el PID trabaje con un setpoint del sesenta por ciento, que por encima del noventa por ciento suene la alarma y el proceso pase a condición segura, y que al volver el nivel al rango permitido se pueda recuperar el automático.
- **V3:** Con el sistema en Automático y setpoint del 60 %, habilita el PID; un nivel mayor del 90 % activa la alarma y la condición segura, y el regreso del nivel al rango permitido permite recuperar la operación automática.

Requisitos del comando:
- R1: En Automatico, PID habilitado con setpoint 60 %.
- R2: Nivel > 90 %: alarma y condicion segura (PID deshabilitado y bomba apagada).
- R3: Con el nivel de nuevo en rango, se recupera la operacion automatica (PID habilitado).

Preparacion del test harness (no es requisito del comando):
- Modo Automatico y nivel simulado 50 % antes de la prueba.

Aclaraciones:
- El PID es un bloque estandar prevalidado: solo se evalua la logica supervisora.
- Aclaracion del benchmark: 'condicion segura' = PID deshabilitado y bomba apagada (misma nocion que P07/P11).
- Aclaracion del benchmark: 'rango permitido' = nivel <= 90 %; la recuperacion es automatica (el comando no pide Reset).
