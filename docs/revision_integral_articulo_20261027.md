# Revisión integral de coherencia del artículo

**Dictamen: listo dentro del alcance experimental revisado, con las limitaciones que el propio artículo declara.** La revisión de consistencia de los datos experimentales quedó completa; no se renovó la comprobación externa del contenido de cada referencia bibliográfica. No se modificaron el artículo, las cifras, los veredictos, las figuras ni las conclusiones.

Fuente revisada: [articulo_CEP_voz_LLM_PLC.tex](../output/articulo_ajuste_kappa_20261027/articulo_CEP_voz_LLM_PLC.tex). SHA-256: `c1496ccb264f997ca888e13a1255de36159bba91088199e4f32dabeed407e573`.

La fuente de resultados fue la matriz de la campaña `THESIS_DISCRETE_LLM_180_20261026_R2`, conservada en el archivo experimental local del proyecto y contrastada con los 180 registros nativos seleccionados de `results/development_validation_v2`. La matriz preliminar se usó exclusivamente para el acuerdo entre campañas. Los ZIP de transferencia a Overleaf permanecen locales y no se publican en GitHub por indicación del autor.

## Datos reconciliados

- Hay 180 celdas caso–variante–modalidad, sin duplicados ni ausencias: 165 PASS, siete FAIL y ocho REVIEW. Cada modalidad conserva 55/60 PASS, equivalentes al 91,67 %. Compilaron 58, 59 y 57 programas, respectivamente: 174 en total; se generaron y verificaron 176 paquetes.
- El WER se recalculó desde las referencias y transcripciones originales: limpia, 43 sustituciones + cuatro omisiones + cinco inserciones sobre 1085 palabras; ruido, 63 sustituciones + cero omisiones + 12 inserciones sobre 1085. Resultados: 4,79 % y 6,91 %, con aumento de 2,12 puntos porcentuales.
- Wilson, las tres comparaciones pareadas y sus intervalos por caso concuerdan con el artículo. Se reprodujo el bootstrap mediante un cálculo independiente. La comparación preliminar-final conserva 157 acuerdos de 180 (87,22 %) y kappa 0,253; no se confunde con repetibilidad a configuración idéntica.
- Coinciden medias, desviaciones muestrales, medianas, cuartiles y denominadores de las duraciones. También coinciden complejidad y casos con tres variantes PASS: 15 en texto, 17 en limpia y 16 con ruido.
- Los 120 WAV conservan PCM16, mono, 16 kHz y sus hashes. Las 60 mezclas utilizan la locución limpia correspondiente; el SNR recalculado desde las muestras queda entre 9,99996 y 10,00004 dB, dentro de la tolerancia declarada. No se realizó escucha perceptual completa de todas las locuciones.
- Se contrastaron las 176 instantáneas disponibles y las 755 señales digitales vinculadas. Los tres canales protegidos mantienen sus nombres y direcciones. Las 60 variantes impresas coinciden literalmente con el catálogo y con las referencias TEXT; los roles obligatorios de los veinte casos coinciden con sus Oracles. El RESET opcional de D09 no es un rol requerido del catálogo.
- La lista de ocho REVIEW y los siete fallos coincide con los registros. Los 174 informes nativos confirman los veredictos y la cobertura de invariantes: 49 con invariantes explícitos, 118 sin ellos y siete sin evaluación completa por roles ausentes. No hay violaciones críticas o mayores registradas en los casos evaluados.
- En cuatro detenciones previas a la integración, el campo nativo `final_verdict` está vacío y el resultado terminal consta en `final_status=FAIL`. Son D14–V3 textual y las tres aclaraciones. Esta diferencia de campos no constituye un cambio de resultado. La única rectificación de clasificación sigue siendo D14–V3, documentada con el reintento PASS excluido.
- D05–V1 mantiene 70 muestras por modalidad y direcciones de arranque, emergencia y motor concordantes. Las primeras muestras de apagado aparecen 63,47, 50,70 y 64,53 ms después de la primera muestra de emergencia activa. D07–V2 textual presenta la primera muestra ON a 0,0655942 s, que se imprime correctamente como 0,066 s.
- ASR y LLM se distinguen consistentemente: `gpt-4o-mini-transcribe` figura en los 120 registros ASR y `gpt-5.6-terra` en la configuración de las solicitudes LLM de los 180 ensayos. Se verifica el identificador solicitado; no se recuperó una versión independiente del modelo servido. El generador local sigue descrito como constructor de IR y SCL.

## Presentación y cobertura

Los totales siguientes corresponden a componentes del alcance, no a porcentajes de exactitud. Un cero indica que no se observaron defectos pendientes; no supone verificación externa de toda afirmación imaginable.

| Categoría | Defectos observados | Evaluación |
|---|---|---|
| Integridad del artículo | 0 / 8 | Resumen, cinco secciones principales y dos apéndices mantienen una secuencia coherente. |
| Claridad analítica | 0 / 8 | Se distinguen unidad experimental, etapas, conformidad, REVIEW y límites de inferencia. |
| Consistencia visual | 0 / 16 | Vista general de las 16 páginas y revisión legible de cinco figuras; se conservó la revisión de los apéndices. El espacio en blanco aceptado es estético. |

## Corrección analítica

| Categoría | Defectos observados | Evaluación |
|---|---|---|
| Autoridad y trazabilidad de fuentes | 0 / 9 | Ocho grupos de evidencia experimental contrastados; la comprobación externa del contenido de las publicaciones no se renovó. |
| Exactitud de valores | 0 / 10 | Siete tablas de resultados y tres figuras cuantitativas concuerdan con las fuentes y los recálculos. |
| Acuerdo interno de figuras | 0 / 3 | Leyendas, unidades, origen temporal y anotaciones concuerdan con las trazas y el WER. |
| Detalles de fuentes interactivos | N/A | Artículo estático sin paneles interactivos. La trazabilidad experimental se evalúa en la primera fila. |
| Consistencia entre secciones | 0 / 6 | Totales, WER, duraciones, complejidad, funciones de modelos y mapa/versiones se mantienen coherentes. |
| Controles de calidad de datos | 0 / 6 | Completitud, selección, audio pareado, SNR, mapa y procedencia LLM comprobados. |
| Respaldo de conclusiones | 0 / 3 | Viabilidad limitada al catálogo; igualdad sin equivalencia; acuerdo entre campañas de alcance indicativo. |

## Problemas prioritarios y límites

No se detectaron errores numéricos ni contradicciones experimentales que requieran cambiar el `.tex`. Se conservan las limitaciones ya declaradas: REVIEW no acredita conformidad, el estudio se limita al catálogo y a simulación, los Oracles no tuvieron validación independiente con programas de referencia y la versión interna servida por el LLM no quedó identificada.

Los 31 identificadores bibliográficos citados tienen entrada y todas las referencias cruzadas están resueltas. Esto verifica la integridad del enlace bibliográfico, no sustituye la lectura y comprobación externa de cada publicación. La aceptación institucional del título, idioma y formato final corresponde al tutor y a la universidad.

La nueva compilación finalizó sin referencias indefinidas, advertencias LaTeX ni cajas desbordadas o insuficientes. La fuente compilada coincide por SHA-256 con la fuente auditada.

La evidencia permanece en el archivo experimental local: `runtime/revision_integral_articulo_20261027/audit_result.json`, `auditar.py` y `coverage.json`, y en `runtime/version_biblioteca_20261027/verificacion_latex.json`. El script de auditoría requiere los registros nativos locales. Esos registros y los paquetes de transferencia no se incluyen en Git.
