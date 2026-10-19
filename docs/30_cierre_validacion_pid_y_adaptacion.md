# Validación de cierre: PID, supervisión y adaptación

Implementación integrada y comprobada en la carpeta principal el 18 de octubre
de 2026. Se conserva la rama `feat/project-closure-20261018`, los respaldos y
la evidencia de desarrollo. Esto no constituye una campaña FORMAL ni una
validación física.

## Evidencia obtenida

| Comprobación | Resultado observado | Evidencia |
|---|---|---|
| P01–P12, tres variantes, intérprete real | 36 respuestas conservadas; 18 generaciones correctas y 18 bloqueadas | `runtime/project_closure_rounds/PID_DEV_29bd9731b979/summary.json` |
| Segunda ronda autorizada con medición declarada | 26 generaciones correctas y 10 fallidas; no son veredictos de ejecución | `runtime/project_closure_rounds/PID_DEV_f4471165b64a/summary.json` |
| Reproducción local tras corregir analizador y declaración de PV | 36/36 primeras respuestas generan programa; cobertura de ejecución: 17 PASS y 19 REVIEW, sin nuevas llamadas a OpenAI | `runtime/project_closure_rounds/REPLAY_1b9489df4994/summary.json`, `runtime/closure_current_program_runtime_coverage.json` |
| Importación PID experimental | Compilación TIA correcta, cero errores y archivo verificado antes de descargar | `runtime/cne/NPID_cbad356284d2/compile_report.json` |
| Regulación PID nativa en PLCSIM | PASSED, ejecución nativa y limpieza confirmadas; MASTER sin cambios | `runtime/cne/NPID_cbad356284d2/native_run.json` |
| Persistencia y reutilización en copia | Subida y guardado en TIA, SAVED_VERIFIED desde la GUI y regulación posterior con las mismas ganancias sin otra sintonización; fallo inicial de muestreo conservado | `runtime/closure_copy_persistence_aggregate.json`, `runtime/pnf/03841f/gui_saved_verified.json` |
| PID en el proyecto Normal principal | Importación, compilación y descarga en S71500_Prueba con la conexión habitual; sintonización, subida en TIA, SAVED_VERIFIED y nueva descarga con REUSE_VERIFIED sin retocar las ganancias; limpieza confirmada | `runtime/rnf/f8581f/flow.json` (carpeta principal) |
| Evaluación aislada desde la GUI | PASSED con ejecución nativa y limpieza verificadas | `runtime/native_pid_evaluations/NPID_8995f684f40c/native_run.json` |
| Adaptación de mapas | Las cinco variantes pasaron compilación y ejecución en PLCSIM; restauración y MASTER comprobados | `runtime/mv/MAP_DEV_0f84f08f78/summary.json` |
| Regresión tras la corrección de muestreo | 2040 aprobadas, 7 omitidas, 1 fallo esperado; 527 archivos de entrada sin cambios y coincidencia literal con el código comprobado | `runtime/closure_final_regression_verified.json`, `runtime/closure_final_word_fix_tests.log` |

Los 36 ensayos P son de **supervisión de un PID existente**. No equivalen a las
pruebas de regulación del bloque PID_Compact y sus resultados no se mezclan.
La ronda inicial usó la selección de mapas anterior; sus fallos se conservaron.
La segunda ronda se ejecutó con autorización expresa. Sus fallos originales se conservan.
Las reproducciones locales se identifican como `OFFLINE_RESPONSE_REPLAY`; no son
una tercera medición independiente de exactitud del LLM. Una reproducción intermedia
descubrió en TIA que las condiciones genéricas no declaraban `Level_PV`, corregido
con una prueba de generación que comprueba su declaración REAL y su referencia local.
La cobertura final combina doce evaluaciones directas de programas nuevos o
corregidos y veinticuatro referencias a ejecuciones anteriores cuyos artefactos
son idénticos byte por byte. Esta vinculación se conserva por separado; no se
escribieron veredictos ficticios en los ensayos nuevos ni se alteraron Oracles.
Los diecinueve REVIEW siguen requiriendo análisis de compatibilidad con el
contrato de observación; no cuentan como pruebas funcionales aprobadas.

## Planta e instrumentos representados

La prueba dinámica utiliza un tanque virtual y un modelo externo separado del
programa PLC. El PLC ejecuta el bloque Siemens PID_Compact 2.3 en un OB cíclico
de 100 ms, sobre una CPU virtual 1516-3 PN/DP en TESIS_PLC_SIM. TIA Portal es V18
y el entorno de ejecución es PLCSIM Advanced.

- Medición: transmisor de nivel representado en `AI_Level_Raw`, `%IW4`, señal
  4–20 mA, RAW 0–27648 y escala 0–100 %.
- Actuación: válvula proporcional de llenado representada en `AO_Fill_Command`,
  `%QW4`, señal 4–20 mA, RAW 0–27648 y mando 0–100 %.
- Modelo de tanque: nivel inicial 20 %, aporte máximo 2 puntos porcentuales/s,
  descarga 0,8 puntos/s y período de intercambio 0,1 s.

Estas escalas son supuestos explícitos de la copia de prueba. El mapa físico
activo conserva su confirmación de calibración original. No se verificaron
instrumentos, cableado ni respuesta de una planta física.

El protocolo exige mantener la medición a ±2 puntos de cada consigna durante
10 s antes de 300 s. Las consignas 50, 40 y 60 % cumplieron el criterio. Sus
registros indican cumplimiento a los 10,14, 21,67 y 26,56 s de cada etapa;
no son tiempos de respuesta certificados para una planta real.

Pasaron Stop, fallo del sensor, Start sostenido durante recuperación/rearme,
emergencia y rechazo de consigna fuera del rango por la aplicación. El ensayo
no declaraba un umbral de sobrellenado, por lo que esa comprobación figura
NOT_APPLICABLE; no cuenta como una comprobación superada.

## Funcionamiento del flujo implementado

1. Configurar la plantilla TIA con la CPU y los módulos reales. Seleccionar el
   proyecto de trabajo Normal y un MASTER experimental independiente.
2. Declarar en el mapa el sensor, actuador, dirección, tipo eléctrico, escala,
   unidad y permisos. Un sensor digital de nivel y una electroválvula se
   representan con BOOL; un transmisor continuo y una válvula proporcional
   requieren señales numéricas y sus escalas.
3. Dar el comando. El motor compartido interpreta y resuelve los recursos del
   mapa. La generación rechaza direcciones físicas solapadas. La decisión entre
   secuencia, histéresis, supervisión o PID conserva la intención del comando.
4. Generar, compilar y descargar por el flujo Normal existente. No hay un modo
   de generación distinto para simulación o planta física: las conexiones
   proceden del mapa y el destino pertenece a la configuración de descarga.
5. Abrir Puesta en marcha PID y leer la CPU. Los mandos se habilitan después de
   una lectura verificada. Las escrituras y pruebas automáticas de esta herramienta
   siguen restringidas a PLCSIM; no se ha habilitado escritura física nueva.
6. Para la planta virtual de tanque, iniciar el modelo explícitamente, comprobar
   el sentido del mando y autorizar la sintonización antes de solicitarla.
   El modelo no se inicia al abrir el panel.
7. Cuando el estado sea PENDING_SAVE, detener el controlador y abrir Commissioning
   de su objeto PID en TIA. Iniciar la lectura, usar **Upload PID parameters** y
   guardar el proyecto. En la aplicación, pulsar **Verificar ajustes guardados en
   TIA**. El servicio relee la CPU, verifica identidad, Kp/Ti/Td y propiedad de los
   bloques, crea un respaldo y compara los ajustes offline. La API instalada es
   de solo lectura para esos parámetros; el botón no los escribe automáticamente.
   En la copia comprobada fue necesario pasar offline, activar **Enable manual
   entry** conservando todos los valores recién subidos y guardar otra vez.
   No se sustituyeron los valores subidos por tres ganancias escritas a mano.
   La copia y el proyecto Normal principal tienen comprobaciones positivas
   independientes de guardado y reutilización. La conexión Normal se conservó
   como PN/IE / Siemens PLCSIM Virtual Ethernet Adapter / 1 X1.
8. Tras guardar, regenerar y compilar antes de descargar: el paquete anterior
   se marca como pendiente de recompilación. Una configuración distinta no
   hereda la verificación de los ajustes guardados.

La evaluación aislada crea una copia nueva del MASTER y un paquete inmutable
que conserva fuente, mapa, conexiones, OB, protocolo y modelo. Archiva y verifica
esa copia antes de descargar al PLC virtual. Su veredicto dinámico es adicional
al de los Oracles P01–P12.

## Mapa de supervisión para la ronda nueva

`data/plc_maps/mapa_desarrollo_supervision_nivel.json` es un mapa virtual nuevo,
con digitales disjuntas del banco y emergencia de ensayo explícita. Declara
`Level_PV` como REAL suministrado externamente en `DB_PLC_PRG.Level_PV`.
El proveedor de ensayo debe escribir esa medición; declararla no crea un sensor
ni un modelo de planta. No sustituye al mapa físico ni modifica los resultados
históricos.

El runner admite `--map` para fijar ese contexto antes de interpretar. La
selección, hash y copia del mapa quedan guardados en cada ensayo. Las reglas del
producto siguen siendo las mismas que en Normal; el Oracle no se envía al LLM.

## Entrega y trabajo pendiente para la tesis

La entrega incluye la comprobación del proyecto Normal, el guardado y la
evaluación reales desde la GUI, cinco mapas, la revisión independiente y la
regresión final. La integración comparó los hashes antes de copiar 53 archivos;
los mapas activos y la configuración de conexión no se reemplazaron. El índice
principal conserva sus 496 entradas preparadas; su caché de atributos cambió.

Quedan diecinueve REVIEW de supervisión por explicar o resolver antes de una
campaña final. No cuentan como PASS. La validación física, voz, ruido y una nueva
versión congelada requieren una etapa posterior. Los fallos y resultados previos
se conservan. Las pruebas actuales cubren el tanque y los mapas descritos, no
demuestran funcionamiento universal en cualquier planta o CPU.

Los artefactos de desarrollo citados viven en
`runtime/worktrees/project-closure/`, salvo el flujo Normal `runtime/rnf/f8581f/`
y el resumen `runtime/project_closure_delivery.json`, que están en la carpeta
principal. El respaldo inmediato anterior a la integración está en
`runtime/backups/pre_closure_integration_20261018_230514`; también conserva el
ejecutable anterior del puente. Los archivos TIA previos a la sustitución están
en los archivos Archive del propio flujo Normal, con hash y ZIP comprobados.

El respaldo inicial está en
`runtime/backups/pre_project_closure_20261018_192454_572756` de la carpeta
principal, con producto, configuración, resultados, audios e índice Git
verificados. La validación física y las campañas de voz quedan para una etapa
posterior; no se ha creado un congelamiento nuevo.
