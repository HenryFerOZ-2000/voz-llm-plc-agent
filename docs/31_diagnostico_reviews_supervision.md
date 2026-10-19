# Diagnóstico de los 19 REVIEW de supervisión

Revisión iniciada el 19 de octubre de 2026. Estos resultados pertenecen a P01–P12,
que evalúan la supervisión de un controlador existente; son distintos de la
regulación nativa de PID_Compact ya comprobada con el tanque virtual.

## Qué se encontró

Se examinó cada comando, respuesta conservada, programa SCL, declaración de
variables y reporte del evaluador. Los 19 REVIEW se distribuyen así:

| Casos y variantes | Cantidad | Causa del REVIEW original | Comprobación adicional local |
|---|---:|---|---|
| P01 V2 | 1 | El programa declara M_AutoMode; el contrato espera Auto_Mode. Además, la plantilla heredaba recursos y lógica de un motor aunque la orden solo pedía seleccionar modo. | Se reprodujo el arranque no solicitado y la dependencia de un segundo selector. Corrección con regresiones. |
| P04 V1–V3 | 3 | La alarma se implementa como salida digital; falta el miembro interno High_Level_Alarm requerido por el contrato de observación. | Alarma únicamente por encima de 90 %, incluida la vuelta al límite: correcta. |
| P05 V1–V3 | 3 | Salida digital de alarma en lugar del miembro Low_Level_Alarm esperado. | Alarma únicamente por debajo de 10 %, incluida la vuelta al límite: correcta. |
| P08 V1–V3 | 3 | Selector y bomba implementados por la plantilla manual/automático; el contrato busca Auto_Mode y rutas de parámetros diferentes. | Orden manual, cambio a automático y prioridad de emergencia: correctos. |
| P09 V1 | 1 | El fallo se indica mediante salida digital; el contrato exige el miembro interno Sensor_Fault. | Límites 0 y 100 incluidos y recuperación de rango: correctos. |
| P10 V1 y V3 | 2 | El enclavamiento se compone directamente sobre la salida, sin el miembro Sensor_Fault ni todas las rutas esperadas por el contrato. | Reset no borra con fallo; sin fallo exige Reset: correcto. |
| P11 V1–V3 | 3 | La condición y el bloqueo se componen sobre la bomba, pero el contrato solo reconoce la ruta pump_output. | Marcha normal, parada desde 95 %, recuperación y emergencia: correctas. |
| P12 V1–V3 | 3 | Los roles se resuelven; falta la etiqueta high_level_alarm, aunque safe_overfill_stop ya activa la alarma solicitada. | Consigna 60 %, condición segura por encima de 90 %, recuperación del PID y emergencia: correctos. La orden no exige apagar automáticamente la alarma al recuperarse el nivel. |

En 16 casos faltan roles observables para el evaluador y en tres la discrepancia
restante es semántica. Las comprobaciones locales de 18 programas satisfacen
las propiedades verificadas. P01 V2 reveló un error real adicional a su
discrepancia de observación.

## Corrección del selector

El motor compartido distingue una selección de modo sin órdenes de actuador.
Para la forma comprobada, utiliza el selector declarado y las memorias de modo;
no añade Start, Stop, un segundo selector ni salidas. Si la forma es incompleta
o incompatible, solicita aclaración antes de completar recursos de motor.
Las solicitudes con órdenes de actuación y los contratos previos conservan su
recorrido correspondiente.

La decisión se deriva de la estructura interpretada y no de un identificador
P01, del texto de un benchmark o de un Oracle. El marcador interno de alcance
se recalcula; no se acepta como autorización proporcionada por el LLM.

La revisión independiente reprodujo dos formas incompletas que aún podían
heredar la plantilla de motor. Ambas se rechazaron antes de completar defaults,
con pruebas RED y GREEN. La suite oficial posterior terminó con **2051 pruebas
aprobadas, 7 omitidas y 1 fallo esperado**, sin cambios en los 529 archivos de
entrada durante la ejecución. Las omisiones conservan las dependencias externas
ya documentadas; la campaña FORMAL anterior requiere un nuevo congelamiento.

## Evidencia y alcance

La carpeta de trabajo `runtime/worktrees/project-closure/` conserva:

- `runtime/review_diagnosis_20261019/initial_diagnosis.json`: los 19 comandos,
  programas y referencias a reportes originales.
- `runtime/review_diagnosis_20261019/offline_behavior_resolved_signals.json`:
  comprobaciones ciclo a ciclo del SCL congelado usando las señales que realmente
  declara cada programa. Se conservaron también los primeros sondeos, que usaban
  nombres fijos y producían falsos negativos por nombres diferentes.
- `runtime/review_selector_red.log` y `runtime/review_selector_review_red.log`:
  reproducciones anteriores a cada corrección; reportes GREEN posteriores.
- `tests/test_mode_selection_only.py`: regresiones de recursos, lógica, nombres
  distintos, compatibilidad y rechazo de formas incompletas en el motor compartido.
- `runtime/review_selector_regression_frozen_report.json` y
  `runtime/review_selector_full_suite.log`: regresión completa y sello de entradas.
- `runtime/rv/pb733c/prepared.json`: 19 respuestas regeneradas sin llamadas nuevas
  a OpenAI; solo P01 V2 cambia su SCL. Los 18 restantes conservan el mismo programa.
- `runtime/review_diagnosis_20261019/offline_behavior_after.json`: las 19
  comprobaciones locales adicionales pasan con los programas regenerados.

Estos sondeos locales utilizan SclMachine y no sustituyen una prueba en TIA y
PLCSIM. La comprobación adicional en vivo tiene su protocolo propio y devuelve
sin cambios el veredicto canónico del Oracle. Su resultado adicional se conserva
en otro archivo; no convierte REVIEW en PASS.

El primer preflight en vivo, `runtime/rv/abc3b8/summary.json`, encontró cero
instancias PLCSIM registradas antes de generar o evaluar casos. No ejecutó pruebas
funcionales. El intento de restauración redundante también se conserva; no había
CPU disponible para recibirlo. El runner se corrigió para no intentar restaurar
un programa si el preflight terminó antes de cualquier posible escritura de CPU.

## Uso en la tesis

Los REVIEW históricos permanecen íntegros. Las discrepancias de observación
deben explicarse y acordarse como parte del diseño de la campaña final: se puede
requerir expresamente una interfaz supervisora o definir y validar una nueva
versión del contrato que admita representaciones equivalentes. Los resultados
de contratos diferentes se informan por separado. Un sondeo adicional aprobado
no cambia el resultado histórico ni demuestra equivalencia universal.

Estado de la repetición en PLCSIM y de la integración: consultar
`runtime/review_diagnosis_20261019/delivery.json` cuando se genere el cierre.
La repetición adicional en TIA y PLCSIM terminó: **19 de 19 comprobaciones
adicionales aprobadas**, con limpieza verificada. La ronda es
`runtime/rv/rc75d7/summary.json`. P01 V2 conserva su primer intento
fallido al conectar durante la descarga; el reintento técnico pasó sin cambiar
la conexión. Cada caso tiene su protocolo y su traza separados del Oracle.

Se restauró por descarga el programa Normal de S71500_Prueba. Una lectura nueva
verificó su identidad, controlador detenido, mando cero y las mismas ganancias
guardadas. Se conservaron la configuración Normal, los Oracles y los artefactos
históricos comprobados.

Los **19 veredictos canónicos siguen siendo REVIEW**. Las comprobaciones
adicionales cierran este diagnóstico funcional acotado; la campaña final debe
declarar qué interfaz y versión del contrato utiliza. No se adjudica un PASS
canónico ni se congela una versión final automáticamente.
