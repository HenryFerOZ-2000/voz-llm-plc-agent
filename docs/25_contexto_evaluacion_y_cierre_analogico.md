# Contexto de evaluación y cierre del control analógico

Fecha de referencia: 17 de octubre de 2026. Memoria para continuar el trabajo de Henry y retomar las pruebas sin confundir versiones, perfiles de interpretación o alcance PID. Los conteos siguientes describen los archivos locales revisados en esa fecha.

## Objetivo y restricciones del proyecto

Transformar comandos de texto o voz en programas PLC generados, compilados y ejecutables, utilizando los dispositivos y permisos del mapa IO. Las direcciones y características eléctricas proceden del mapa; el hardware, módulos y red se preparan previamente en una plantilla TIA.

El comando debe expresar el comportamiento del proceso. No debe necesitar una elección de lógica diferente por usar PLCSIM o un PLC físico. Una planta simulada es un proveedor explícito de medición, independiente del controlador. No se inventan sensores, actuadores, calibraciones, ganancias sintonizadas ni una planta por ausencia de analógicas.

La plataforma probada es TIA V18, S7-1500/CPU 1516-3 PN/DP y PLCSIM Advanced V5, instancia TESIS_PLC_SIM. La conexión de descarga habitual ya funcionaba; no cambiar su adaptador basándose únicamente en una prueba aislada. El banco de trabajo usa digitales I16.x/Q8.x. El ejemplo de tanque declara AI_Level_Raw en IW4 y AO_Fill_Command en QW4, 4–20 mA y 0–100 %, con válvula proporcional de llenado. Los rangos supuestos no equivalen a calibración física confirmada.

## Diseño experimental vigente e histórico

El benchmark vigente es v3: 20 casos discretos D01–D20 y 12 casos de supervisión PID P01–P12. Cada caso tiene tres variantes lingüísticas V1/V2/V3 y tres modalidades TEXT/VOICE_CLEAN/VOICE_NOISE: 288 celdas, un ensayo formal por celda.

Los factores incluyen caso, dominio, complejidad, variante y modalidad de entrada. Reglas/LLM/Híbrido no son grupos experimentales del diseño vigente. El benchmark v2 y los ensayos DEVELOPMENT/BASELINE son históricos y se conservan separados de las estadísticas formales v3.

Referencias: [diseño experimental](experimental_design_v2.md), [protocolo formal v1](formal_evaluation_protocol_v1.md), [extensión de audio v1.1](formal_evaluation_protocol_v1_1.md) e [interfaz del evaluador v3](experimental_interface_v3.md). Algunos documentos anteriores, especialmente la guía inicial de lotes, describen limitaciones del Runtime PID ya superadas; contrastarlos con código y evidencia de los ensayos actuales.

## Ejecución y conservación de un ensayo

1. Seleccionar caso, variante, modalidad y fase en Experimentación. TEXT utiliza el comando exacto del benchmark. Voz utiliza el audio congelado y el ASR sin corrección humana en FORMAL.
2. Ejecutar interpretación LLM, asignación de IO, representación intermedia, generación SCL y validaciones. El mapa de trabajo se resuelve y congela por ensayo.
3. Restaurar una copia nueva del MASTER experimental en un workspace propio. Importar, compilar, crear y verificar el archivo zap18.
4. Descargar exclusivamente a PLCSIM, comprobar RUN y ejecutar el Oracle: secuencia de estímulos, observación de respuestas, invariantes y limpieza.
5. Persistir resultados por etapa, trazas, tiempos, mapas, código y hashes. El siguiente ensayo comienza después de finalizar y guardar el anterior.

El proyecto Normal es tia_projects/S71500_Prueba/S71500_Prueba.ap18. El MASTER experimental S71500_MASTER es independiente y no se modifica durante los ensayos. Los mapas experimentales se seleccionan por capacidad según config/experiment_maps.json; no se toma automáticamente el mapa de trabajo de Modo Normal.

Un resultado semántico válido para el esquema y el generador no demuestra coincidencia con el benchmark: semantic_pipeline_success y semantic_benchmark_match son mediciones distintas. Las etapas no ejecutadas tampoco cuentan como aprobadas.

PASS, FAIL y REVIEW se conservan. Un fallo funcional no se repite para obtener PASS. Un INFRASTRUCTURE_ERROR pausa el lote y permite un reintento técnico explícito con motivo; el intento anterior permanece. Las aclaraciones del lote quedan sin responder. La reanudación contrasta el manifiesto con trial.json.

La evidencia vive en results/experiments, results/development_validation_v2 y results/batches según fase. scripts/audit_trial_persistence.py audita persistencia sin ejecutar nuevamente el programa. scripts/backup_results.py respalda resultados formales, lotes y corpus formal con manifiesto SHA-256 y permite verificar la copia; no sustituye un respaldo del código ni incluye por defecto todas las carpetas de desarrollo.

## Resultados locales comprobados

| Lote formal TEXT del 13 de octubre | Total | PASS | FAIL | REVIEW |
| --- | ---: | ---: | ---: | ---: |
| TEXT_FORMAL_20261013_001, D01–D20 | 60 | 52 | 8 | 0 |
| TEXT_FORMAL_20261013_002, P01–P12 | 36 | 24 | 10 | 2 |
| Total | 96 | 76 | 18 | 2 |

Los 96 trial.json son FORMAL_TRIAL, benchmark v3, modalidad TEXT y celdas únicas. Sus veredictos coinciden con las 96 filas de ambos lotes. Registran el commit 81c6bd5621c021d61418e907e2f3798f64c4b792 y el modelo gpt-5.6-terra. Esta revisión comprobó conteos y correspondencia de veredictos; no repitió los ensayos ni verificó exhaustivamente todos los hashes de su evidencia.

Las categorías registradas son 76 SUCCESS, 5 CODEGEN_FAILURE, 5 SEMANTIC_FAILURE, 7 COMPILE_FAILURE, 1 VERIFICATION_FAILURE y 2 REVIEW. Los dos lotes no registran INFRASTRUCTURE_ERROR. Estos resultados pertenecen a su versión histórica; no se atribuyen a las mejoras posteriores.

No se encontraron ensayos formales VOICE_CLEAN ni VOICE_NOISE en results/experiments, ni corpus en results/formal_audio. Sí existen pilotos y comprobaciones de captura/mezcla en results/development_audio. Un piloto de audio no equivale a una celda formal ejecutada de extremo a extremo.

## Audio pareado y congelamiento

VOICE_CLEAN requiere una locución humana por caso/variante, PCM16 mono a 16 kHz. VOICE_NOISE se deriva del mismo clean con ruido maestro industrial, SNR de 10 dB y tolerancia ±0,25 dB. El algoritmo es PAIRED_ACTIVE_RMS_SNR_V1, con energía de voz activa y offset determinista. No se regraba para la condición noisy ni se ajusta la SNR después de observar resultados. Una pareja utilizada queda inmutable y los reintentos técnicos reutilizan el mismo audio.

El manifiesto data/software_freeze_manifest.json identifica FORMAL_V1_1, benchmark v3, 342 archivos y 32 Oracles. Al revisar el árbol de trabajo mejorado, validate_freeze devolvió 25 FROZEN_FILE_MODIFIED. No se alteró el manifiesto ni se intentó levantar esa guarda. Una campaña sobre la nueva versión exige su propio congelamiento y una identidad que permita separar resultados anteriores y nuevos.

## Estado analógico y sintonización

El soporte nativo actual cubre un lazo de nivel con acción de llenado o vaciado, actuador proporcional 0–100 %, PID_Compact 2.3 y OB cíclico de 100 ms. Admite medición/mando INT por canales hardware declarados y señales REAL de DB declaradas en el mapa; la medición DB exige calidad BOOL. No se ha demostrado compatibilidad con cualquier planta analógica o múltiples lazos.

Las pruebas P01–P12 evalúan supervisión y variables internas del DB (Level_PV, Level_SP, PID_Enable y estados); no evalúan por sí mismas regulación analógica ni sintonización de PID_Compact. La evidencia de desarrollo nativo está separada en runtime/pid_io_unification_delivery.json y docs/24_pid_unificado_desde_mapa.md: se registraron pruebas PLCSIM de interfaces IW/QW y DB, presintonización, consignas y paradas. La etiqueta hardware de esa entrega describe la representación de IO probada en PLCSIM, no una prueba en planta física.

El software ya expone CmdPretune y CmdFinetune, botones Presintonizar/Sintonización fina, lectura de Kp/Ti/Td y estados. El panel exige autorización de sintonización, marcha, sensor válido y ausencia de fallo. El código generado no inicia ajuste solo por descargar o arrancar la CPU. La validación dinámica registrada comprobó presintonización; no implica haber validado todas las modalidades de ajuste fino ni todas las plantas.

El panel de puesta en marcha actual exige target_type PLCSIM_ADVANCED en src/pid_commissioning.py. La puesta en marcha desde ese panel en PLC físico es pendiente. Los parámetros aprendidos online no se transfieren automáticamente al proyecto TIA; la conservación offline/online debe comprobarse antes de nuevas descargas. Véase también la explicación de presintonización y ajuste fino de [Siemens](https://cache.industry.siemens.com/dl/files/707/79047707/att_915339/v2/79047707_PidCompactV2_2_DOC_V2_0_1_en.pdf), secciones 5.3.1 y 5.3.2; esa referencia V2.2 explica el mecanismo, mientras el proyecto usa y verifica V2.3 en su entorno instalado.

El documento inicial docs/superpowers/specs/2026-10-16-pid-tanque-s7-1500-design.md contiene decisiones históricas sobre modos simulación/físico y parámetros de demostración. Para el funcionamiento vigente, consultar docs/24_pid_unificado_desde_mapa.md y la entrega de unificación; no restaurar las decisiones antiguas por tomar aquel diseño inicial como descripción actual.

## Última corrección del intérprete

runtime/normal_control_interpretation_delivery.json registra la corrección integrada desde el commit aislado 13a475c0d4ff07c30305b89c5ec33cb2d35fd3f8: distinción de límite finito, histéresis, PID nuevo y supervisión; consistencia sensor/actuador; conservación del comportamiento en reintentos y corrección de formato JSON.

Evidencia: 253 regresiones en el worktree, 81 comprobaciones después de integrar y ocho casos reales con API clasificados según lo esperado. Hubo bloqueos por configuración y solicitudes de aclaración; no fueron ocho ejecuciones completas. Las comprobaciones locales de llenado e histéresis pasaron. Esta última entrega no volvió a compilar en TIA ni descargar a PLCSIM. Una medida de duración del harness tuvo una variable sombreada y está expresamente excluida de conclusiones temporales en la entrega.

## Orientación solicitada para la siguiente fase

Henry quiere que la campaña nueva evalúe el producto mejorado que utiliza en Modo Normal. Actualmente src/gui.py pasa interaction_profile normal solo en ese modo; Experimentación conserva el perfil histórico. Por tanto, cambiar únicamente el freeze no incorpora automáticamente todas las reglas nuevas a la evaluación.

La propuesta es compartir el motor de interpretación, validación, resolución de IO y generación para los ensayos nuevos y Modo Normal. Se conservarían como diferencias operativas el proyecto TIA aislado, los estímulos del Oracle, la evidencia, los lotes y la política experimental de aclaraciones sin respuesta. El programa no debe recibir respuestas esperadas del Oracle como ayuda privilegiada para interpretar; las convenciones necesarias deben constituir un contrato de interfaz documentado y trazable.

Antes de modificar ese comportamiento debe concretarse y aprobarse el diseño de la nueva campaña. Los ensayos y protocolos anteriores permanecen históricos; P01–P12 no se reinterpretan retroactivamente como PID nativo. El alcance del PID nativo puede incorporarse como bloque experimental adicional con criterios propios, o mediante una revisión explícita del benchmark antes de congelar la nueva campaña.

Prioridad propuesta: unificar la ruta que se evaluará, validar extremo a extremo control por límite/histéresis/PID nativo, cerrar conservación de ajustes y puesta en marcha dentro del alcance, y después congelar la versión y ejecutar TEXT/VOICE_CLEAN/VOICE_NOISE. La automatización adicional aconsejada es un asistente de sintonización supervisado y verificable; no ajustar continuamente ni inventar ganancias a partir del mapa IO.

La prueba física se realizará otro día, según disponibilidad del usuario y requisitos del tutor. Hasta entonces, las conclusiones sobre esa parte se limitan a PLCSIM y al modelo de proceso utilizado.

## Continuación del trabajo de unificación (contexto previo a la implementación)

Henry solicitó iniciar la unificación y estudiar la operación experimental antes de la próxima campaña. Aprobó el [diseño escrito del motor compartido](superpowers/specs/2026-10-17-motor-producto-compartido-design.md) para preparar el [plan de implementación](superpowers/plans/2026-10-17-motor-producto-compartido.md), que queda pendiente de revisión y método de ejecución. Esta revisión confirmó además la limpieza de nombres/alias de mapas no LOCKED y el bloqueo de programas componibles fuera de Normal; cambiar solo el perfil del parser no resuelve todas las diferencias. El diseño distingue la integración inmediata del motor de la futura evaluación completa de PID nativo; todavía no hay cambios de comportamiento de esta unificación.

Al preparar el plan, el mapa activo `data/plc_maps/mapa_banco_fisico_working.json` tenía un hash distinto del registrado en la entrega anterior del intérprete y fecha de modificación 2026-10-17T18:50:42. El trabajo de planificación no lo modificó ni lo restauró. Antes de implementar se debe respaldar su estado vigente; no usar el hash antiguo como base para sobrescribir ediciones recientes. Los archivos de producto de aquella entrega, el índice principal y las configuraciones de conexión/modelo seguían coincidiendo con sus hashes registrados.

## Actualización de cierre del 18 de octubre de 2026

El plan de cierre fue aprobado y se ejecuta en una copia aislada. La primera
ronda LLM de 36 variantes conservó 18 generaciones correctas y 18 bloqueadas.
La evaluación dinámica adicional del PID nativo pasó en PLCSIM, con archivo
previo verificado, pruebas de regulación, parada/recuperación y limpieza; el
MASTER quedó intacto. La segunda ronda conservó 26 generaciones correctas
y 10 fallidas. La reproducción local genera 36 programas y su cobertura de
ejecución conserva 17 PASS y 19 REVIEW. Los cinco mapas alternativos pasaron.
El guardado/reuso real de ajustes todavía no se declara completado. Véase la evidencia y los pendientes en
[Validación de PID y adaptación](30_cierre_validacion_pid_y_adaptacion.md).

## Puntos de entrada y reglas operativas de Experimentación

- `gui.run_complete_trial` es la entrada oficial individual y la que reutiliza el lote. Comprueba disponibilidad de operaciones y entorno, obtiene el texto del benchmark o el estímulo de audio, crea el ensayo y ejecuta generación/evaluación. El lote programa el siguiente solo después del callback y la persistencia; el botón individual ejecuta un ensayo.
- `gui.start_trial` arma la identidad y los registros, selecciona la configuración de interpretación experimental y prepara el working map. FORMAL comprueba la guarda de congelamiento antes de generar. El identificador del participante forma parte de la metadata; la validación formal de voz usa el formato de speaker definido por su protocolo.
- `gui._load_runtime_configuration` lee el working map cuando existe un ensayo activo. Para benchmark v2/v3, `allowed_variables` de los perfiles es metadata histórica, no una whitelist. La restricción por lista pertenece solo a benchmark v1. La descripción inicial de `docs/20_modo_experimentacion.md` no debe tomarse como el contrato actual en esos detalles.
- `trial_io_map` permite mutaciones automáticas solo durante CREATED/PREPARING. Después de IO_RESOLVED, el snapshot y sus bindings permanecen congelados. La preparación histórica libera canales no LOCKED y borra nombres/alias; las señales internas no LOCKED se descartan. Debe revisarse expresamente para los dispositivos y DB del producto actual.
- `deferred_evaluator.finalize_generation` copia fuente y variables del paquete, congela los bindings de proceso presentes, genera el informe y manifiesto, y deja la evaluación PENDING. Un ensayo generado se puede evaluar más tarde sin volver a interpretar su comando.
- La evaluación trabaja con Retrieve del MASTER, workspace corto por intento y handshake de archivo: compilar/archivar, copiar y verificar zap18, y solo entonces habilitar descarga. No reemplazar este flujo por la descarga de Modo Normal ni por un segundo proyecto recuperado de otra fuente.
- `text_batch.py` es el motor actual de lotes TEXT y voz pareada. `batch_runner.py` conserva el recorrido inmediato histórico del baseline y no debe usarse como sustituto del flujo actual. Las reglas de reanudación, pausa por infraestructura e inmutabilidad de ensayos se aplican en el motor actual.
- La evaluación PID nativa requiere el paquete completo y su contrato tecnológico; `program.scl` y los bindings del supervisor no bastan. La unificación no autoriza a borrar este límite ni a convertir una generación válida en una ejecución validada sin evidencia.

## Implementación del motor compartido, 17 de octubre de 2026

Henry aprobó el plan y su ejecución en esta sesión. La rama aislada `feat/shared-product-engine` incorpora `PRODUCT_SHARED_V1` para ambas entradas de la GUI, preparación `PRODUCT_DECLARED_V1`, asignación compartida, aceptación de composiciones válidas y evidencia nueva con identidad congelada. El [documento operativo](26_motor_producto_compartido.md) sustituye las descripciones previas de divergencia para los ensayos nuevos; los recorridos históricos explícitos permanecen disponibles.

La generación experimental PID nativa queda identificada y conservada, con evaluación PENDING por `NATIVE_PID_EXPERIMENT_EVALUATION_UNSUPPORTED` antes de TIA. No consume intento ni produce un veredicto funcional. Los casos P01–P12 mantienen su significado histórico de supervisión. Los lotes no responden aclaraciones; los ensayos individuales conservan interacción explícita y registran su política.

La reproducción offline de los ocho casos guardados pasó por ambos adaptadores de la GUI con respuestas y mapas iguales. El informe nuevo está en `runtime/shared_product_engine_offline_replay/summary.json`; no se modificó la auditoría anterior ni se usó la API. Cinco pares generables se compararon por SCL exacto. Este cambio no acredita nuevas compilaciones TIA ni ejecuciones PLCSIM. La entrega verificable, respaldo, revisión y suites se registran en `runtime/shared_product_engine_delivery.json` una vez completada la integración.

Verificación final: 1.904 pruebas aprobadas, 7 omitidas y un fallo esperado en la suite completa, sin fallos inesperados; 113 pruebas aprobadas después de integrar en la carpeta principal. No sumar ambos conteos como pruebas únicas. La revisión independiente encontró dos problemas importantes, reproducidos y corregidos: conservación de procedencia durante el commit de Normal y persistencia del motivo pendiente en ensayos PID individuales. No quedaron hallazgos menores diferidos.

Se verificaron el CRC del respaldo y los 3.439 hashes protegidos, incluido el índice Git principal. El congelamiento histórico conserva su manifiesto y sigue bloqueando el software mejorado; no se creó un freeze ni campaña FORMAL nueva. Próximas etapas: validación representativa en PLCSIM, cerrar el alcance de evaluación PID nativa y de conservación/sintonización de ajustes, revisar protocolo, congelar la versión y ejecutar la nueva campaña TEXT/VOICE_CLEAN/VOICE_NOISE.

## Lazo cerrado comprobado, 18 de octubre de 2026

La prueba actual de presintonización y regulación se completó en TESIS_PLC_SIM con el programa PID ya cargado en S71500_Prueba. Las consignas 50/40/60 % cumplieron ±2 puntos durante 10 s antes de 300 s; pasaron las cinco comprobaciones de seguridad declaradas y la parada/restauración final. La evidencia actual y sus límites están en [28_pid_lazo_cerrado_plcsim.md](28_pid_lazo_cerrado_plcsim.md) y runtime/pid_closed_loop_delivery.json. Esto amplía la auditoría anterior, que solo comprobó transporte, manual y paradas. Los parámetros aprendidos siguen online: falta sincronizarlos con TIA y verificar su conservación al regenerar/descargar. No se confirmó calibración física ni se inició una campaña FORMAL.

## Conservación de sintonización comprobada, 18 de octubre de 2026

Se completó el guardado inicial de parámetros desde TIA y su confirmación en la plantilla. El mismo PID se regeneró, compiló y descargó a TESIS_PLC_SIM conservando Kp/Ti/Td y ParametersConfirmed. La repetición de consignas 50/40/60 % pasó sin otra sintonización, con parada/restauración verificadas. Una calibración diferente fue rechazada en una copia TIA aislada, sin descarga. El flujo, la intervención inicial en TIA y sus límites están en [29_persistencia_sintonizacion_pid.md](29_persistencia_sintonizacion_pid.md); evidencia estable: runtime/pid_persistence_delivery.json. Este resultado cierra la conservación del mismo lazo ensayado; no acredita todas las transiciones, una planta física ni la evaluación experimental nativa aún pendiente. No se modificó el código del producto ni se creó un freeze/campaña FORMAL.
