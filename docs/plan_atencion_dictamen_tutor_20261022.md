> Actualización al 24-10-2026: las 180 celdas están ejecutadas y el manuscrito completo se actualizó. La revisión documental y estadística está cerrada, con 162 PASS, 17 FAIL y un REVIEW conservados. Estado vigente: [cierre de correcciones](cierre_correcciones_tutor_20261024.md). El texto siguiente conserva el estado histórico del 22-10.

# Atención del dictamen del tutor

Fecha de revisión: 22 de octubre de 2026.

El dictamen respalda la arquitectura y su trazabilidad, pero condiciona el cierre de la tesis a completar la evaluación de voz, relacionar objetivos y evidencia, y fortalecer la comprobación de los Oracles. Estas observaciones requieren trabajo experimental además de ajustes del manuscrito. El estado actual sigue siendo 60 ensayos TEXT, 57 compilados y 55 conformes. No se ejecutaron ensayos nuevos ni se modificaron el código congelado, los datos o el manuscrito durante esta lectura del dictamen.

## Fuentes y alcance

Se leyó el contenido completo de `C:/Users/DOCENTE/Downloads/Dictamen_consolidado_tesis_Henry_Ochoa.docx`, incluidos los párrafos de su matriz. No contiene comentarios de revisión en `word/comments.xml`. El documento identifica como versión evaluada `Articulo_Henry_Ochoa_Elsevier.pdf`, de 18 páginas y fecha 22-10-2026; ese PDF no se proporcionó en esta solicitud.

Se contrastó el dictamen con el `main.tex` y `referencias.bib` locales, los registros de la revisión anterior, el código de clasificación de infraestructura y los controles técnicos de los Oracles. La compilación local verificada tiene 16 páginas físicas, incluyendo highlights, y omite mediante condiciones las cinco capturas disponibles solo en Overleaf. Por ello no permite descartar la acumulación de figuras que observó el tutor en la versión que recibió.

## Matriz de atención

| Observación | Estado comprobado | Acción para cerrarla |
|---|---|---|
| Ejecutar 60 celdas de voz limpia y 60 con ruido | Pendiente en los resultados del manuscrito | Confirmar grabaciones y consentimiento; completar las parejas de audio y verificar su integridad; ejecutar el protocolo con la versión congelada. Registrar WER, intención, parámetros, compilación y comportamiento por modalidad. |
| Responder la comparación entre modalidades | Parcial: solo TEXT | Conservar la pregunta de investigación que incluye voz. Comparar las mismas parejas caso–variante y actualizar resumen, resultados, discusión y conclusiones después de conciliar las 180 celdas. |
| Mostrar una cadena de extremo a extremo | Hay ejemplos de generación, integración y trazas; falta la comparación completa con voz | Preparar un caso en las tres modalidades con entrada, transcripción, interpretación, asignación I/O, SCL y respuesta adquirida. D05 es una posibilidad sugerida por el tutor. |
| Tabla de las 180 celdas | Pendiente como tabla consolidada | Incluir ID de ensayo, caso, variante, modalidad, audio y hash, transcripción, WER, intención, parámetros, hash SCL, compilación, descarga/RUN y veredicto. En TEXT, audio y WER son «no aplica»; en detenciones previas, el SCL puede estar ausente y debe constar el motivo. |
| Separar incidencias de conexión de D11–V1 y D11–V2 | Los dos errores y el respaldo ya están descritos; infraestructura figura OK | Mantener los resultados originales. Añadir clasificación explícita de incidencia remota y procedencia semántica. Si se hacen reintentos técnicos, conservar sus nuevos ID y vincularlos con los intentos originales sin sobrescribirlos. |
| Corregir el indicador de infraestructura | La función actual devuelve OK cuando el resultado terminal no es INFRASTRUCTURE_ERROR | Diferenciar «evaluación completada» de «sin incidencias de transporte». La corrección del software debe versionarse y someterse a los controles del congelamiento; puede elaborarse antes un informe derivado que exponga las incidencias conservando los archivos originales. |
| Validar los Oracles con programas de referencia | Existen aprobación humana, controles positivos/negativos y pruebas con simulación interna; falta acreditar el control solicitado en PLCSIM con referencia revisada por experto | Empezar por D17. Conservar requisito, programa de referencia, autor/revisor, versión, compilación, trazas, intervalos reales de adquisición y resultado de cada expectativa. Extender a los veinte Oracles discretos. |
| Añadir intervalos de confianza | No están incorporados | El Wilson binomial al 95 % calculado para 55/60 es 81,93–96,39 %. Explicitar su supuesto de independencia y el carácter orientativo ante variantes agrupadas por caso. No convertirlo en prueba de confiabilidad industrial ni de repetibilidad del LLM. |
| Tabla explícita de requisitos funcionales y operativos para OE1 | Hay explicación distribuida, sin tabla de cierre | Relacionar cada requisito con su implementación, evidencia y resultado: captura/transcripción, interpretación, aclaración, recursos I/O, generación, verificación, integración, ejecución y trazabilidad. Añadir las condiciones operativas efectivamente comprobadas. |
| Matriz objetivo–evidencia–resultado | No está incorporada | Añadir una matriz con OE1–OE4 y la pregunta de investigación, usando referencias LaTeX y un estado que refleje la evidencia disponible. Actualizarla al cerrar voz y la validación del instrumento. |
| Cuatro apariciones de citas como signo de interrogación | Las tres entradas asociadas existen en el .bib local; no hay claves citadas sin resolver | Sincronizar el .bib local completo con Overleaf y recompilar desde cero. Comprobar el PDF que se entregue al tutor, porque el dictamen puede corresponder a archivos distintos o una compilación anterior. |
| Completar los campos pendientes | Continúan pendientes | Confirmar ciudad, financiación, correspondencia/correo, roles CRediT, intereses, acceso a datos y agradecimientos. Los hechos de autoría no se completan por inferencia. |
| Figuras 4–10 después de las referencias | No reproducible con la compilación local incompleta | Revisar el PDF de Overleaf con todas las capturas. Reducir tamaños excesivos, revisar agrupaciones y ubicación de floats, y comprobar que cada figura aparezca cerca de su discusión y sea legible. No forzar todas con [H]. |
| Unificar «modelos de lenguaje de gran tamaño» | El cuerpo usa esa denominación; título y objetivo general conservan el texto aprobado «largo» | Proponer la corrección terminológica y comprobar la regla institucional para modificar el título y los objetivos aprobados. La observación del documento no sustituye por sí sola la decisión del autor sobre esos textos. |
| Mover identificadores internos al anexo y reducir redacción defensiva | Siguen presentes, aunque se mejoró parte de la explicación | Conservar en el cuerpo el procedimiento y sus condiciones; trasladar commits, hashes, etiquetas y nombres de políticas a una tabla de reproducibilidad en el anexo. Redactar afirmaciones directas y reunir los límites donde afectan la interpretación. |
| Ampliar la comparación bibliográfica | La tabla actual tiene cuatro antecedentes y la propuesta | Añadir Koziolek 2023, Tran 2024, AutoPLC y PLCWorld usando información respaldada por sus fuentes. Mantener criterios comparables de generación, entorno y comprobación. |

## Precisiones metodológicas para atender las correcciones

### Conservar los fallos y separar los análisis

En la configuración ensayada, las reglas de respaldo pertenecen a la arquitectura. Los dos fallos de D11 sí describen su comportamiento ante una incidencia de conexión. La interpretación del dictamen de que «no miden la arquitectura» debe matizarse: permiten evaluar la arquitectura con respaldo, aunque no describen una interpretación remota satisfactoria del LLM.

El resultado principal histórico permanece en 55/60. Se puede añadir el subgrupo de ensayos que utilizó efectivamente el LLM y el subgrupo de respaldo. Eso no equivale a haber ensayado una arquitectura con respaldo deshabilitado. Los reintentos técnicos aportan información adicional y deben presentarse con su política de selección y sus registros originales; reemplazar únicamente resultados fallidos introduciría un sesgo.

Corregir diagnósticos y continuar ensayos con «la misma versión congelada» exige cuidar la identidad del software. No se deben modificar los archivos sellados y conservar el mismo identificador como si nada hubiera cambiado. La decisión sobre una revisión de instrumentación o una nueva versión debe quedar documentada antes de ejecutar los ensayos afectados.

### Diferenciar tres niveles de comprobación del Oracle

La revisión manual y la aprobación formal ya están registradas. Además, `tests/test_phase3b_oracles.py` contiene controles positivos y negativos mediante un simulador interno con reloj virtual. Es evidencia técnica útil que conviene describir con su alcance.

El control solicitado por el tutor es más fuerte: ejecutar un programa de referencia revisado por un especialista en el entorno Siemens/PLCSIM utilizado para medir la campaña. El archivo `src/trial_experiments/reference_pipeline.py` utiliza el generador del producto y simulación SCL interna; su nombre no basta para considerarlo una referencia independiente de experto en PLCSIM.

En D17, el período solicitado de 50 ms no identifica la causa del retraso observado. La comprobación debe contrastar código de referencia, origen temporal, secuencia aplicada y adquisición real, conservando las tolerancias originales. Si se descubre un defecto del evaluador, hay que evaluar su impacto sobre todos los ensayos afectados, no corregir solo D17.

### Interpretar la incertidumbre sin sustituir las repeticiones

Aplicando la fórmula de Wilson para una proporción binomial con n=60, éxitos=55 y z=1,959963984540054, se obtiene 81,9311–96,3880 %. El valor redondeado del dictamen es consistente con ese cálculo.

Fuentes metodológicas: [fórmula de Wilson en NIST](https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm) y [definición de ensayos independientes en la documentación de binom](https://search.r-project.org/CRAN/refmans/binom/html/binom.confint.html).

Las tres variantes de cada requisito comparten caso. Presentar el Wilson sin esa advertencia daría una precisión aparente mayor que la sustentada por el diseño. La comparación entre modalidades debe mantener el pareamiento; un análisis que contemple la agrupación por caso puede complementar el intervalo binomial. Un intervalo calculado sobre estas ejecuciones no mide por sí solo la variabilidad de repetir exactamente el mismo comando ni la confiabilidad operativa industrial.

## Orden práctico de trabajo

1. Sincronizar la versión que se utilizará para corregir: fuente LaTeX, .bib, imágenes y PDF completo de Overleaf. Resolver el corpus y los consentimientos antes de ejecutar voz.
2. Preparar las tablas de requisitos y objetivo–evidencia–resultado, la plantilla de las 180 celdas y el control de referencias de los Oracles. Son trabajos posibles sin nuevos resultados.
3. Resolver cómo registrar incidencias y reintentos preservando el congelamiento; preparar la comprobación de D17 y su programa de referencia.
4. Completar la evidencia experimental siguiendo el protocolo y conservar todos los intentos; no cambiar las tolerancias a partir de los resultados.
5. Integrar la comparación de voz, la evidencia de extremo a extremo, la incertidumbre y la respuesta final a la pregunta de investigación. Cerrar las observaciones editoriales y administrativas, y revisar el PDF final que recibirá el tutor.

## Verificación de esta lectura

- 29 entradas bibliográficas locales; ninguna clave citada ausente.
- Las entradas Vogel-Heuser 2018, Schnakenbeck 2026 y Ma 2019 están presentes.
- El PDF local conserva la huella de la última revisión verificada: `276eb295f7d9873f8c8cd5575c583f89d30c0f0ae011ea5cca2e85f479d42c35`.
- La función de infraestructura fue inspeccionada, sin modificarla.
- No se hicieron llamadas a modelos, compilaciones TIA, descargas al controlador ni cambios al estado de una campaña.

## Aplicación autorizada de correcciones

El autor solicitó adelantar las correcciones con la evidencia disponible. Se trabajará sobre una copia del manuscrito y se entregará el LaTeX compilado con respaldo de la versión anterior.

- [x] Incorporar requisitos funcionales/operativos y matriz objetivo–evidencia–resultado, manteniendo explícita la evaluación de voz pendiente.
- [x] Ampliar la comparación bibliográfica y reunir los identificadores internos en un anexo de reproducibilidad.
- [x] Añadir el intervalo de Wilson con su supuesto y el desglose descriptivo por ruta semántica; conservar todos los fallos originales.
- [x] Crear la matriz suplementaria de 180 celdas con 60 resultados TEXT y estados pendientes explícitos para voz, vinculada a las fuentes y hashes disponibles.
- [x] Revisar redacción, referencias, límites y colocación de figuras; compilar y verificar las páginas modificadas y el material suplementario. La comprobación con las cinco capturas exclusivas de Overleaf queda pendiente allí.
- [x] Entregar fuentes, PDF y paquete de Overleaf actualizados, con registro de lo resuelto y lo que aún necesita evidencia experimental o datos del autor.

El título y el objetivo general se unificaron por indicación expresa del autor: «Todo según las recomendaciones de mi tutor». El detalle del avance y los pendientes está en [avance_correcciones_tutor_20261022.md](avance_correcciones_tutor_20261022.md).
