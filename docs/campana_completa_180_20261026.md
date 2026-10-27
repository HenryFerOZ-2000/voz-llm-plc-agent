# Campaña completa nueva: 180 comandos, LLM exclusivo y mapa común

Autorización del autor del 26-10-2026: ejecutar ahora todas las modalidades, empezando por texto, para continuar la redacción. Esta instrucción sustituye la espera previa para las modalidades de voz.

Se reutilizan los 60 audios limpios y sus 60 derivados ruidosos originales; no se vuelve a grabar ni mezclar. Orden: D01--D20 × V1--V3 para TEXT, después VOICE_CLEAN y VOICE_NOISE. Se aplica el mismo mapa 8+8 de simulación en las 180 celdas, con I_Start/I_Stop conservados y el canal I16.2 explícitamente autorizado como I_Emergency. Se usa el motor de producto y el evaluador conductual existentes, sin cambiar prompts ni Oracles durante la campaña.

Identificador: THESIS_DISCRETE_LLM_180_20261026_R2. Protocolo, inventario de hashes, registros y progreso en runtime/campana_180_llm_20261026/. La fase técnica de almacenamiento es DEVELOPMENT_VALIDATION para preservar la campaña FORMAL histórica y su congelación; la nueva campaña se identifica y congela por su propio protocolo y hashes. No se afirma un commit limpio ni identidad con V4.

La matriz principal posterior incluirá las 180 celdas nuevas independientemente del resultado. PASS/FAIL/REVIEW son terminales. Solo los errores de infraestructura permiten hasta dos reintentos técnicos con las esperas ya fijadas de 5 y 15 segundos; se conserva el mismo programa al repetir evaluación y el mismo audio al repetir generación. Se conserva todo intento previo. No se seleccionan resultados antiguos para mejorar la tasa.

Estado inicial: revisión de entorno satisfactoria, TESIS_PLC_SIM conectado en RUN y destino PLCSIM_ADVANCED. Preparación y verificación de artefactos antes del primer ensayo. Las estadísticas y el artículo anteriores permanecen archivados.

## Enmienda de clasificación del ejecutor

Durante D14--V3, el ejecutor reutilizado lanzó `IO_ASSIGNMENT_BLOCKED` y lo etiquetó genéricamente como infraestructura. El diagnóstico original muestra rechazo local de propuestas I/O; por la regla previa era un fallo experimental y no correspondía reintentar. La secuencia se detuvo entre ensayos, tras 44 comandos, sin interrumpir una evaluación.

Se verificaron los hashes: 284 archivos protegidos del motor, modelos/configuración, mapa, prompts, audios y Oracles permanecieron intactos. Solo cambiaron dos archivos del ejecutor para separar los errores de servicio de los fallos de generación y preservar la semántica en los rechazos. La corrección y la política de reintentos pasaron 24 pruebas aisladas.

El primer D14--V3 se conserva como FAIL de asignación I/O. Se guardó `trial_antes_enmienda_clasificacion.json` antes de corregir su etiqueta, junto con `revision_clasificacion.json`, el error original y la respuesta LLM. El reintento D14_V3_TEXT_DEV_002 (PASS) se conserva pero queda explícitamente excluido por ser improcedente. No se eligió el resultado favorable. Los otros 43 resultados no cambiaron.

Protocolo original intacto: `protocolo_previo.json`. Enmienda con hashes anteriores y actuales: `enmienda_clasificacion.json`. No se afirma identidad binaria de todo el ejecutor durante la campaña; sí se acredita la misma versión de interpretación/generación, el mismo mapa y los mismos Oracles. La secuencia continúa desde D15--V3, sin repetir los comandos ya evaluados.

## Cierre verificado

180/180 celdas completadas:165 PASS,7 FAIL y8 REVIEW. Cada modalidad obtuvo55/60 PASS (91,67%). Compilaron58/60 TEXT,59/60 VOICE_CLEAN y57/60 VOICE_NOISE. Rutas LLM180; respaldo por reglas0. WER global4,79% limpia y6,91% ruido.

Verificación de176 paquetes generados,120 transcripciones con distancia de edición independiente y4224 comprobaciones de canales;755 vínculos digitales revisados. No se modificaron canales protegidos. El reintento improcedente D14 está excluido; no hubo reintentos técnicos válidos. Datos, protocolo, cálculos, incidencias y pruebas de integridad en output/estadistica_campana_completa_180_20261026/. El informe estadístico activo se actualizó con respaldo del anterior; el manuscrito todavía no se ha reescrito.
