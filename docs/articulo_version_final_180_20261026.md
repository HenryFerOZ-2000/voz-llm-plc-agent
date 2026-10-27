# Artículo basado en la campaña final

Por indicación del autor, la redacción principal presenta exclusivamente la evaluación de la versión final: campaña `THESIS_DISCRETE_LLM_180_20261026_R2`, realizada el 26-10-2026. No combina observaciones de campañas anteriores.

- Matriz autorizada: `output/estadistica_campana_completa_180_20261026/matriz_180_celdas.json`.
- 180 comandos con interpretación LLM y copias del mismo mapa de simulación.
- 174 programas compilados; 165 PASS, 7 FAIL, 8 REVIEW.
- Cada modalidad obtuvo 55/60 PASS; las coincidencias globales no implican equivalencia ni identidad por comando.
- WER global: 52/1085 en limpia y 75/1085 con ruido.
- Un resultado por caso–variante–modalidad; los lotes solo automatizan su ejecución.

El artículo, las figuras regeneradas, la bibliografía y los archivos CAS se encuentran en `output/articulo_version_final_180_20261026/`. El ZIP del mismo nombre tiene `articulo_CEP_voz_LLM_PLC.tex` directamente en su raíz y se puede cargar como proyecto en Overleaf. Los títulos estructurales permanecen en inglés y el cuerpo en español. El título largo y la autoría confirmada se conservaron.

La rectificación interna de clasificación de D14 y la exclusión de su reintento improcedente se conservan en el suplemento de auditoría. No se eliminó ni se falsificó la procedencia de los datos. Las capturas del sistema se distinguen de las observaciones estadísticas de esta campaña.

Los registros experimentales y los archivos fuente del programa no se modificaron durante esta actualización del artículo. Tampoco se sobrescribió el proyecto externo del autor: debe importar el paquete en el proyecto del tutor. Siguen pendientes la declaración pública de acceso/licencia de los datos y los agradecimientos; los roles CRediT deben revisarse con ambos autores.

Verificación: compilación local con Tectonic, referencias y recursos resueltos, sin cajas desbordadas ni advertencias de LaTeX; inspección de páginas renderizadas y contraste estadístico portable. Los mensajes externos de Fontconfig/algorithm.sty y la entrada sin páginas de BigCodeBench se registran en el recibo de compilación y no impidieron generar el PDF.
