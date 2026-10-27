> Actualización al 24-10-2026: las 180 celdas están ejecutadas y el manuscrito completo se actualizó. La revisión documental y estadística está cerrada, con 162 PASS, 17 FAIL y un REVIEW conservados. Estado vigente: [cierre de correcciones](cierre_correcciones_tutor_20261024.md). El texto siguiente conserva el estado histórico del 22-10.

# Correcciones adelantadas del dictamen del tutor

Se actualizaron el artículo y el material suplementario con la evidencia disponible del lote textual. Se conserva el resultado histórico de 60 ensayos, 57 compilados y 55 conformes. El autor indicó unificar también el título y el objetivo general según la recomendación del tutor.

## Incorporado en el manuscrito

- Título y objetivo general con «modelos de lenguaje de gran tamaño».
- Tabla de siete requisitos funcionales y tres operativos, con criterio de comprobación y resultado disponible.
- Matriz OE1–OE4 y pregunta de investigación, con referencias a la evidencia y los aspectos pendientes.
- Tabla bibliográfica ampliada con Koziolek 2023, Tran 2024, AutoPLC y PLCWorld, además de los antecedentes existentes.
- Identificadores de versión, política de asignación, algoritmo de mezcla, estados del mapa, commits y lote reunidos en el anexo de reproducibilidad.
- Intervalos de Wilson al 95 %: conformidad 81,93–96,39 % y compilación 86,30–98,29 %, con explicación del supuesto binomial y la agrupación por caso.
- Desglose por ruta: LLM, 58 ensayos, 56 compilados y 55 conformes; respaldo, dos ensayos, uno compilado y ninguno conforme. Los dos errores de conexión siguen dentro del resultado global.
- Ejemplo textual D05 enlazado a sus parámetros, asignaciones, fuente SCL, traza e informe.
- Pies de figura y párrafos más directos; ajuste de tamaños, capacidad de colocación y barrera antes de las referencias.
- Respuesta explícita al alcance actual de la pregunta de investigación: conformidad textual caracterizada y comparación acústica pendiente.

## Material suplementario preparado

La carpeta `suplemento/analisis_revision_20261022/` contiene:

- `matriz_180_celdas.csv` y JSON: 60 resultados TEXT y 120 celdas de voz pendientes. Incluye entrada, intención, parámetros, ruta, incidencia, hash SCL y resultados por etapa.
- `procedencia_y_calculos.json`: cálculos y hashes de 351 fuentes verificadas.
- `intervalos_adquisicion.csv`: 57 registros de intervalos reales entre muestras del mismo paso y fase. D17–V1: mediana 47,73 ms, P95 64,48 ms y máximo 222,42 ms. Estos valores no atribuyen por sí solos la discrepancia de la alarma a una causa.
- `ejemplo_D05_TEXT.json`, `D05_V1_TEXT_program.scl` y `traza_D05_V1_TEXT.csv`: evidencia de la cadena textual, con cuatro comprobaciones funcionales y un invariante satisfechos.
- `control_validacion_oracles.csv`: veinte filas pendientes para registrar programa de referencia, revisión, compilación, ejecución y veredicto.
- `PROTOCOLO_REFERENCIAS.md`: procedimiento de comprobación con especialista, empezando por D17.
- `exportar_evidencia.py` y README: exportación reproducible con biblioteca estándar de Python desde los datos del repositorio. Se ejecutó en una salida separada y reprodujo los siete archivos derivados principales byte a byte.

## Verificado

El artículo y el suplemento compilan. Se resolvieron las claves de las 30 referencias y las referencias cruzadas. Se inspeccionaron las nuevas tablas, los intervalos, las páginas finales y las secciones suplementarias modificadas. La compilación local tiene 18 páginas físicas, incluido highlights, y el suplemento nueve.

Cinco capturas continúan disponibles únicamente en Overleaf. Las condiciones que las incorporan permanecen en el LaTeX con los mismos nombres. La distribución final con esas cinco imágenes debe comprobarse al recompilar en Overleaf; el PDF local no certifica esa variante de maquetación.

## Pendiente de evidencia o información

1. Grabar/confirmar y autorizar el corpus, y ejecutar las 120 celdas de voz con el protocolo y la versión correspondientes.
2. Completar la comprobación de los veinte Oracles con programas de referencia revisados por especialista y ejecución en PLCSIM. La plantilla preparada no acredita validación realizada.
3. Decidir y ejecutar los reintentos técnicos documentados de D11 preservando intentos originales. El diagnóstico de transporte se separó en el análisis derivado; el indicador del software congelado no se modificó.
4. Acreditar inicialización de memoria/retentividad, fundamento de tolerancias y evidencia interactiva de aclaración y ampliación.
5. Obtener la figura completa de un caso en las tres modalidades al disponer de voz.
6. Completar ciudad, financiación, correspondencia, CRediT, intereses, acceso/licencia y agradecimientos, así como identificación del ruido, participantes, micrófono y consentimiento.
7. Revisar el PDF completo de Overleaf y la captura que conserva la etiqueta PHYSICAL_PLC.

Los programas, Oracles, manifiestos y resultados originales permanecen sin modificación. Los datos nuevos del suplemento son exportaciones y cálculos sobre los registros existentes.
