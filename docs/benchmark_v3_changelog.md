# Benchmark v2 -> v3: registro de cambios

Generado por `scripts/build_benchmark_v3.py` el 2026-10-12T12:21:55.

**El refinamiento se hizo ANTES de cualquier ensayo FORMAL.** El benchmark v2 queda archivado byte a byte en
`data/experiment_benchmark/versions/benchmark_v2/` (manifest con hashes) como historico DEVELOPMENT; sus ensayos
no se mezclan con los del v3.

Criterio unico: alineacion entre la especificacion textual y el ground truth (Oracles congelados), segun las
auditorias de ambiguedad D01-D20 (60 variantes) y P01-P12 (36 variantes) y las decisiones humanas aprobadas el
2026-10-12. Ningun cambio se justifica por el resultado de un modelo.

- Comportamiento funcional cambiado: **NO** en los 32 casos.
- Comportamiento de los Oracles cambiado: **NO** (test_sequence, invariantes, tiempos, cleanup, roles y reglas
  identicos). Excepcion registrada: `semantic_expectations` de **D03** (cambio semantico, no funcional).
- Los 32 casos pasan a `benchmark_version = 3`; como ese campo forma parte del hash canonico, los 32 Oracles
  reciben una version nueva con `source_definition` actualizada (16 con cambio de texto, 16 solo metadata).

## Decisiones humanas aplicadas

1. D03: texto sin cambios; acepta `INT_MOTOR_START_STOP` e `INT_MOTOR_LATCH` (simetria funcional con D04/D11).
2. Emergencia (D05, P07): senal logica de simulacion; no representa hardware; no se crea `I_Emergency` en el mapa fisico.
3. Modo: convencion global `MODE_AUTO = TRUE` -> Automatico, `FALSE` -> Manual (un unico selector logico).
4. Senales del arnes de prueba documentadas en Methods (`docs/experimental_interface_v3.md`), no en los comandos.
5. Polaridad: entradas activas en ON, incluido Stop.
6. D03/D04/D11 se conservan; forman una familia funcional para analisis secundario.
7. P07 y P11: comandos completados; los Oracles no se relajan.
8. P03: 0-100 % (benchmark/Oracle) es la fuente v3; la configuracion legacy 10-90 % queda pendiente de alineacion.
9. D14: evaluacion formal con mapa de simulacion con recursos suficientes; el banco fisico no se modifica.

## Cambios por caso

### D03 - Arranque y paro con memoria de marcha

- **Texto:** sin cambios.
- **semantic_expectations:** accepted_intents `['INT_MOTOR_START_STOP']` -> `['INT_MOTOR_START_STOP', 'INT_MOTOR_LATCH']` (cambio semantico, no funcional).
- **Comportamiento funcional cambiado:** NO.
- **Oracle:** v1 -> v2 (BENCHMARK_V3_METADATA + SEMANTIC_EXPECTATIONS); comportamiento identico salvo semantic_expectations.
- **Justificacion:** alineacion especificacion-ground truth (el texto hace explicito lo que el Oracle congelado ya evaluaba).

### D05 - Prioridad de la condicion de emergencia sobre el arranque

| | v2 | v3 |
|---|---|---|
| Canonico | Enciende un motor con Start solo si la condición de seguridad está normal. Si se activa la condición de emergencia, apaga el motor y bloquea el arranque mientras permanezca activa. | Enciende un motor con Start solo si no hay una condición de emergencia activa. Si se activa la emergencia, apaga el motor y bloquea el arranque mientras permanezca activa. |
| V1 | Arranca el motor con Start solo si la condición de seguridad es normal; si se activa la emergencia, apágalo y bloquea el arranque mientras siga activa. | Arranca el motor con Start únicamente si no hay emergencia activa; si se activa, apágalo y bloquea el arranque mientras siga activa. |
| V2 | Quiero que el motor arranque con Start únicamente con la seguridad normal, y que una emergencia lo apague y no deje arrancarlo mientras dure. | Quiero que el motor arranque con Start solo sin emergencia, y que una emergencia lo apague y no deje arrancarlo mientras dure. |
| V3 | Mientras la condición de emergencia esté activa, el motor debe estar apagado y Start no puede arrancarlo; con la seguridad normal, Start enciende el motor. | Mientras la condición de emergencia esté activa, el motor debe estar apagado y Start no puede arrancarlo; sin emergencia, Start enciende el motor. |

- **Ambiguedad eliminada:** E (MISSING_ACTOR_OR_RESOURCE): 'condicion de seguridad normal' y 'condicion de emergencia' podian leerse como dos senales; el Oracle usa una unica senal logica de emergencia (SAFETY_TRIP).
- **Comportamiento funcional cambiado:** NO.
- **Oracle:** v1 -> v2 (BENCHMARK_V3_METADATA); comportamiento identico.
- **Justificacion:** alineacion especificacion-ground truth (el texto hace explicito lo que el Oracle congelado ya evaluaba).

### D08 - Paro automatico tras 10 s de funcionamiento continuo

| | v2 | v3 |
|---|---|---|
| Canonico | Al activar Start, enciende el motor y apágalo automáticamente después de 10 segundos de funcionamiento continuo. | Al activar Start, enciende el motor, mantenlo en marcha aunque se suelte Start y apágalo automáticamente después de 10 segundos de funcionamiento continuo. |
| V1 | Enciende el motor con Start y apágalo automáticamente después de 10 segundos de funcionamiento. | Enciende el motor con Start, que siga en marcha aunque se suelte el pulsador, y apágalo automáticamente tras 10 segundos de funcionamiento. |
| V2 | Haz que el motor arranque con Start y se detenga solo tras funcionar durante 10 segundos. | Haz que el motor arranque con Start, siga funcionando aunque se suelte y se detenga solo tras 10 segundos. |
| V3 | Cuando se active Start, mantén el motor funcionando 10 segundos y después apágalo. | Cuando se active Start, mantén el motor funcionando 10 segundos, aunque se suelte el pulsador, y después apágalo. |

- **Ambiguedad eliminada:** D/I: 'Al activar Start, enciende el motor' admitia leer que el motor solo funciona mientras se mantiene Start; el Oracle (step_2) suelta Start a los 300 ms y exige el motor en marcha hasta los 10 s.
- **Comportamiento funcional cambiado:** NO.
- **Oracle:** v1 -> v2 (BENCHMARK_V3_METADATA); comportamiento identico.
- **Justificacion:** alineacion especificacion-ground truth (el texto hace explicito lo que el Oracle congelado ya evaluaba).

### D13 - Variador habilitado solo sin alarma

| | v2 | v3 |
|---|---|---|
| Canonico | Ante una orden de marcha, habilita el variador solo si no existe una alarma activa. | Con una orden de marcha, habilita el variador solo mientras no exista una alarma activa; si la alarma aparece con el variador habilitado, deshabilítalo. |
| V1 | Ante una orden de marcha, habilita el variador solo si no hay alarma activa. | Habilita el variador con la orden de marcha únicamente mientras no haya alarma activa; si aparece una alarma, deshabilítalo. |
| V2 | Quiero que el variador se habilite con la orden de marcha, pero nunca si existe una alarma activa. | Quiero que el variador se habilite con la orden de marcha, pero nunca mientras exista una alarma activa, ni siquiera si ya estaba funcionando. |
| V3 | Si hay una alarma activa, el variador no debe habilitarse aunque llegue la orden de marcha; sin alarma, habilítalo con esa orden. | Mientras haya una alarma activa el variador debe estar deshabilitado, aunque tenga orden de marcha; sin alarma, habilítalo con esa orden. |

- **Ambiguedad eliminada:** A/I (ACTION_VS_CONDITION, TEMPORAL): 'ante una orden de marcha, habilita... solo si' admitia comprobar la alarma solo al dar la orden; el Oracle (step_2, INV_ALARM_VFD CRITICAL) exige un permisivo continuo.
- **Comportamiento funcional cambiado:** NO.
- **Oracle:** v1 -> v2 (BENCHMARK_V3_METADATA); comportamiento identico.
- **Justificacion:** alineacion especificacion-ground truth (el texto hace explicito lo que el Oracle congelado ya evaluaba).

### D15 - Modo Manual/Automatico con orden por modo

| | v2 | v3 |
|---|---|---|
| Canonico | Implementa modo Manual y Automático para el motor: en Manual responde a una orden manual y en Automático a una orden automática. | El operador elige el modo del motor con un selector Manual/Automático: en Automático el motor sigue la orden automática y en Manual sigue la orden manual; la orden del otro modo no tiene efecto. |
| V1 | Implementa modo Manual y Automático para el motor: en Manual obedece la orden manual y en Automático la orden automática. | Con un selector Manual/Automático: en Automático, el motor obedece la orden automática; en Manual, la orden manual; la otra orden se ignora. |
| V2 | Quiero que en modo Manual el motor responda a la orden manual y en modo Automático a la orden automática. | Quiero un selector Manual/Automático: en Automático el motor responde a la orden automática y en Manual a la orden manual, sin que la otra orden haga nada. |
| V3 | Según el modo seleccionado, Manual o Automático, el motor debe atender la orden manual o la orden automática respectivamente. | Según la posición del selector, Manual o Automático, el motor atiende la orden manual o la orden automática respectivamente, e ignora la del otro modo. |

- **Ambiguedad eliminada:** H (MODE_AMBIGUITY): no decia si Manual es 'no Automatico' (un selector) o una entrada propia; el Oracle usa un unico selector MODE_AUTO (C-D15-MODES).
- **Comportamiento funcional cambiado:** NO.
- **Oracle:** v1 -> v2 (BENCHMARK_V3_METADATA); comportamiento identico.
- **Justificacion:** alineacion especificacion-ground truth (el texto hace explicito lo que el Oracle congelado ya evaluaba).

### D17 - Supervision de sensor 5 s tras Start

| | v2 | v3 |
|---|---|---|
| Canonico | Al activar Start, supervisa un sensor; si no cambia de estado durante 5 segundos, activa una alarma. | Al activar Start, supervisa un sensor: si pasan 5 segundos sin que cambie de estado, activa una alarma; cada cambio del sensor vuelve a contar los 5 segundos. |
| V1 | Al activar Start, vigila el sensor y activa una alarma si no cambia de estado durante 5 segundos. | Tras activar Start, vigila el sensor y activa una alarma si transcurren 5 segundos sin ningún cambio; cada cambio reinicia la cuenta. |
| V2 | Quiero que, después de dar Start, se active una alarma si el sensor pasa cinco segundos sin cambiar de estado. | Quiero que, después de dar Start, salte una alarma si el sensor pasa cinco segundos seguidos sin cambiar de estado. |
| V3 | Tras activar Start, si el sensor permanece sin cambios 5 segundos, activa la alarma. | Con Start activado, si el sensor permanece sin cambios durante 5 segundos seguidos, activa la alarma. |

- **Ambiguedad eliminada:** I/A (TEMPORAL): 'si no cambia de estado durante 5 segundos' admitia una ventana unica tras Start; el Oracle (t4_timeout) cuenta los 5 s desde el ultimo cambio del sensor.
- **Comportamiento funcional cambiado:** NO.
- **Oracle:** v1 -> v2 (BENCHMARK_V3_METADATA); comportamiento identico.
- **Justificacion:** alineacion especificacion-ground truth (el texto hace explicito lo que el Oracle congelado ya evaluaba).

### D19 - Pilotos de estado: detenido, marcha y falla

| | v2 | v3 |
|---|---|---|
| Canonico | Controla tres pilotos para indicar detenido, marcha y falla, manteniendo activo únicamente el correspondiente al estado actual. | Controla tres pilotos según las señales de marcha y de falla del sistema: detenido, marcha y falla, manteniendo activo únicamente el del estado actual. |
| V1 | Controla tres pilotos de detenido, marcha y falla, dejando encendido solo el del estado actual. | Con las señales de marcha y falla del sistema, controla tres pilotos (detenido, marcha y falla) y deja encendido solo el del estado actual. |
| V2 | Quiero tres pilotos, detenido, marcha y falla, y que solo esté encendido el que corresponde al estado actual. | Quiero tres pilotos, detenido, marcha y falla, que según las señales de marcha y falla del sistema dejen encendido solo el que corresponde al estado actual. |
| V3 | Indica con tres pilotos si el sistema está detenido, en marcha o en falla; únicamente debe encenderse el del estado actual. | A partir de las señales de marcha y de falla, indica con tres pilotos si el sistema está detenido, en marcha o en falla; únicamente debe encenderse el del estado actual. |

- **Ambiguedad eliminada:** E (MISSING_ACTOR_OR_RESOURCE): no decia de donde sale el estado; el Oracle recibe marcha y falla como senales del sistema (C-D19-INPUTS).
- **Comportamiento funcional cambiado:** NO.
- **Oracle:** v1 -> v2 (BENCHMARK_V3_METADATA); comportamiento identico.
- **Justificacion:** alineacion especificacion-ground truth (el texto hace explicito lo que el Oracle congelado ya evaluaba).

### P01 - Modo automatico al seleccionar Automatico

| | v2 | v3 |
|---|---|---|
| Canonico | Habilita el modo automático del sistema de nivel cuando se seleccione Automático. | El sistema de nivel debe pasar a modo automático solo cuando el operador seleccione Automático. |
| V1 | Habilita el modo automático del sistema de nivel al seleccionar Automático. | Pasa el sistema de nivel a modo automático únicamente cuando el operador seleccione Automático. |
| V2 | Quiero que el sistema de nivel pase a modo automático cuando se elija Automático. | Quiero que el control de nivel entre en automático solo si el operador elige Automático. |
| V3 | Cuando se seleccione Automático, activa el modo automático del control de nivel. | Solo al seleccionar el operador Automático debe el sistema de nivel ponerse en modo automático. |

- **Ambiguedad eliminada:** A/H: 'Habilita el modo automatico' admitia 'permitir que se pueda seleccionar'; el Oracle exige que el modo pase a automatico solo al seleccionarlo (step_0/step_1).
- **Comportamiento funcional cambiado:** NO.
- **Oracle:** v1 -> v2 (BENCHMARK_V3_METADATA); comportamiento identico.
- **Justificacion:** alineacion especificacion-ground truth (el texto hace explicito lo que el Oracle congelado ya evaluaba).

### P03 - Setpoint validado en el rango 0-100 %

- **Texto:** sin cambios.
- **Nombres funcionales (metadata):** ['validate_setpoint', 'keep_last_valid'] -> ['reject_unsafe_setpoint'] (alineados con el Oracle; no puntuan).
- **Comportamiento funcional cambiado:** NO.
- **Oracle:** v1 -> v2 (BENCHMARK_V3_METADATA); comportamiento identico.
- **Justificacion:** alineacion especificacion-ground truth (el texto hace explicito lo que el Oracle congelado ya evaluaba).

### P04 - Alarma de nivel alto > 90 %

| | v2 | v3 |
|---|---|---|
| Canonico | Activa una alarma de nivel alto cuando el nivel supere el 90 %. | Activa la alarma de nivel alto mientras el nivel esté por encima del 90 % y desactívala cuando vuelva a 90 % o menos. |
| V1 | Activa la alarma de nivel alto cuando el nivel pase del 90 %. | Mantén activa la alarma de nivel alto mientras el nivel supere el 90 % y apágala cuando baje a 90 % o menos. |
| V2 | Quiero una alarma de nivel alto si el nivel supera el noventa por ciento. | Quiero que la alarma de nivel alto suene mientras el nivel pase del noventa por ciento y se quite al volver a noventa o menos. |
| V3 | Con el nivel por encima del 90 %, activa la alarma de nivel alto. | Con el nivel por encima del 90 %, la alarma de nivel alto debe estar activa; a 90 % o menos, desactivada. |

- **Ambiguedad eliminada:** D (MISSING_LATCH_RESET_RULE): no decia que la alarma se desactiva al bajar del umbral; el Oracle (step_2) lo exige (alarma no enclavada).
- **Comportamiento funcional cambiado:** NO.
- **Oracle:** v1 -> v2 (BENCHMARK_V3_METADATA); comportamiento identico.
- **Justificacion:** alineacion especificacion-ground truth (el texto hace explicito lo que el Oracle congelado ya evaluaba).

### P05 - Alarma de nivel bajo < 10 %

| | v2 | v3 |
|---|---|---|
| Canonico | Activa una alarma de nivel bajo cuando el nivel sea inferior al 10 %. | Activa la alarma de nivel bajo mientras el nivel esté por debajo del 10 % y desactívala cuando vuelva a 10 % o más. |
| V1 | Activa la alarma de nivel bajo cuando el nivel baje del 10 %. | Mantén activa la alarma de nivel bajo mientras el nivel esté por debajo del 10 % y apágala cuando suba a 10 % o más. |
| V2 | Quiero una alarma de nivel bajo si el nivel es inferior al diez por ciento. | Quiero que la alarma de nivel bajo suene mientras el nivel sea inferior al diez por ciento y se quite al volver a diez o más. |
| V3 | Con el nivel por debajo del 10 %, activa la alarma de nivel bajo. | Con el nivel por debajo del 10 %, la alarma de nivel bajo debe estar activa; a 10 % o más, desactivada. |

- **Ambiguedad eliminada:** D (+ I en V1): no decia que la alarma se desactiva al subir del umbral; V1 'cuando baje del 10 %' admitia una lectura de flanco; el Oracle (step_2) exige alarma no enclavada.
- **Comportamiento funcional cambiado:** NO.
- **Oracle:** v1 -> v2 (BENCHMARK_V3_METADATA); comportamiento identico.
- **Justificacion:** alineacion especificacion-ground truth (el texto hace explicito lo que el Oracle congelado ya evaluaba).

### P06 - PID habilitado solo en Automatico

| | v2 | v3 |
|---|---|---|
| Canonico | Habilita el PID únicamente cuando el sistema esté en modo Automático. | El PID solo debe estar habilitado mientras el sistema se encuentre en modo Automático, que selecciona el operador; en modo Manual debe permanecer deshabilitado. |
| V1 | Habilita el PID solo cuando el sistema esté en modo Automático. | Mantén el PID habilitado únicamente mientras el operador tenga el sistema en Automático; en Manual, deshabilitado. |
| V2 | Quiero que el PID funcione únicamente en modo Automático. | Quiero que el PID solo funcione cuando el operador haya puesto el sistema en Automático, y que en Manual quede deshabilitado. |
| V3 | El PID debe estar habilitado solamente mientras el sistema esté en Automático. | Solo con el sistema en el modo Automático elegido por el operador puede estar habilitado el PID; en Manual debe estar deshabilitado. |

- **Ambiguedad eliminada:** A/H/E: 'Habilita el PID unicamente cuando el sistema este en Automatico' admitia una orden de poner el Automatico; el Oracle trata el modo como seleccion del operador (C-P06) y exige el PID deshabilitado en Manual (pre_manual, step_2, INV_PID_ONLY_AUTO). Sin instrucciones negativas tipo 'no cambies el modo'.
- **Comportamiento funcional cambiado:** NO.
- **Oracle:** v1 -> v2 (BENCHMARK_V3_METADATA); comportamiento identico.
- **Justificacion:** alineacion especificacion-ground truth (el texto hace explicito lo que el Oracle congelado ya evaluaba).

### P07 - PID deshabilitado ante emergencia

| | v2 | v3 |
|---|---|---|
| Canonico | Si se activa una condición de emergencia mientras el PID está funcionando, deshabilítalo inmediatamente. | Con el sistema en Automático el PID trabaja habilitado; si se activa una condición de emergencia, deshabilita el PID de inmediato. |
| V1 | Si se activa una condición de emergencia con el PID funcionando, deshabilítalo de inmediato. | En Automático el PID funciona habilitado, pero si se activa una emergencia, deshabilítalo inmediatamente. |
| V2 | Quiero que, si hay una emergencia mientras el PID trabaja, el PID se deshabilite en el acto. | Quiero que el PID esté habilitado en Automático y que, si hay una emergencia, se deshabilite en el acto. |
| V3 | Ante una condición de emergencia durante el funcionamiento del PID, deshabilítalo inmediatamente. | Ante una condición de emergencia, el PID, que en Automático está habilitado, debe deshabilitarse de inmediato. |

- **Ambiguedad eliminada:** J (HIDDEN_ORACLE_REQUIREMENT): el Oracle exige el PID habilitado en Automatico antes del disparo (pre_enabled); el comando lo presuponia sin decirlo. Se completa el comando (no se relaja el Oracle).
- **Nombres funcionales (metadata):** ['emergency_disables_pid'] -> ['safety_trip_disables_pid'] (alineados con el Oracle; no puntuan).
- **Comportamiento funcional cambiado:** NO.
- **Oracle:** v1 -> v2 (BENCHMARK_V3_METADATA); comportamiento identico.
- **Justificacion:** alineacion especificacion-ground truth (el texto hace explicito lo que el Oracle congelado ya evaluaba).

### P08 - Bomba manual ON/OFF en modo Manual

| | v2 | v3 |
|---|---|---|
| Canonico | En modo Manual, permite encender y apagar la bomba mediante una orden manual, sin que el control automático la gobierne. | Cuando el sistema esté en modo Manual, es decir, siempre que no esté en Automático, la bomba debe encenderse y apagarse solo con la orden manual del operador; el control automático no debe actuar sobre ella. |
| V1 | En modo Manual, enciende y apaga la bomba con una orden manual, sin que el control automático intervenga. | Siempre que el sistema no esté en Automático, o sea en Manual, la orden manual del operador enciende y apaga la bomba, sin que actúe el control automático. |
| V2 | Quiero que en Manual la bomba se encienda y se apague solo con la orden manual, no con el control automático. | Quiero que, mientras el sistema no esté en Automático, la bomba solo se encienda y apague con la orden manual del operador. |
| V3 | Con el sistema en Manual, la orden manual decide si la bomba está encendida o apagada; el control automático no la gobierna. | Fuera del modo Automático, en Manual, la bomba debe seguir únicamente la orden manual del operador para encenderse o apagarse. |

- **Ambiguedad eliminada:** H (MODE_AMBIGUITY): no decia que Manual equivale a 'no Automatico'; el Oracle solo pone AUTO_MODE = falso (pre_manual). V1 convertia el permiso en accion directa.
- **Comportamiento funcional cambiado:** NO.
- **Oracle:** v1 -> v2 (BENCHMARK_V3_METADATA); comportamiento identico.
- **Justificacion:** alineacion especificacion-ground truth (el texto hace explicito lo que el Oracle congelado ya evaluaba).

### P09 - Fallo de sensor fuera de 0-100 %

| | v2 | v3 |
|---|---|---|
| Canonico | Detecta un fallo del sensor si el nivel medido está fuera del rango de 0 % a 100 %. | Indica fallo del sensor mientras el nivel medido esté por debajo de 0 % o por encima de 100 %; cuando vuelva a estar entre 0 % y 100 %, el fallo debe desaparecer. |
| V1 | Detecta fallo de sensor cuando el nivel medido esté fuera del rango de 0 % a 100 %. | Señala fallo de sensor mientras el nivel medido esté fuera de 0 % a 100 % y quítalo cuando vuelva a ese rango. |
| V2 | Quiero que se marque un fallo del sensor si el nivel medido sale del rango de cero a cien por ciento. | Quiero que se marque fallo del sensor mientras el nivel medido salga del rango de cero a cien por ciento, y que se quite al volver a él. |
| V3 | Si el nivel medido no está entre 0 % y 100 %, indica un fallo del sensor. | Con el nivel medido por debajo de 0 % o por encima de 100 % debe haber fallo de sensor; dentro de ese rango, no. |

- **Ambiguedad eliminada:** D (MISSING_LATCH_RESET_RULE): no decia que el fallo desaparece al volver al rango; el Oracle (step_2) lo exige.
- **Comportamiento funcional cambiado:** NO.
- **Oracle:** v1 -> v2 (BENCHMARK_V3_METADATA); comportamiento identico.
- **Justificacion:** alineacion especificacion-ground truth (el texto hace explicito lo que el Oracle congelado ya evaluaba).

### P10 - Reset de alarma de sensor solo sin falla

| | v2 | v3 |
|---|---|---|
| Canonico | Si existe una alarma por fallo del sensor, no permitas resetearla mientras la falla continúe; permite el Reset cuando la medición vuelva al rango válido. | Activa una alarma cuando el nivel medido salga del rango de 0 % a 100 % por fallo del sensor. Mientras la medición siga fuera de ese rango, el Reset no debe borrar la alarma; cuando vuelva al rango, el Reset sí debe borrarla. |
| V1 | Si hay una alarma por fallo del sensor, no permitas su Reset mientras la falla siga; permítelo cuando la medición vuelva al rango válido. | Genera una alarma si el nivel medido sale de 0 % a 100 % por fallo del sensor; el Reset no la borra mientras siga fuera y sí cuando vuelva al rango. |
| V2 | Quiero que la alarma por fallo del sensor no se pueda resetear mientras dure la falla, y que sí se pueda cuando la medición vuelva a ser válida. | Quiero una alarma por fallo del sensor cuando la medición salga de cero a cien por ciento, que no se pueda resetear mientras dure y sí al volver al rango. |
| V3 | El Reset de la alarma por fallo del sensor solo debe funcionar cuando la medición haya vuelto al rango válido, no mientras continúe la falla. | Un nivel medido fuera de 0 % a 100 % debe activar la alarma de fallo del sensor; el Reset solo la borra cuando la medición vuelve a ese rango. |

- **Ambiguedad eliminada:** G/J: el Oracle exige que la alarma la provoque el fallo del sensor (pre_fault) y usa como 'rango valido' 0-100 % (C-P10, de P09); el comando presuponia la alarma y no daba el rango.
- **Comportamiento funcional cambiado:** NO.
- **Oracle:** v1 -> v2 (BENCHMARK_V3_METADATA); comportamiento identico.
- **Justificacion:** alineacion especificacion-ground truth (el texto hace explicito lo que el Oracle congelado ya evaluaba).

### P11 - Bomba apagada por sobrellenado >= 95 %

| | v2 | v3 |
|---|---|---|
| Canonico | Si el nivel alcanza o supera el 95 %, considera sobrellenado y apaga la bomba mientras esa condición permanezca activa. | En operación normal la bomba está en marcha; si el nivel alcanza o supera el 95 %, considéralo sobrellenado y mantén la bomba apagada mientras dure esa condición. |
| V1 | Si el nivel llega o supera el 95 %, trátalo como sobrellenado y apaga la bomba mientras dure esa condición. | Con el nivel normal la bomba funciona; si el nivel llega o supera el 95 %, trátalo como sobrellenado y apaga la bomba mientras dure. |
| V2 | Quiero que la bomba se apague mientras el nivel esté en el noventa y cinco por ciento o más, porque es sobrellenado. | Quiero que la bomba trabaje normalmente y que se apague mientras el nivel esté en el noventa y cinco por ciento o más, por sobrellenado. |
| V3 | Considera sobrellenado un nivel igual o superior al 95 % y mantén la bomba apagada mientras siga así. | La bomba, en marcha en condiciones normales, debe quedar apagada mientras el nivel sea igual o superior al 95 % (sobrellenado). |

- **Ambiguedad eliminada:** J (HIDDEN_ORACLE_REQUIREMENT): el Oracle exige la bomba en marcha con nivel normal antes del sobrellenado (pre_normal); el comando no lo decia. Se completa el comando (no se relaja el Oracle).
- **Nombres funcionales (metadata):** ['overfill_pump_stop'] -> ['safe_overfill_stop'] (alineados con el Oracle; no puntuan).
- **Comportamiento funcional cambiado:** NO.
- **Oracle:** v1 -> v2 (BENCHMARK_V3_METADATA); comportamiento identico.
- **Justificacion:** alineacion especificacion-ground truth (el texto hace explicito lo que el Oracle congelado ya evaluaba).

### P12 - Automatico con SP 60 %, alarma > 90 % y recuperacion

| | v2 | v3 |
|---|---|---|
| Canonico | En modo Automático, habilita el PID con un setpoint del 60 %. Si el nivel supera el 90 %, activa la alarma y lleva el proceso a condición segura. Cuando el nivel vuelva al rango permitido, permite recuperar la operación automática. | En modo Automático, habilita el PID con un setpoint del 60 %. Si el nivel supera el 90 %, activa la alarma y lleva el proceso a condición segura: PID deshabilitado y bomba apagada. Cuando el nivel vuelva a 90 % o menos, el PID debe volver a habilitarse por sí solo, sin intervención del operador. |
| V1 | En modo Automático, habilita el PID con setpoint del 60 %; si el nivel supera el 90 %, activa la alarma y lleva el proceso a condición segura, y cuando vuelva al rango permitido deja recuperar la operación automática. | En Automático, PID habilitado con setpoint del 60 %; por encima del 90 %, alarma y condición segura (PID deshabilitado y bomba apagada); al volver a 90 % o menos, el PID se rehabilita solo, sin que intervenga el operador. |
| V2 | Quiero que en Automático el PID trabaje con un setpoint del sesenta por ciento, que por encima del noventa por ciento suene la alarma y el proceso pase a condición segura, y que al volver el nivel al rango permitido se pueda recuperar el automático. | Quiero que en Automático el PID trabaje con un setpoint del sesenta por ciento; que por encima del noventa por ciento suene la alarma y se pare el PID y la bomba; y que, al volver a noventa o menos, el PID se reactive solo. |
| V3 | Con el sistema en Automático y setpoint del 60 %, habilita el PID; un nivel mayor del 90 % activa la alarma y la condición segura, y el regreso del nivel al rango permitido permite recuperar la operación automática. | Con el sistema en Automático y setpoint del 60 %, habilita el PID; un nivel mayor del 90 % activa la alarma, deshabilita el PID y apaga la bomba; al regresar a 90 % o menos, el PID vuelve a habilitarse automáticamente. |

- **Ambiguedad eliminada:** F/G/C: 'condicion segura', 'rango permitido' y la recuperacion automatica solo estaban en aclaraciones del catalogo; el Oracle exige PID deshabilitado y bomba apagada (step_2) y rehabilitacion sin Reset a 90 % o menos (step_3).
- **Comportamiento funcional cambiado:** NO.
- **Oracle:** v1 -> v2 (BENCHMARK_V3_METADATA); comportamiento identico.
- **Justificacion:** alineacion especificacion-ground truth (el texto hace explicito lo que el Oracle congelado ya evaluaba).

## Casos sin cambios de texto (solo benchmark_version y Oracle metadata)

D01, D02, D04, D06, D07, D09, D10, D11, D12, D14, D16, D18, D20, P02

## Oracles re-versionados

| Caso | Version | Alcance | Hash nuevo |
|---|---|---|---|
| D01 | v1 -> v2 | BENCHMARK_V3_METADATA | `5eff52840e121774` |
| D02 | v1 -> v2 | BENCHMARK_V3_METADATA | `76c046eaddc44153` |
| D03 | v1 -> v2 | BENCHMARK_V3_METADATA + SEMANTIC_EXPECTATIONS | `f1c5bf3ee7f708d3` |
| D04 | v1 -> v2 | BENCHMARK_V3_METADATA | `a299ff8d88e2a307` |
| D05 | v1 -> v2 | BENCHMARK_V3_METADATA | `1928377b0e610748` |
| D06 | v1 -> v2 | BENCHMARK_V3_METADATA | `2f4540fb9185b970` |
| D07 | v2 -> v3 | BENCHMARK_V3_METADATA | `ef89ba4115fffbf5` |
| D08 | v1 -> v2 | BENCHMARK_V3_METADATA | `2a7463e479914c8f` |
| D09 | v1 -> v2 | BENCHMARK_V3_METADATA | `5c8f2bb3a0ad4b6d` |
| D10 | v1 -> v2 | BENCHMARK_V3_METADATA | `db41ac94ab24b36b` |
| D11 | v1 -> v2 | BENCHMARK_V3_METADATA | `57c93841ac371edb` |
| D12 | v2 -> v3 | BENCHMARK_V3_METADATA | `71cb20e92b7d8e61` |
| D13 | v1 -> v2 | BENCHMARK_V3_METADATA | `e1e7ec3301bc247f` |
| D14 | v1 -> v2 | BENCHMARK_V3_METADATA | `1cefcbee200446e9` |
| D15 | v1 -> v2 | BENCHMARK_V3_METADATA | `6cc504987db5c37e` |
| D16 | v1 -> v2 | BENCHMARK_V3_METADATA | `47dd88ea9664afff` |
| D17 | v1 -> v2 | BENCHMARK_V3_METADATA | `f757df8d6f6c2f9c` |
| D18 | v1 -> v2 | BENCHMARK_V3_METADATA | `a11e0bbec7329ec6` |
| D19 | v1 -> v2 | BENCHMARK_V3_METADATA | `101f21568dc5d57c` |
| D20 | v1 -> v2 | BENCHMARK_V3_METADATA | `9cbe97bddbb6a934` |
| P01 | v1 -> v2 | BENCHMARK_V3_METADATA | `ad686822b466d75d` |
| P02 | v1 -> v2 | BENCHMARK_V3_METADATA | `4bafcce6b0d44a63` |
| P03 | v1 -> v2 | BENCHMARK_V3_METADATA | `50fe20c9e9052060` |
| P04 | v1 -> v2 | BENCHMARK_V3_METADATA | `396800b290ebc216` |
| P05 | v1 -> v2 | BENCHMARK_V3_METADATA | `c11fe837b3970630` |
| P06 | v1 -> v2 | BENCHMARK_V3_METADATA | `b1c474fcc6dbbdfc` |
| P07 | v1 -> v2 | BENCHMARK_V3_METADATA | `a3bcdea3164a8b8e` |
| P08 | v1 -> v2 | BENCHMARK_V3_METADATA | `77889a51f0da9369` |
| P09 | v1 -> v2 | BENCHMARK_V3_METADATA | `9b0a99e3a00655f7` |
| P10 | v1 -> v2 | BENCHMARK_V3_METADATA | `d700ca642636423f` |
| P11 | v1 -> v2 | BENCHMARK_V3_METADATA | `bc7b522fccd39200` |
| P12 | v1 -> v2 | BENCHMARK_V3_METADATA | `df683f9a4fdf8ad4` |

Archivo v2: 75 archivos verificados por hash.
