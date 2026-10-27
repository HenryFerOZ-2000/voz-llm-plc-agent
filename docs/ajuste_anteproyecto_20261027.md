# Alineación con el anteproyecto y explicación de WER

Fuente activo actualizado directamente: `output/articulo_ajuste_kappa_20261027/articulo_CEP_voz_LLM_PLC.tex`.

Se restauró el objetivo específico 3 con el texto literal facilitado por el autor, se añadió el punto final al OE1 y se incorporó la explicación de la integración aprobada entre LLM y motor local de reglas, plantillas y estructuras IEC. El título y el objetivo general mantienen «de gran tamaño»; queda por confirmar con el tutor si el registro administrativo exige literalmente «lenguaje largo».

La elección de ASR se describe según el motivo comunicado por el autor: costo y evaluación exploratoria de viabilidad. No se declara que sea el servicio más barato del mercado ni que una comparación experimental haya probado su superioridad. El código confirma que la transcripción se entrega al LLM sin reescritura lingüística, salvo recorte de espacios en los extremos. La normalización NFC/casefold/alnum pertenece únicamente al cálculo de WER.

Se amplió WER con referencia textual, alineación de Levenshtein por palabras, S/D/I, denominador, porcentaje y agregación de los sesenta audios. Su descripción no modifica el procedimiento ni los resultados. Se eliminó la sección de disponibilidad de datos para la versión de maestría, se retiraron las dos definiciones sin uso de `freeze` y se incorporó la declaración solicitada de ausencia de financiamiento específico. El agradecimiento a la familia y el diagnóstico de REVIEW permanecen.

Las tablas de resultados, las figuras y el resumen no se modificaron. La compilación con Tectonic fue satisfactoria, sin advertencias LaTeX, referencias sin resolver ni cajas desbordadas. Se revisaron las páginas renderizadas de ASR y WER. Recibos y respaldo del fuente previo: `runtime/ajuste_anteproyecto_20261027/`.

El ZIP anterior no se reconstruyó: la entrega solicitada corresponde al archivo .tex actualizado. No debe ejecutarse un constructor anterior sobre este fuente sin incorporar estos cambios, porque restauraría una versión editorial desactualizada.
