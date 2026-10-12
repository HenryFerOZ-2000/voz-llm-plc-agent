# Catalogo de comandos experimentales (benchmark v3)

Fuente de verdad: `data/experiment_cases/canonical_cases.json`. `profiles.json` y `experiment_variants.json` se generan desde este catalogo; los Oracles se validan contra el.

> **Nota metodologica.** Los comandos canonicos mantienen la formulacion original cuando esta es suficientemente inequivoca y anaden unicamente la informacion necesaria para definir un comportamiento PLC evaluable. Benchmark v3 (FORMAL): refinado ANTES de los ensayos formales para hacer explicito, sin cambiar el comportamiento evaluado, lo que los Oracles congelados ya exigian (criterio: alineacion especificacion-ground truth). El v2 queda archivado como historico DEVELOPMENT en data/experiment_benchmark/versions/benchmark_v2/.

Separacion de responsabilidades: los **requisitos del comando** (lo que el usuario pide y el PLC debe cumplir) estan separados de la **preparacion del test harness** (acciones del runner para empezar la prueba en un estado reproducible, que no son requisito del comando).

| ID | Objetivo original | Comando canonico | Complejidad |
|---|---|---|---|
| D01 | Activar una salida digital durante 5 segundos al presionar un pulsador. | Activa una salida digital durante 5 segundos al presionar un pulsador. | LOW |
| D02 | Encender una lampara cuando una entrada digital este activa. | Enciende una lámpara mientras una entrada digital esté activa. | LOW |
| D03 | Arranque y parada de motor con pulsadores independientes. | Enciende un motor con Start, mantenlo encendido al soltar el pulsador y apágalo con Stop. | LOW |
| D04 | Arranque enclavado de motor con memoria de marcha. | Enclava un motor con Start para que permanezca encendido al soltar el pulsador, y apágalo con Stop. | MEDIUM |
| D05 | Paro de emergencia con prioridad sobre cualquier orden de arranque. | Enciende un motor con Start solo si no hay una condición de emergencia activa. Si se activa la emergencia, apaga el motor y bloquea el arranque mientras permanezca activa. | MEDIUM |
| D06 | Activar alarma si se intenta arrancar sin condicion de seguridad. | Si se intenta arrancar el sistema sin cumplir la condición de seguridad, activa una alarma. | MEDIUM |
| D07 | Arranque retardado 3 s. | Mientras Start permanezca activo, espera 3 segundos antes de encender el motor. | MEDIUM |
| D08 | Apagar motor despues de 10 segundos de operacion continua. | Al activar Start, enciende el motor, mantenlo en marcha aunque se suelte Start y apágalo automáticamente después de 10 segundos de funcionamiento continuo. | MEDIUM |
| D09 | Contar 5 pulsos y activar una salida. | Cuenta 5 pulsos de una entrada digital y, al llegar al quinto, activa una salida. | MEDIUM |
| D10 | Resetear contador mediante pulsador. | Cuenta 5 pulsos y activa una salida; al presionar Reset, reinicia el contador a cero y apaga la salida. | MEDIUM |
| D11 | Control de contactor con enclavamiento electrico/logico. | Controla un contactor con Start y Stop usando enclavamiento de marcha. | HIGH |
| D12 | Interlock: evitar activacion simultanea de dos contactores. | Controla dos contactores con órdenes independientes e impide que ambos estén activos al mismo tiempo. | HIGH |
| D13 | Activar variador solo si no existe alarma. | Con una orden de marcha, habilita el variador solo mientras no exista una alarma activa; si la alarma aparece con el variador habilitado, deshabilítalo. | MEDIUM |
| D14 | Seleccionar velocidad baja/media/alta mediante entradas digitales. | Selecciona velocidad baja, media o alta mediante tres entradas digitales, activando únicamente la velocidad seleccionada. | HIGH |
| D15 | Modo manual/automatico para habilitacion del motor. | El operador elige el modo del motor con un selector Manual/Automático: en Automático el motor sigue la orden automática y en Manual sigue la orden manual; la orden del otro modo no tiene efecto. | HIGH |
| D16 | Secuencia: arranque -> espera -> salida auxiliar. | Al recibir Start, activa una salida principal y, después de 3 segundos, activa una salida auxiliar. | HIGH |
| D17 | Alarma si el sensor no cambia de estado en 5 s. | Al activar Start, supervisa un sensor: si pasan 5 segundos sin que cambie de estado, activa una alarma; cada cambio del sensor vuelve a contar los 5 segundos. | HIGH |
| D18 | Bloquear arranque en modo mantenimiento. | Bloquea el arranque del motor mientras el sistema esté en modo mantenimiento. | MEDIUM |
| D19 | Pilotos: detenido, marcha, falla. | Controla tres pilotos según las señales de marcha y de falla del sistema: detenido, marcha y falla, manteniendo activo únicamente el del estado actual. | MEDIUM |
| D20 | Ciclo automatico: inicio -> ejecucion -> parada -> reset. | Al activar Start, inicia un ciclo automático de 3 segundos. Al terminar, detén la ejecución y marca el ciclo como finalizado. Reset debe devolverlo al estado inicial. | HIGH |
| P01 | Habilitar modo automatico. | El sistema de nivel debe pasar a modo automático solo cuando el operador seleccione Automático. | LOW |
| P02 | Cambiar setpoint a 60 %. | Cambia el setpoint del nivel al 60 %. | LOW |
| P03 | Rechazar setpoint fuera de rango seguro. | Acepta setpoints de nivel entre 0 % y 100 %. Si se solicita un valor fuera de ese rango, recházalo y conserva el último valor válido. | LOW |
| P04 | Alarma si nivel > 90 %. | Activa la alarma de nivel alto mientras el nivel esté por encima del 90 % y desactívala cuando vuelva a 90 % o menos. | LOW |
| P05 | Alarma si nivel < 10 %. | Activa la alarma de nivel bajo mientras el nivel esté por debajo del 10 % y desactívala cuando vuelva a 10 % o más. | LOW |
| P06 | PID habilitado solo en automatico. | El PID solo debe estar habilitado mientras el sistema se encuentre en modo Automático, que selecciona el operador; en modo Manual debe permanecer deshabilitado. | MEDIUM |
| P07 | Deshabilitar PID ante condicion de emergencia/seguridad autorizada. | Con el sistema en Automático el PID trabaja habilitado; si se activa una condición de emergencia, deshabilita el PID de inmediato. | LOW |
| P08 | Modo manual con operacion limitada de bomba. | Cuando el sistema esté en modo Manual, es decir, siempre que no esté en Automático, la bomba debe encenderse y apagarse solo con la orden manual del operador; el control automático no debe actuar sobre ella. | MEDIUM |
| P09 | Fallo de sensor por valor fuera de rango. | Indica fallo del sensor mientras el nivel medido esté por debajo de 0 % o por encima de 100 %; cuando vuelva a estar entre 0 % y 100 %, el fallo debe desaparecer. | MEDIUM |
| P10 | Reset de alarma solo si desaparecio la falla. | Activa una alarma cuando el nivel medido salga del rango de 0 % a 100 % por fallo del sensor. Mientras la medición siga fuera de ese rango, el Reset no debe borrar la alarma; cuando vuelva al rango, el Reset sí debe borrarla. | MEDIUM |
| P11 | Parada segura ante sobrellenado. | En operación normal la bomba está en marcha; si el nivel alcanza o supera el 95 %, considéralo sobrellenado y mantén la bomba apagada mientras dure esa condición. | MEDIUM |
| P12 | Secuencia completa: automatico -> setpoint -> alarma -> recuperacion. | En modo Automático, habilita el PID con un setpoint del 60 %. Si el nivel supera el 90 %, activa la alarma y lleva el proceso a condición segura: PID deshabilitado y bomba apagada. Cuando el nivel vuelva a 90 % o menos, el PID debe volver a habilitarse por sí solo, sin intervención del operador. | HIGH |

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

**Comando canonico:** Enciende un motor con Start solo si no hay una condición de emergencia activa. Si se activa la emergencia, apaga el motor y bloquea el arranque mientras permanezca activa.

- **V1:** Arranca el motor con Start únicamente si no hay emergencia activa; si se activa, apágalo y bloquea el arranque mientras siga activa.
- **V2:** Quiero que el motor arranque con Start solo sin emergencia, y que una emergencia lo apague y no deje arrancarlo mientras dure.
- **V3:** Mientras la condición de emergencia esté activa, el motor debe estar apagado y Start no puede arrancarlo; sin emergencia, Start enciende el motor.

Requisitos del comando:
- R1: Sin emergencia activa, Start enciende el motor.
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

**Comando canonico:** Al activar Start, enciende el motor, mantenlo en marcha aunque se suelte Start y apágalo automáticamente después de 10 segundos de funcionamiento continuo.

- **V1:** Enciende el motor con Start, que siga en marcha aunque se suelte el pulsador, y apágalo automáticamente tras 10 segundos de funcionamiento.
- **V2:** Haz que el motor arranque con Start, siga funcionando aunque se suelte y se detenga solo tras 10 segundos.
- **V3:** Cuando se active Start, mantén el motor funcionando 10 segundos, aunque se suelte el pulsador, y después apágalo.

Requisitos del comando:
- R1: Al activar Start el motor se enciende.
- R2: El motor sigue en marcha tras soltar Start y, a los 10 s de funcionamiento continuo, se apaga automaticamente.

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

**Comando canonico:** Con una orden de marcha, habilita el variador solo mientras no exista una alarma activa; si la alarma aparece con el variador habilitado, deshabilítalo.

- **V1:** Habilita el variador con la orden de marcha únicamente mientras no haya alarma activa; si aparece una alarma, deshabilítalo.
- **V2:** Quiero que el variador se habilite con la orden de marcha, pero nunca mientras exista una alarma activa, ni siquiera si ya estaba funcionando.
- **V3:** Mientras haya una alarma activa el variador debe estar deshabilitado, aunque tenga orden de marcha; sin alarma, habilítalo con esa orden.

Requisitos del comando:
- R1: Con orden de marcha y sin alarma, el variador se habilita.
- R2: Si aparece una alarma con el variador habilitado, el variador se deshabilita; con alarma activa nunca esta habilitado.
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

**Comando canonico:** El operador elige el modo del motor con un selector Manual/Automático: en Automático el motor sigue la orden automática y en Manual sigue la orden manual; la orden del otro modo no tiene efecto.

- **V1:** Con un selector Manual/Automático: en Automático, el motor obedece la orden automática; en Manual, la orden manual; la otra orden se ignora.
- **V2:** Quiero un selector Manual/Automático: en Automático el motor responde a la orden automática y en Manual a la orden manual, sin que la otra orden haga nada.
- **V3:** Según la posición del selector, Manual o Automático, el motor atiende la orden manual o la orden automática respectivamente, e ignora la del otro modo.

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

**Comando canonico:** Al activar Start, supervisa un sensor: si pasan 5 segundos sin que cambie de estado, activa una alarma; cada cambio del sensor vuelve a contar los 5 segundos.

- **V1:** Tras activar Start, vigila el sensor y activa una alarma si transcurren 5 segundos sin ningún cambio; cada cambio reinicia la cuenta.
- **V2:** Quiero que, después de dar Start, salte una alarma si el sensor pasa cinco segundos seguidos sin cambiar de estado.
- **V3:** Con Start activado, si el sensor permanece sin cambios durante 5 segundos seguidos, activa la alarma.

Requisitos del comando:
- R1: Antes de Start no hay supervision (no hay alarma).
- R2: Con cambios del sensor en menos de 5 s no hay alarma.
- R3: Si el sensor no cambia durante 5 s contados desde su ultimo cambio, se activa la alarma.

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

**Comando canonico:** Controla tres pilotos según las señales de marcha y de falla del sistema: detenido, marcha y falla, manteniendo activo únicamente el del estado actual.

- **V1:** Con las señales de marcha y falla del sistema, controla tres pilotos (detenido, marcha y falla) y deja encendido solo el del estado actual.
- **V2:** Quiero tres pilotos, detenido, marcha y falla, que según las señales de marcha y falla del sistema dejen encendido solo el que corresponde al estado actual.
- **V3:** A partir de las señales de marcha y de falla, indica con tres pilotos si el sistema está detenido, en marcha o en falla; únicamente debe encenderse el del estado actual.

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

**Comando canonico:** El sistema de nivel debe pasar a modo automático solo cuando el operador seleccione Automático.

- **V1:** Pasa el sistema de nivel a modo automático únicamente cuando el operador seleccione Automático.
- **V2:** Quiero que el control de nivel entre en automático solo si el operador elige Automático.
- **V3:** Solo al seleccionar el operador Automático debe el sistema de nivel ponerse en modo automático.

Requisitos del comando:
- R1: Al seleccionar Automatico, el sistema de nivel pasa a modo automatico.
- R2: Sin seleccionar Automatico, el sistema no pasa a modo automatico ('solo cuando').

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

**Comando canonico:** Activa la alarma de nivel alto mientras el nivel esté por encima del 90 % y desactívala cuando vuelva a 90 % o menos.

- **V1:** Mantén activa la alarma de nivel alto mientras el nivel supere el 90 % y apágala cuando baje a 90 % o menos.
- **V2:** Quiero que la alarma de nivel alto suene mientras el nivel pase del noventa por ciento y se quite al volver a noventa o menos.
- **V3:** Con el nivel por encima del 90 %, la alarma de nivel alto debe estar activa; a 90 % o menos, desactivada.

Requisitos del comando:
- R1: Con el nivel por encima de 90 % se activa la alarma de nivel alto.
- R2: Con el nivel en 90 % o menos no hay alarma de nivel alto (se desactiva al volver).

Preparacion del test harness (no es requisito del comando):
- Nivel simulado en 50 % antes de la prueba y al final.

Aclaraciones:
- El PID es un bloque estandar prevalidado: solo se evalua la logica supervisora.

## P05 - Alarma de nivel bajo < 10 %

**Comando canonico:** Activa la alarma de nivel bajo mientras el nivel esté por debajo del 10 % y desactívala cuando vuelva a 10 % o más.

- **V1:** Mantén activa la alarma de nivel bajo mientras el nivel esté por debajo del 10 % y apágala cuando suba a 10 % o más.
- **V2:** Quiero que la alarma de nivel bajo suene mientras el nivel sea inferior al diez por ciento y se quite al volver a diez o más.
- **V3:** Con el nivel por debajo del 10 %, la alarma de nivel bajo debe estar activa; a 10 % o más, desactivada.

Requisitos del comando:
- R1: Con el nivel por debajo de 10 % se activa la alarma de nivel bajo.
- R2: Con el nivel en 10 % o mas no hay alarma de nivel bajo (se desactiva al volver).

Preparacion del test harness (no es requisito del comando):
- Nivel simulado en 50 % antes de la prueba y al final.

Aclaraciones:
- El PID es un bloque estandar prevalidado: solo se evalua la logica supervisora.

## P06 - PID habilitado solo en Automatico

**Comando canonico:** El PID solo debe estar habilitado mientras el sistema se encuentre en modo Automático, que selecciona el operador; en modo Manual debe permanecer deshabilitado.

- **V1:** Mantén el PID habilitado únicamente mientras el operador tenga el sistema en Automático; en Manual, deshabilitado.
- **V2:** Quiero que el PID solo funcione cuando el operador haya puesto el sistema en Automático, y que en Manual quede deshabilitado.
- **V3:** Solo con el sistema en el modo Automático elegido por el operador puede estar habilitado el PID; en Manual debe estar deshabilitado.

Requisitos del comando:
- R1: En modo Automatico el PID esta habilitado.
- R2: En Manual (fuera de Automatico) el PID esta deshabilitado.

Preparacion del test harness (no es requisito del comando):
- Modo Automatico en OFF antes de la prueba.

Aclaraciones:
- El PID es un bloque estandar prevalidado: solo se evalua la logica supervisora.

## P07 - PID deshabilitado ante emergencia

**Comando canonico:** Con el sistema en Automático el PID trabaja habilitado; si se activa una condición de emergencia, deshabilita el PID de inmediato.

- **V1:** En Automático el PID funciona habilitado, pero si se activa una emergencia, deshabilítalo inmediatamente.
- **V2:** Quiero que el PID esté habilitado en Automático y que, si hay una emergencia, se deshabilite en el acto.
- **V3:** Ante una condición de emergencia, el PID, que en Automático está habilitado, debe deshabilitarse de inmediato.

Requisitos del comando:
- R0: En Automatico, sin emergencia, el PID esta habilitado.
- R1: La emergencia deshabilita el PID en funcionamiento.

Preparacion del test harness (no es requisito del comando):
- Automatico activo y sin emergencia para que el PID este funcionando antes de la prueba (estado previo que presupone el comando).

Aclaraciones:
- El PID es un bloque estandar prevalidado: solo se evalua la logica supervisora.

## P08 - Bomba manual ON/OFF en modo Manual

**Comando canonico:** Cuando el sistema esté en modo Manual, es decir, siempre que no esté en Automático, la bomba debe encenderse y apagarse solo con la orden manual del operador; el control automático no debe actuar sobre ella.

- **V1:** Siempre que el sistema no esté en Automático, o sea en Manual, la orden manual del operador enciende y apaga la bomba, sin que actúe el control automático.
- **V2:** Quiero que, mientras el sistema no esté en Automático, la bomba solo se encienda y apague con la orden manual del operador.
- **V3:** Fuera del modo Automático, en Manual, la bomba debe seguir únicamente la orden manual del operador para encenderse o apagarse.

Requisitos del comando:
- R1: En Manual, la orden manual enciende la bomba.
- R2: En Manual, la orden manual apaga la bomba (el control automatico no la mantiene encendida).

Preparacion del test harness (no es requisito del comando):
- Modo Manual y orden en OFF antes de la prueba.

Aclaraciones:
- El PID es un bloque estandar prevalidado: solo se evalua la logica supervisora.

## P09 - Fallo de sensor fuera de 0-100 %

**Comando canonico:** Indica fallo del sensor mientras el nivel medido esté por debajo de 0 % o por encima de 100 %; cuando vuelva a estar entre 0 % y 100 %, el fallo debe desaparecer.

- **V1:** Señala fallo de sensor mientras el nivel medido esté fuera de 0 % a 100 % y quítalo cuando vuelva a ese rango.
- **V2:** Quiero que se marque fallo del sensor mientras el nivel medido salga del rango de cero a cien por ciento, y que se quite al volver a él.
- **V3:** Con el nivel medido por debajo de 0 % o por encima de 100 % debe haber fallo de sensor; dentro de ese rango, no.

Requisitos del comando:
- R1: Nivel por encima de 100 %: fallo de sensor.
- R2: Nivel por debajo de 0 %: fallo de sensor.
- R3: Con el nivel de nuevo dentro de 0-100 % no hay fallo de sensor (desaparece al volver).

Preparacion del test harness (no es requisito del comando):
- Nivel simulado en 50 % antes de la prueba y al final.

Aclaraciones:
- El PID es un bloque estandar prevalidado: solo se evalua la logica supervisora.

## P10 - Reset de alarma de sensor solo sin falla

**Comando canonico:** Activa una alarma cuando el nivel medido salga del rango de 0 % a 100 % por fallo del sensor. Mientras la medición siga fuera de ese rango, el Reset no debe borrar la alarma; cuando vuelva al rango, el Reset sí debe borrarla.

- **V1:** Genera una alarma si el nivel medido sale de 0 % a 100 % por fallo del sensor; el Reset no la borra mientras siga fuera y sí cuando vuelva al rango.
- **V2:** Quiero una alarma por fallo del sensor cuando la medición salga de cero a cien por ciento, que no se pueda resetear mientras dure y sí al volver al rango.
- **V3:** Un nivel medido fuera de 0 % a 100 % debe activar la alarma de fallo del sensor; el Reset solo la borra cuando la medición vuelve a ese rango.

Requisitos del comando:
- R0: Un nivel medido fuera de 0-100 % activa la alarma por fallo del sensor.
- R1: Con la falla presente, Reset no borra la alarma.
- R2: Con la medicion en rango, Reset borra la alarma.

Preparacion del test harness (no es requisito del comando):
- Nivel simulado fuera de rango (150 %) para provocar la falla y la alarma que el comando presupone.

Aclaraciones:
- El PID es un bloque estandar prevalidado: solo se evalua la logica supervisora.

## P11 - Bomba apagada por sobrellenado >= 95 %

**Comando canonico:** En operación normal la bomba está en marcha; si el nivel alcanza o supera el 95 %, considéralo sobrellenado y mantén la bomba apagada mientras dure esa condición.

- **V1:** Con el nivel normal la bomba funciona; si el nivel llega o supera el 95 %, trátalo como sobrellenado y apaga la bomba mientras dure.
- **V2:** Quiero que la bomba trabaje normalmente y que se apague mientras el nivel esté en el noventa y cinco por ciento o más, por sobrellenado.
- **V3:** La bomba, en marcha en condiciones normales, debe quedar apagada mientras el nivel sea igual o superior al 95 % (sobrellenado).

Requisitos del comando:
- R0: En operacion normal (nivel por debajo de 95 %) la bomba esta en marcha.
- R1: Con nivel >= 95 % la bomba esta apagada mientras dure la condicion.

Preparacion del test harness (no es requisito del comando):
- Nivel simulado normal (50 %) con la bomba habilitada antes de la prueba (estado previo que presupone 'apaga la bomba').

Aclaraciones:
- El PID es un bloque estandar prevalidado: solo se evalua la logica supervisora.

## P12 - Automatico con SP 60 %, alarma > 90 % y recuperacion

**Comando canonico:** En modo Automático, habilita el PID con un setpoint del 60 %. Si el nivel supera el 90 %, activa la alarma y lleva el proceso a condición segura: PID deshabilitado y bomba apagada. Cuando el nivel vuelva a 90 % o menos, el PID debe volver a habilitarse por sí solo, sin intervención del operador.

- **V1:** En Automático, PID habilitado con setpoint del 60 %; por encima del 90 %, alarma y condición segura (PID deshabilitado y bomba apagada); al volver a 90 % o menos, el PID se rehabilita solo, sin que intervenga el operador.
- **V2:** Quiero que en Automático el PID trabaje con un setpoint del sesenta por ciento; que por encima del noventa por ciento suene la alarma y se pare el PID y la bomba; y que, al volver a noventa o menos, el PID se reactive solo.
- **V3:** Con el sistema en Automático y setpoint del 60 %, habilita el PID; un nivel mayor del 90 % activa la alarma, deshabilita el PID y apaga la bomba; al regresar a 90 % o menos, el PID vuelve a habilitarse automáticamente.

Requisitos del comando:
- R1: En Automatico, PID habilitado con setpoint 60 %.
- R2: Nivel > 90 %: alarma y condicion segura (PID deshabilitado y bomba apagada).
- R3: Con el nivel en 90 % o menos, el PID vuelve a habilitarse por si solo (sin Reset ni intervencion).

Preparacion del test harness (no es requisito del comando):
- Modo Automatico y nivel simulado 50 % antes de la prueba.

Aclaraciones:
- El PID es un bloque estandar prevalidado: solo se evalua la logica supervisora.
- Aclaracion del benchmark: 'condicion segura' = PID deshabilitado y bomba apagada (misma nocion que P07/P11).
- Aclaracion del benchmark: 'rango permitido' = nivel <= 90 %; la recuperacion es automatica (el comando no pide Reset).
