# Corrección de etapas con salidas analógicas

El 19 de octubre de 2026, el comando de llenado al 100 % hasta un nivel del 80 % produjo la pregunta «¿Qué salidas deben activarse en cada etapa y en qué orden?». La respuesta guardada del intérprete ya identificaba el transmisor y la válvula del mapa. No faltaba el orden del proceso.

El modelo había representado la orden dentro de `timed_sequence.steps[].analog_outputs`, con `output`, `value` y `unit`. El resolutor trataba ese objeto completo como una referencia de recurso sin nombre; la validación y la generación de etapas solo contemplaban salidas booleanas. Por ello tampoco reconocían que el sensor gobernaba la transición de la válvula.

La corrección conserva las órdenes numéricas por etapa, sus unidades y sus conexiones al mapa. El mismo estado de secuencia controla la apertura, la transición, la finalización y la cancelación. Al terminar o cancelar se aplica el valor seguro de la salida configurado en el mapa. Las salidas BOOL conservan su tratamiento anterior. Las diferentes etapas exclusivas pueden ordenar distintos valores a la misma salida; propietarios independientes y órdenes duplicadas en una etapa se rechazan. La guarda que impide sustituir una bomba por una válvula también se aplica a estas órdenes.

La pregunta de duración de una etapa incompleta identifica ahora sus salidas analógicas. La política del intérprete explica el formato admitido para evitar órdenes duplicadas o memorias de secuencia activa inventadas.

## Evidencia y límites

La incidencia, su mapa y las respuestas originales se conservan en `runtime/worktrees/project-closure/runtime/analog_sequence_incident_20261019/`. El fixture de regresión conserva la representación funcional capturada; para validarla de nuevo se neutralizan las banderas de aclaración derivadas de la validación anterior. Esto no constituye una nueva respuesta del LLM ni una medición independiente de su exactitud.

Las pruebas ejecutan el SCL generado con SclMachine: apertura, cierre por nivel, Stop, emergencia, espera de un nuevo Start, etapas con valores diferentes, unidades, direcciones alternativas y valor seguro numérico. También rechazan valores inválidos, escritores en conflicto, tipo de actuador incorrecto y calibración pendiente. El informe de entrega de esta corrección registra las pruebas completas, las comprobaciones sobre la carpeta principal y el respaldo individual de los archivos sustituidos.

No se hicieron llamadas nuevas a la API, importación en TIA ni descarga al PLC durante esta corrección. La prueba con el mapa real ya evita la falsa pregunta de etapas, pero mantiene `ANALOG_CONFIGURATION_REQUIRED`: sus canales analógicos siguen sin confirmar. No se cambiaron sus direcciones, escalas ni permisos. Las pruebas con escalas confirmadas utilizan exclusivamente copias de prueba y no acreditan calibración física.

Para repetir desde la GUI, reabra la aplicación y ejecute de nuevo el comando original. Antes de generar con el mapa activo hay que revisar y confirmar la configuración adecuada al entorno de ensayo. Una planta virtual requiere una medición suministrada por el modelo o por las herramientas de IO; la confirmación de sus escalas no acredita el comportamiento de una planta real.

La regresión completa de esta corrección recopiló 2 137 casos en 145 módulos: 2 129 aprobados, siete omitidos y un fallo esperado. Se ejecutaron todos los casos en orden, sin filtros ni reintentos, en grupos consecutivos de diez módulos por proceso para limitar la acumulación de estado Tk. Los 532 archivos de entrada sellados permanecieron intactos. La primera ejecución completa se interrumpió para atender la revisión; se conserva como intento interrumpido y no cuenta como aprobada. Las suites focalizadas se solapan con la completa y no se suman como casos únicos adicionales.

El informe integrado se publica en `runtime/analog_sequence_fix_20261019/delivery.json`; identifica también las pruebas sobre la carpeta principal y la ruta del respaldo individual anterior a la sustitución. La comprobación de la respuesta guardada no sustituye una nueva prueba desde la GUI ni una compilación real en TIA del programa analógico corregido.
