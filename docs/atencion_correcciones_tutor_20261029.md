# Atención a las correcciones del artículo del 29 de octubre de 2026

Se aplicaron las recomendaciones de `Cambios_integrados_tesis_Henry_Ochoa.docx` al artículo. Se conservaron los 180 ensayos seleccionados, las cifras de las tablas originales, las 60 variantes, los objetivos aprobados y los 2221 archivos del manifiesto experimental. El código de la aplicación no se modificó.

## Aplicación en Overleaf

Reemplazar `articulo_CEP_voz_LLM_PLC.tex` y `referencias.bib` por los archivos de `output/articulo_ajuste_kappa_20261027/`. Las siete imágenes utilizadas por el artículo conservan sus nombres y contenido. El script `reproducir_figuras.py` y el registro `revision_documental_20261029.json` documentan la reproducción y la revisión; no son necesarios para compilar en Overleaf.

## Correspondencia con las recomendaciones

| Punto | Atención aplicada |
|---|---|
| 1 | Se introduce D01–D20 como catálogo de veinte casos y se distingue de los 180 ensayos de sus variantes y modalidades. |
| 2 | Se define «oráculo de prueba» en la introducción y se usa el término en español de forma consistente. |
| 3 | Se distingue la política general ASSIGNED del estado LOCKED/FREE al inicio de cada ensayo. |
| 4 | PASS, FAIL y REVIEW se definen en métodos; el indicador pareado es 1 para PASS y 0 para los demás, sin equiparar causas. |
| 5 | Se documentan los ocho REVIEW con evidencia, causa y decisión. Se identificaron cinco omisiones funcionales por inspección; se preservó el resultado original de cada ensayo y no se afirmó una nueva ejecución. |
| 6 | El WER queda referido al guion. Se declara que puede incluir diferencias de lectura y que no existe una transcripción humana verificada aportada para separar ese componente. |
| 7 | Se incorpora la matriz de cuatro objetivos, evidencia y resultado, complementaria a la de requisitos. |
| 8 | D05–V2 se documenta en las tres modalidades con transcripciones y preguntas exactas; las etapas posteriores a las aclaraciones constan como no ejecutadas. |
| 9 | La selección del ASR se describe por costo e integración, sin comparación previa de superioridad; la valoración de los resultados pasa a discusión. |
| 10 | Se explican los cuatro tiempos ausentes y se incluye un bloque TIA calculado y comprobado por campo, con n y estadísticos. |
| 11 | Las categorías de complejidad se presentan como etiquetas descriptivas; no se inventa una escala ni una justificación posterior de D03/D04/D11. |
| 12 | Se explicita el locutor único en resumen y el posible sesgo de familiaridad en limitaciones. |
| 13 | Las conclusiones se vinculan a análisis de requisitos, diseño, implementación y validación, conservando las cifras. |
| 14 | Se aclara el carácter automatizado del contraste separado. El apéndice identifica la instantánea por huellas, la revisión de publicación, los archivos y los scripts; la rectificación D14 se traslada allí. |
| 15 | Se conserva «modelos de lenguaje de gran tamaño». La sección NIST citada no muestra fecha, por lo que se añade «s. f.»; se verifican TUM/Obermeier y la página editorial de Ren. La tilde de «Andrés» queda pendiente de confirmación del autor. |
| 16 | Se compila y renderiza el PDF completo: 18 páginas físicas, sin advertencias de LaTeX, referencias indefinidas ni fallos al decodificar los flujos del PDF. Las tablas de tiempos y errores quedan junto al texto correspondiente y fuera de las conclusiones. Se conserva la clase CAS y su pie editorial: no se recibió la portada institucional ni una orden de sustituirlo. |

## Revisión documental de REVIEW

Las omisiones encontradas están en D15–V2/V3 de voz limpia (sin rama automática), D15–V1 con ruido (la orden automática no interviene en el SCL) y D17–V1/V3 de voz limpia (sin habilitación Start). Se distinguen de los tres casos con discrepancias de etiqueta o correspondencia de selector: D05–V2 textual, D15–V3 textual y D15–V3 con ruido. El registro completo preserva los identificadores y las huellas de los programas inspeccionados. No se reclasificó ninguna celda.

## Reproducción

Los scripts `recalcular.py` y `comparar_campanas.py` de la carpeta de campaña reproducen los cálculos principales con Python estándar. Para regenerar las tres figuras experimentales se requieren Matplotlib y NumPy:

```text
python output/articulo_ajuste_kappa_20261027/reproducir_figuras.py --output figuras_reproducidas
```

En la comprobación del 29-10-2026, los tres PNG regenerados fueron idénticos byte a byte a los utilizados en el manuscrito. No se realizaron llamadas al ASR/LLM ni nuevas pruebas en PLC. La instantánea de campaña y los registros permanecen sin cambios.

## Pendientes que requieren evidencia o confirmación humana

- Confirmar si Paul utiliza la grafía «Andrés». Hasta recibir respuesta se conserva «Paul Andres Chasi Pesantez».
- Si se desea un WER que mida exclusivamente la discrepancia del ASR respecto del habla real, escuchar las 60 locuciones y fijar una transcripción humana fiel antes de recalcular. Los valores actuales siguen siendo válidos como discrepancia respecto del guion y están identificados así.
- Las correcciones de portada y página institucional de derechos deberán aplicarse en el documento institucional cuando se facilite su fuente. No se añadieron ni se supusieron esos preliminares al artículo CAS.
