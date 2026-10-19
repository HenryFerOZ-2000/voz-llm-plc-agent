# Motor de producto compartido para Normal y Experimentación

Fecha: 17 de octubre de 2026. Estado: diseño escrito aprobado por Henry para preparar el plan de implementación. El plan y su método de ejecución se revisan por separado; este documento no certifica que el cambio ya esté implementado.

## Resultado esperado

Los nuevos ensayos deben medir el intérprete y generador que utiliza el producto en Modo Normal. Con el mismo comando, mapa, catálogo, reglas, configuración del modelo y contexto previo explícito, ambas rutas deben construir la misma solicitud de interpretación y aplicar las mismas validaciones, resolución de recursos y reglas de generación. No se exige igualdad byte a byte entre respuestas independientes del servicio LLM.

El usuario ya solicitó iniciar esta unificación y conservar el contexto del modo experimental para realizar la campaña después. El alcance inmediato es compartir el motor y verificar su integración; no iniciar una campaña formal, modificar sus resultados anteriores ni ampliar ahora el sistema de sintonización.

## Situación comprobada

- `src/gui.py` llama al parser y al empaquetador desde ambas modalidades, pero pasa `interaction_profile="normal"` únicamente en Normal. Ese perfil activa reglas de composición, resolución funcional, corrección de interpretación y consistencia del control.
- La GUI permite continuar con `INT_UNKNOWN` y primitivas componibles solamente en Normal. Activar el perfil del parser sin corregir este paso seguiría deteniendo programas válidos en Experimentación.
- `trial_io_map.build_experiment_base_map` limpia nombres, alias y descripciones de los canales no LOCKED, y descarta señales internas no LOCKED. Esta transformación fue diseñada para el benchmark histórico; no reproduce automáticamente el mapa de sensores y actuadores que recibe el producto actual, especialmente señales analógicas y DB declaradas.
- Los ensayos usan un working map propio, lo congelan antes de generar y evalúan sobre una copia nueva del MASTER, sin modificar el proyecto Normal. Esta separación es necesaria y se conserva.
- La evaluación diferida congela SCL, variables y bindings del supervisor P01–P12. Eso no constituye un contrato completo para importar y evaluar PID nativo, con sus objetos tecnológicos, OB cíclico, manifiesto y conexiones de proceso.
- El benchmark v3 contiene 32 casos y 96 ensayos TEXT formales históricos. Los P01–P12 son supervisión PID; no se convierten retroactivamente en ensayos de PID_Compact.

## Alternativas

1. Pasar el perfil Normal a Experimentación desde una sola condición de la GUI. Tiene poco coste inicial, pero deja las diferencias de aceptación de programas, mapas y evaluación; no satisface la equivalencia buscada.
2. Establecer una entrada compartida al motor del producto, reutilizando parser, asignador y generador existentes, y separar la operación experimental. Es la opción elegida: permite comprobar equivalencia sin duplicar las reglas ni incorporar el Oracle al intérprete.
3. Mantener dos motores y sincronizar manualmente sus instrucciones. Conserva la divergencia que se quiere eliminar y aumenta el mantenimiento; se descarta.

## Contrato del motor compartido

Una entrada de aplicación común recibirá únicamente datos legítimos de programación: comando efectivo, mapa preparado, catálogo, reglas de seguridad, modo/configuración de interpretación y, cuando corresponda, historial explícito de aclaraciones o programa previo que el usuario solicita modificar.

La implementación reutilizará las reglas actuales de Normal. El nombre interno de compatibilidad `interaction_profile="normal"` podrá mantenerse inicialmente; no debe depender de la pestaña o etiqueta de la GUI. La fachada común debe hacer explícita esa elección para que los dos llamadores nuevos no puedan omitirla accidentalmente.

Se compartirán:

- construcción del contexto e instrucciones, restricciones de control y normalización;
- reintentos limitados de formato e interpretación y fallback configurado;
- validación semántica y aceptación de primitivas componibles, aunque no tengan intención monolítica;
- resolución de recursos, propuestas de asignación, aplicación pura sobre un mapa de trabajo y revalidación;
- construcción de IR, generación SCL y verificaciones del paquete.

No habrá reglas de control alternativas condicionadas por `case_id`, variante, Oracle, fase de evaluación, proyecto TIA o destino PLCSIM/físico. El LLM no recibirá respuestas esperadas, secuencias del Oracle, parámetros esperados por caso ni resultados previos como ayuda para producir el programa.

La operación de creación de un programa completo será la comparación principal. La ampliación de un programa previo conserva su contexto explícito de Normal y no se simulará en el benchmark sin un escenario que declare ese mismo programa de partida.

## Preparación del mapa y efectos persistentes

El motor debe conocer las mismas señales declaradas que el usuario: nombres, alias, funciones, permisos, tipos, direcciones, unidades, calibraciones y conexiones DB. Copiar un mapa a un ensayo no autoriza borrar esa información ni promover calibraciones supuestas a confirmadas.

La ruta nueva de Experimentación utilizará una copia de un mapa de escenario identificado y verificable. Su preparación reutilizará las reglas de propiedad y asignación del producto: se distinguen dispositivos configurados por el operador de asignaciones generadas por un programa anterior. Los canales libres seguirán disponibles; los LOCKED conservarán identidad y función. Si no puede establecerse esa distinción con la metadata disponible, se conservará la configuración y se informará el conflicto, sin liberar canales por suposición.

Los mapas específicos que aportan señales del banco de pruebas se declaran como escenarios de prueba. No se confunden con el banco físico ni se inyectan automáticamente por el contenido de la respuesta deseada. La elección y la transformación del mapa quedan registradas antes de interpretar.

Normal conserva sus transacciones y guardado en el mapa de trabajo del usuario. Experimentación solo escribe su working map durante CREATED/PREPARING y lo congela en IO_RESOLVED; no modifica mapa base, configuración del usuario o resultados anteriores. Las funciones puras de asignación y vinculación serán comunes; los adaptadores de persistencia seguirán separados.

La preparación histórica que limpiaba canales permanece únicamente para compatibilidad de fixtures/herramientas identificadas como históricas. No será la ruta predeterminada de los nuevos ensayos del producto ni un selector para recuperar mejores resultados en una campaña.

## Interacción y medición experimental

Normal puede pedir aclaración y recibir una respuesta. El lote experimental registra la misma pregunta del motor y la deja sin responder, según su protocolo. Esta diferencia de interacción no debe cambiar la primera interpretación, inventar una respuesta o sustituir la lógica solicitada.

Ambos caminos muestran errores de recursos, configuración y comportamiento a partir del mismo resultado del motor. La GUI no bloqueará un programa componible válido solo porque la intención sea INT_UNKNOWN, ni permitirá un resultado inválido por venir de Experimentación.

La identidad/versionado del motor y las políticas de mapa e interacción se registrarán en los ensayos nuevos y en sus artefactos congelados. La ausencia de estos campos en un ensayo histórico significa versión no declarada; no se completa ni se recalcula silenciosamente. La evaluación diferida de un ensayo guardado utiliza sus artefactos congelados y no llama al intérprete actual para regenerarlo.

Los resúmenes mantendrán separadas validez del pipeline semántico, coincidencia con el benchmark, compilación, función y seguridad. Obtener una representación distinta pero funcional no autoriza ajustar el Oracle después de observar resultados. La decisión sobre el alcance y los criterios de una nueva campaña precede a su congelamiento.

## TIA y límite de esta primera entrega

Normal seguirá trabajando sobre el proyecto Normal configurado. Experimentación seguirá utilizando copias nuevas del snapshot MASTER, el workspace corto, archivo zap18 verificado antes de descargar, exclusión de operaciones simultáneas, parada y limpieza del Oracle, y conservación de intentos de infraestructura.

El motor compartido puede generar un paquete PID nativo, pero la ruta experimental no debe tratarlo como un supervisor ni intentar importarlo usando únicamente la fuente SCL genérica. Esta primera entrega identificará el tipo de paquete y comprobará la capacidad del evaluador antes de TIA. Si la evaluación nativa no está soportada por ese recorrido, conservará la generación y registrará explícitamente la capacidad pendiente, sin declarar PASS ni clasificar el rechazo preventivo como fallo funcional del programa.

El soporte experimental completo para PID_Compact requiere una entrega posterior: congelar el paquete nativo íntegro, adaptar su importación aislada desde MASTER, aportar un modelo/medición de prueba identificado y definir un Oracle dinámico de regulación y sintonización. El soporte existente de P01–P12 se mantiene como supervisión. No se ejecutará esa nueva campaña en esta primera entrega.

## Protección de la evidencia y compatibilidad

Los 96 ensayos TEXT previos, lotes, audios, benchmark v3, Oracles y manifiesto FORMAL_V1_1 permanecen intactos. No se reetiquetan como evaluaciones del nuevo motor. El congelamiento histórico seguirá rechazando el árbol modificado; no se relaja su guarda ni se crean resultados FORMAL sin una nueva versión aprobada.

Las llamadas históricas explícitas al parser podrán conservar su contrato para reproducir pruebas guardadas. El acceso de la GUI nueva, tanto Normal como Experimentación, utilizará el motor del producto compartido. No habrá selección automática de una semántica más antigua para hacer pasar un caso.

Se crearán respaldo y copia aislada de trabajo antes de implementar. La integración se limitará a los archivos del cambio, con comprobación de edición concurrente y conservación del índice Git principal.

## Componentes afectados

- Entrada compartida del producto y contratos de resultado/contexto, reutilizando `llm_parser.py`, `semantic_validator.py`, `ir_builder.py` y `project_packager.py`.
- Puntos de entrada, aceptación de programas y presentación de aclaraciones de `gui.py`.
- Preparación y persistencia de mapas en `trial_experiments/trial_io_map.py`, y trazabilidad de la selección del mapa de escenario.
- Identidad del motor en registros/artefactos nuevos y detección de capacidad de evaluación en `deferred_evaluator.py` y módulos de ensayo correspondientes.
- Regresiones de Normal, experimentación, composición, asignación, evidencia diferida, guardas de freeze, audio y paquetes PID.

No se añadirán nuevos factores al diseño experimental, nuevas ganancias PID, adaptación continua del controlador ni comunicación de puesta en marcha con PLC físico en este cambio.

## Criterios de aceptación

1. Con el mismo contexto de producto, los dos puntos de entrada construyen mensajes y configuración equivalentes, incluida su política prioritaria; los metadatos de evaluación no cambian el comando o la semántica.
2. Respuestas reales guardadas o clientes simulados idénticos producen los mismos requisitos, decisiones de aclaración, bindings y errores en ambos recorridos. Se verifican límite finito, histéresis, PID nativo y supervisión solicitada expresamente.
3. Las regresiones reproducen el rechazo anterior de un programa compuesto en Experimentación y comprueban su aceptación posterior cuando es válido. Las restricciones sensor/actuador se aplican igualmente.
4. Un mapa de ensayo del producto conserva dispositivos analógicos, señales DB, funciones y permisos; sus asignaciones no escriben en el mapa del usuario y respetan el congelamiento del ensayo.
5. Una aclaración queda registrada sin respuesta en un lote. No se contesta implícitamente ni cambia el tipo de control en un reintento.
6. La generación PID nativa conserva su identidad. Un evaluador sin capacidad nativa lo detecta antes de abrir TIA y nunca lo degrada a un supervisor, un programa discreto o un PASS de regulación.
7. Reanudar o evaluar un ensayo guardado no modifica sus artefactos ni usa el intérprete nuevo para mejorar un resultado histórico. Se mantienen políticas de reintento, archive, limpieza, audio pareado y separación de fases.
8. Los hashes protegidos de resultados, Oracles, benchmark, freeze, mapas de usuario y configuración no cambian por las pruebas. Se ejecutan las regresiones pertinentes, con informe que distinga pruebas de software, llamadas LLM y comprobaciones TIA/PLCSIM realmente efectuadas.

## Siguiente trabajo tras la integración

Validar programas representativos desde la interfaz hasta PLCSIM; cerrar conservación de ajustes PID y poner a punto el alcance de evaluación nativa. Solo después, revisar el protocolo de la nueva campaña, congelar el software y ejecutar TEXT, VOICE_CLEAN y VOICE_NOISE. La prueba física y la automatización adicional de puesta en marcha se tratarán con criterios propios.
