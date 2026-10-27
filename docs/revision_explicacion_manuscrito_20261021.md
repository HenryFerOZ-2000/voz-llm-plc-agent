# Revisión de explicación y evidencia del manuscrito

Fecha: 21 de octubre de 2026. Estado: **necesita completar documentación antes del cierre**. Revisión de las secciones y de las cifras TEXT completada; verificación visual parcial porque cinco capturas solo existen en Overleaf. Se corrigió el LaTeX y se recompiló una copia local. Las pruebas de voz siguen pendientes y no se incorporaron resultados nuevos.

## Qué se revisó

Se leyó el manuscrito completo y se contrastaron los conteos, denominadores, duraciones, clasificación de resultados y aprobación de los veinte Oracles con los archivos locales. Se verificaron los 57 informes de ejecución respecto de conexión/RUN e invariantes, y la distribución por complejidad. Para el mecanismo de generación se consultaron el código local y la versión c8f6383. Se reutilizó la comprobación bibliográfica anterior; esta revisión no constituye una nueva auditoría de las 29 publicaciones ni una repetición de los ensayos PLC.

Los denominadores de las tablas siguientes son grupos de afirmaciones o secciones del alcance revisado, no porcentajes de exactitud ni declaraciones de revisión universal. Una carencia documental cuenta como pendiente aunque el número correspondiente sea aritméticamente correcto.

| Categoría de calidad del manuscrito | Problemas observados | Evaluación |
|---|---:|---|
| Integridad de las preguntas y demostraciones | 2 / 5 | Faltan la comparación de modalidades y ejemplos verificables de aclaración/ampliación. El artículo identifica que solo TEXT está completo. |
| Claridad metodológica | 3 / 8 | Se precisaron generación local, Oracles, polaridad y tiempos. Quedan fundamento empírico de tolerancias, reinicio de memoria y criterio de complejidad. |
| Presentación y coherencia de figuras | 1 / 4 | Las seis figuras generadas son accesibles y se revisó el PDF local. El destino de una captura interactiva muestra PHYSICAL_PLC; cinco capturas solo pueden comprobarse en la compilación de Overleaf. |

| Categoría de validez analítica | Problemas observados | Evaluación |
|---|---:|---|
| Procedencia y confianza de las fuentes | 1 / 4 | Registros TEXT y aprobaciones disponibles. Falta identificación completa de la fuente del ruido. La bibliografía conserva su comprobación previa. |
| Exactitud de valores | 0 / 5 | Conciliados resultados globales, resultados por etapa, grupos de complejidad, 16 casos con tres PASS y estadísticas de duración. |
| Coherencia entre gráficos y texto | 0 / 4 | Se conservan las figuras previamente contrastadas de etapas, matriz, D01 y D17; no se alteraron datos ni escalas. |
| Disponibilidad de evidencia reproducible | 1 / 3 | Catálogo, Oracles y resumen acompañan el proyecto. Falta resolver acceso al código, trazas e informes completos y describir la reproducción. |
| Coherencia entre secciones | 0 / 5 | Objetivos, cadena de generación, criterios de aceptación, resultados y conclusiones conservan el alcance discreto simulado. |
| Controles de calidad de datos | 0 / 4 | Celdas únicas, denominadores explícitos, etapas no ejecutadas separadas y ensayos interrumpidos excluidos del lote concluido. No se rehízo la auditoría histórica de todos los hashes. |
| Apoyo de las conclusiones | 0 / 4 | Conformidad descriptiva, errores documentados, alcance finito y ausencia de comparación entre modalidades hasta contar con voz. |

## Correcciones incorporadas

- Se explicó que el LLM produce semántica estructurada y que la generación local emplea plantillas parametrizadas y reglas de composición. Se distinguieron estas plantillas de las plantillas JSON de evaluación.
- Se documentó la elaboración asistida con Claude y la aprobación registrada de Henry Ochoa del 12-10-2026. Los veinte Oracles discretos contienen aprobación formal y estado FROZEN. Esto acredita trazabilidad de aprobación; no constituye revisión externa independiente.
- Se añadieron las convenciones activas en TRUE, incluido Stop, la señal de emergencia simulada y el selector de D15.
- Se aclaró el reloj monótono, el origen temporal, la primera muestra tras observar el estado opuesto y la ventana −300/+700 ms. La ventana se identifica como criterio de aceptación, no como precisión del PLC.
- Se identificó el benchmark v3 como catálogo del proyecto y se explicó su revisión previa al lote formal.
- Se precisaron la proximidad funcional entre D03, D04 y D11, el carácter descriptivo de la complejidad y el alcance de generalización.
- Se cerraron las comillas faltantes del comando ilustrado en la interfaz.

## Pendientes priorizados y cómo cerrarlos

1. **Tolerancias y adquisición.** Adjuntar el fundamento original de −300/+700 ms: protocolo, medición previa o decisión experimental documentada. Si no hubo calibración, declararlo con claridad. Resumir intervalos reales de adquisición de los registros, además del período solicitado de 50 ms. Una caracterización nueva debe identificarse como comprobación adicional; no cambiar retrospectivamente los criterios del lote ni atribuir toda desviación al código.
2. **Estado inicial y memoria entre ensayos.** Precisar el procedimiento aplicado al controlador: preparación de la copia TIA, descarga/reinicio, inicialización de DB y tratamiento de retentividad. Una copia de proyecto y precondiciones sobre entradas no prueban por sí solas que toda memoria interna empieza igual. Respaldarlo con el procedimiento y registros existentes; no declarar un reset no acreditado.
3. **Interacción y ampliación.** Conservar un ejemplo de solicitud ambigua, pregunta, respuesta del usuario y programa final, y otro de ampliación antes/después. Registrar comando, semántica, mapa, código, compilación y comportamiento. Presentarlos como demostraciones adicionales, separados de las 60 celdas sin intervención.
4. **Complejidad y alcance.** Recuperar la regla original de asignación LOW/MEDIUM/HIGH, si existe. Si no existe, mantener la explicación descriptiva incorporada, sin inventar una escala después de conocer los resultados. El solapamiento funcional de algunos casos limita interpretar el catálogo como veinte dificultades independientes.
5. **Capturas del destino.** Obtener capturas nuevas de la sesión con PLCSIM Advanced correctamente identificado, compilación, descarga y consulta RUN. Conservar las originales. La etiqueta PHYSICAL_PLC no permite presentar esa captura como prueba inequívoca de descarga simulada; el identificador del destino debe corresponder al utilizado. No confundir la demostración interactiva NOCASE con el ensayo formal D01_V1_TEXT_005.
6. **Revisión de los Oracles.** La aprobación ya está registrada: no es necesario inventar una revisión adicional. Conviene adjuntar una ficha legible por caso o un extracto con requisito, estímulo, respuesta, tolerancia, revisor, fecha y versión. La validación externa por otro especialista fortalecería el trabajo, pero no se presenta como realizada ni como obligación institucional acreditada.
7. **Reproducción y material suplementario.** Añadir un README que relacione cada tabla y figura con sus archivos y comandos de cálculo, versiones y requisitos del entorno. Elegir repositorio o condiciones de acceso, licencia y consentimiento de los audios. Distinguir metadatos históricos de los Oracles sobre limitaciones antiguas del generador de las capacidades de V4; conservar las copias congeladas originales.
8. **Cierre documental.** Confirmar ciudad, correspondencia, financiación, roles CRediT, conflictos de interés y agradecimientos. Identificar título, autor y página del ruido, y documentar micrófono, participantes, ambiente y consentimiento. Cuando exista una revista o formato institucional de destino, revisar su plantilla y declaraciones específicas.

## Qué no hace falta añadir por obligación

No se necesita aumentar el número de capturas si no aportan evidencia nueva. Una comparación con programación manual, una ablación sin LLM o pruebas en hardware físico ampliarían las preguntas del trabajo; no son requisitos derivados de las conclusiones actuales. Evitar afirmar ahorro de tiempo, superioridad frente a otros métodos, confiabilidad industrial general o seguridad certificada sin un diseño que los evalúe.

## Evidencia de esta revisión

- `runtime/article_explanation_review_20261021/evidence_review.json`: conciliación de cifras, duraciones y aprobación de Oracles.
- `runtime/article_explanation_review_20261021/reports_verification.json`: informes ejecutados, invariantes y grupos de complejidad.
- `runtime/article_explanation_review_20261021/final_verification.json`: compilación, referencias cruzadas, figuras y conservación de título/objetivos.
- Fuentes: `results/batches/TEXT_FORMAL_20261021_001/batch_manifest.json`, informes de `results/experiments`, `data/experiment_oracles/D01.json` a `D20.json`, `docs/experimental_interface_v3.md`, `docs/benchmark_v3_changelog.md` y código de generación.

La compilación local omite las cinco capturas que solo están en Overleaf mediante las condiciones ya presentes en el documento. Por ello no acredita la distribución de páginas final con esas cinco imágenes incorporadas.
