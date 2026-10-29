# Plan de aplicación de correcciones del artículo

> **Para ejecución:** aplicar `superpowers:executing-plans` por tareas y comprobar cada bloque antes de continuar.

**Objetivo:** incorporar las 16 recomendaciones del documento del tutor al artículo LaTeX sin inventar comprobaciones, cambiar registros originales ni reclasificar resultados sin evidencia suficiente.

**Arquitectura:** usar el artículo activo y la campaña publicada como fuentes; mantener separados el veredicto original del ejecutor y la revisión documental posterior. El Word es una referencia de cambios, no un registro experimental.

**Herramientas:** Python estándar para examinar JSON/OOXML y recalcular estadísticas; LaTeX CAS y Tectonic para compilar; renderizado PDF para comprobar la presentación.

**Especificación:** `C:/Users/DOCENTE/Downloads/Cambios_integrados_tesis_Henry_Ochoa.docx`; extracción de lectura en `runtime/correcciones_tutor_20261029/indicaciones.txt`.

## Restricciones y comprobaciones

- Conservar los 180 ensayos seleccionados y sus veredictos originales: 165 PASS, 7 FAIL y 8 REVIEW.
- No afirmar revisión humana de los audios ni recalcular un WER de referencia humana sin esa evidencia.
- No atribuir independencia humana a una comprobación automatizada separada del generador.
- Preservar mapa, audios, programas, oráculos, registros y código de la campaña.
- Mantener GitHub como destino de disponibilidad, sin MIT ni Zenodo en el artículo.
- Entregar el `.tex`; incluir la bibliografía si cambia. Las imágenes se conservan salvo defecto comprobado de legibilidad.

## Tareas

- [x] 1. Contrastar registros de los ocho REVIEW, D05–V2 y tiempos ausentes; identificar versión, huellas y scripts de reproducción (puntos 5, 8, 10, 14).
- [x] 2. Corregir catálogo/unidad, terminología, estados I/O, definiciones, ASR/WER, complejidad y locutor (puntos 1–4, 6, 9, 11–12).
- [x] 3. Incorporar tablas de revisión y trazabilidad, matriz de objetivos y conclusiones vinculadas (puntos 5, 7–8, 13).
- [x] 4. Verificar bibliografía y grafía confirmada; documentar diferencias entre la plantilla de artículo y portada institucional (puntos 15–16).
- [x] 5. Compilar, inspeccionar páginas, contrastar cifras y producir el archivo final con registro conciso de cambios y limitaciones pendientes.

## Cierre

Verificación: 18 páginas físicas; cero advertencias de LaTeX; 2221 archivos experimentales con huellas intactas; tres figuras regeneradas idénticas; ningún veredicto reclasificado. Se realizó una revisión documental independiente, sin defectos materiales. Las confirmaciones recibidas sobre audio humano y grafía de Paul, y el alcance pendiente de la portada institucional, quedan documentados en docs/atencion_correcciones_tutor_20261029.md.
