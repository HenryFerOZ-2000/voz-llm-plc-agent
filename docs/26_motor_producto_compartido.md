# Motor compartido para Normal y nuevos ensayos

Desde esta entrega, ambas entradas de la GUI usan `src/product_engine.py`: interpretación con las reglas vigentes del producto, resolución de recursos y generación. El nombre interno de compatibilidad del perfil es `normal`; ya no depende del modo visual. Identidad: `PRODUCT_SHARED_V1`.

El intérprete recibe el comando, mapa, catálogo y reglas de seguridad. No recibe secuencias del Oracle, respuestas esperadas ni resultados anteriores. Extender un programa y responder aclaraciones siguen siendo interacciones explícitas de Normal. En lotes las aclaraciones se registran sin respuesta. Los ensayos individuales conservan su interacción y registran esa política por separado.

## Mapas

Los nuevos ensayos de la GUI crean una copia con política `PRODUCT_DECLARED_V1`. Conserva dispositivos digitales, analógicos y señales DB, sus nombres, funciones, permisos y configuración. Solo se liberan asignaciones AUTO con propietario comprobado del programa anterior. Un dato sin procedencia suficiente se conserva. EXTEND_PROGRAM conserva las asignaciones.

Esa conservación continúa al guardar el programa de Normal: utilizar un dispositivo declarado no lo convierte en una asignación AUTO del programa. Solo se registra propiedad para una asignación nueva comprobada o se transfiere la propiedad AUTO del programa anterior identificado.

Normal mantiene sus transacciones en el mapa del usuario. Experimentación asigna exclusivamente en su working map y congela su snapshot antes de generar. Las llamadas históricas explícitas que usan la política `LEGACY_CLEARED_V1` siguen disponibles para reproducir software anterior; no son la entrada de los ensayos nuevos de la GUI.

## Evidencia y compatibilidad

Un ensayo nuevo congela `product_contract.json`, metadata del generador y hashes adicionales en `integrity_manifest.json`. El contrato identifica motor, política de mapa, interacción y clase del paquete. Evaluar un ensayo guardado verifica esa evidencia y utiliza su programa congelado: no vuelve a interpretar, asignar ni generar. Abrir un ensayo histórico no crea identidad retrospectiva.

Las clases son `DISCRETE_OR_SUPERVISORY` y `NATIVE_PID`. La segunda se reconoce por la fuente y los manifiestos reales; un identificador P01–P12 no basta. Una identidad incompleta o alterada bloquea la integridad.

## Límite de esta entrega

La generación PID nativa continúa disponible en el producto. Su evaluación experimental diferida se detiene antes de TIA con `NATIVE_PID_EXPERIMENT_EVALUATION_UNSUPPORTED`: generación SUCCESS, evaluación PENDING, sin intento ni veredicto funcional. El lote registra NOT_EVALUABLE y conserva el motivo. El encabezado indica «Evaluación PID nativa pendiente de soporte».

El motivo queda persistido al finalizar la generación nueva, incluso en un ensayo individual que nunca llega a iniciar el evaluador. Cerrar y abrir su resumen no pierde esa información.

Esto no impide el flujo Normal del PID ni convierte los casos históricos de supervisión en reguladores nativos. Falta incorporar al evaluador el paquete nativo completo, su importación aislada, una planta/medición identificada y un Oracle dinámico apropiado. Congelar los manifiestos en esta entrega conserva identidad; no constituye un bundle portátil certificado.

Los resultados anteriores y FORMAL_V1_1 permanecen históricos. Su guarda sigue rechazando el árbol mejorado. Antes de otra campaña se deben validar programas representativos en PLCSIM, cerrar el alcance del PID, aprobar el protocolo y crear un nuevo congelamiento. Las regresiones de esta entrega son pruebas de software y reproducción offline; no acreditan una nueva ejecución TIA, PLCSIM o planta física.
