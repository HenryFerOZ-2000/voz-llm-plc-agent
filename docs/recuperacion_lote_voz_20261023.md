# Recuperación del lote de voz tras error ASR — 23-10-2026

## Evidencia

El ensayo `D06_V3_VOICE_CLEAN_DEV_001` terminó a las 11:21:45 con
`INFRASTRUCTURE_ERROR`, etapa `asr`. El servicio devolvió HTTP 429,
`insufficient_quota`, `credit_balance_exhausted`.
Su grabación limpia existe, dura 5,018 s y coincide con el hash guardado.

El lote `VCLEAN_DEV_20261023_001` conservó el estado `RUNNING` y su entrada
`GENERATING`, actualizado a las 11:21:42. La interfaz habilita el reintento solo
para lotes pausados con una entrada que requiera atención. En este estado también
quedaba deshabilitado REANUDAR; reiniciar por sí solo no resolvía la discrepancia.

## Causa y corrección

En `run_complete_trial`, la salida anticipada por fallo de voz guardaba el ensayo
y regresaba sin notificar al controlador del lote. Ahora entrega el resultado
fallido al mismo controlador que gestiona los demás resultados terminales. El
controlador registra la incidencia y pausa el lote sin iniciar otro ensayo.

Al recuperar desde disco un lote que aparece RUNNING, `_load_open_text_batch`
contrasta sus entradas con los ensayos persistidos y lo deja pausado. No inicia
trabajo automáticamente. El lote ya cargado en memoria conserva su manejo normal
para no interrumpir una operación activa.

## Validación y conservación

Se reprodujeron antes del cambio tres fallos: ausencia de pausa al fallar ASR,
recuperación de una entrada terminal y recuperación de una evaluación pendiente.
Las tres pruebas pasan con el cambio. El ensayo de ASR comprueba además el
reintento explícito, la conservación del audio anterior y la reutilización de la
grabación del corpus. Se utilizan audio sintético, proyecto temporal y dobles de
API y PLC.

La regresión completa y sus salidas se conservan en
`runtime/batch_voice_recovery_20261023/full_suite/`.
Resultado final: 2226 pruebas en 151 módulos; 2217 aprobadas, 8 omitidas y un
fallo esperado (`xfail`), sin fallos inesperados. `git diff --check` no informa
problemas de espacios. Se repitió la comprobación de conservación tras la suite.
Una simulación de recuperación sobre una copia del lote real produce PAUSED y
una entrada INFRASTRUCTURE_ERROR apta para reintento.

Se guardaron respaldo de `src/gui.py` y hashes de 2528 archivos. La comprobación
inicial encontró como única modificación de ese inventario `src/gui.py`.
La comprobación final detectó que el arranque de la interfaz durante la regresión
también recuperó el lote real: actualizó `batch_manifest.json`, `batch_summary.csv`
y `batch_summary.json` para reflejar el error ya persistido y la pausa. No cambió
ningún archivo de ensayo, audio, par ruidoso ni el manifiesto V4. No hubo llamadas
reales a la API ni operaciones TIA/PLC.

Se aisló `_announce_open_text_batch` en la construcción de la GUI de pruebas para
que futuras regresiones no recuperen lotes reales. Las pruebas de recuperación
invocan el cargador explícitamente sobre sus proyectos temporales.
Tras ese aislamiento, las 48 pruebas de flujo de voz y control de lotes vuelven
a pasar; no se detectaron nuevas modificaciones en la evidencia protegida.

## Pasos para el usuario

1. Cerrar y volver a iniciar la aplicación para cargar la corrección.
2. Abrir el lote existente `VCLEAN_DEV_20261023_001`; la recuperación lo pausa y
   habilita REINTENTAR ESTE ENSAYO.
3. Una vez restablecido el saldo de la API, elegir ese reintento y documentar el
   motivo, por ejemplo «Saldo de API restablecido tras error de cuota».

En este caso la generación falló antes de obtener un programa: el reintento crea
otro ensayo para la misma celda y conserva el anterior. La grabación del corpus
se reutiliza; no se vuelve a grabar. No iniciar un lote distinto ni borrar datos.

La corrección no restablece el saldo del servicio. Este lote sigue siendo de
desarrollo. La modificación de GUI debe documentarse en una nueva revisión antes
de una campaña formal; el freeze V4 original permanece conservado.
