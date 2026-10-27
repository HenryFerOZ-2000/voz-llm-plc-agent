# Versión del artículo para biblioteca

El fuente actualizado sigue siendo `output/articulo_ajuste_kappa_20261027/articulo_CEP_voz_LLM_PLC.tex`. Se actuó sobre ese nombre, sin sobrescribir el `main.tex` externo del usuario.

Se eliminaron todas las apariciones del término solicitado, incluida la búsqueda del prefijo `suplement` sin distinguir mayúsculas. El fuente y el PDF privado de verificación tienen cero coincidencias. La configuración secundaria, los archivos de prompt, las secuencias completas, los cálculos y las evidencias se remiten ahora al archivo experimental del proyecto. El texto integra la instancia de simulación y comunicación, una descripción breve de la mezcla con región activa y un ejemplo operativo del Oracle D01.

El Apéndice A incorpora literalmente las 60 variantes del registro final, agrupadas como caso/V1/V2/V3. Se presentan en una tabla lógica con dos partes a ancho completo, ambas con `table*` y `footnotesize`. La numeración se conserva mediante continuación. La disposición de las páginas de variantes permite que el Apéndice B aparezca debajo de la segunda parte. El Apéndice B queda en tres frases con identificador y ubicación de la configuración, huellas, Oracles, auditoría y scripts.

Se añadieron las dos indicaciones sobre ASR: valoración posterior del modelo y comparación futura con alternativas, incluidas locales. La valoración posterior se vincula al WER junto con los resultados de ejecución, sin inferir suficiencia conductual únicamente del WER.

Se verificó identidad exacta de once tablas protegidas, incluidas todas las de resultados, y de las conclusiones completas. El resumen y los bloques de figuras tampoco cambiaron. Los sesenta textos se cotejaron con la matriz final y se conservaron literalmente. Las imágenes y la bibliografía no se modificaron.

La compilación local con Tectonic produjo 16 páginas físicas, sin referencias sin resolver, cajas desbordadas o insuficientes, advertencias LaTeX ni tablas demasiado grandes. Se inspeccionaron las dos partes de la tabla y el Apéndice B renderizados. Scripts, respaldo y recibos: `runtime/version_biblioteca_20261027/`. El ZIP anterior permanece sin reconstruir; la entrega de este cambio es el archivo .tex.
