# Revisión del artículo del 27-10-2026

Fuente más reciente entregado como archivo único:
`output/correcciones_articulo_20261027/articulo_CEP_voz_LLM_PLC.tex`.
El usuario pidió solo este .tex para copiarlo en Overleaf, sin importar imágenes ni ZIP adicionales. No se sobrescribió su proyecto externo.

Cambios: encabezados en español; confirmación de D15–V1/V3 como REVIEW con ruido y 17 casos completos en voz limpia; sustitución visual de la nota de respaldo de Figura 1 mediante una máscara y texto nativos de LaTeX; explicación de la campaña preliminar; declaración explícita de la única rectificación de clasificación D14–V3 y de su reintento excluido; comparación indicativa entre campañas; comillas seguras con cita literal del ASR; identificador sin cortes internos; Tabla 9 con primera columna suficiente. Los campos de datos públicos y agradecimientos se conservan pendientes.

La comparación utiliza la matriz inicial completa de `output/estadistica_tesis_20261024/matriz_180_celdas.json` y la campaña final completa de `output/estadistica_campana_completa_180_20261026/matriz_180_celdas.json`, emparejadas por caso–variante–modalidad. No utiliza el conjunto intermedio de sustituciones LLM exclusivo. Hay 157 acuerdos de 180 (87,22 %) y kappa no ponderado de Cohen 0,2531120332, con tres categorías PASS/FAIL/REVIEW. Los 120 hashes de audio coinciden entre campañas. En limpia hubo una sustitución menos en D10–V1, con WER global 53/1085 frente a 52/1085.

No se incorporó la afirmación propuesta de que el generador permaneciera idéntico: sus archivos difieren respecto de la congelación preliminar incluso normalizando CRLF a LF. Sí coinciden el prompt estático, el código ASR y los veinte archivos Oracle bajo esa normalización. Por ello la comparación se declara indicativa entre versiones, no repetibilidad bajo configuración idéntica. La cita conservada es «lo apague y lo deje arrancado mientras dure», conforme al registro; no se cambió a «no apague».

Scripts y comprobaciones: `runtime/revision_articulo_20261027/revisar.py`, `verificacion_y_acuerdo.json`, `verificar_latex.py` y `verificacion_latex.json`. El documento compiló con Tectonic sin referencias indefinidas, cajas desbordadas, cajas insuficientes ni advertencias LaTeX. Se inspeccionaron las páginas renderizadas, incluidos Figura 1, tabla, cita e identificador. El PDF privado de revisión no se entregó: el único archivo de la carpeta de salida es el .tex solicitado.
