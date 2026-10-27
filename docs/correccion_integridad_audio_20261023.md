# Corrección de integridad de evidencia de voz — 23-10-2026

## Incidencia comprobada

El lote de desarrollo `VCLEAN_DEV_20261023_001` quedó `PAUSED`, con motivo
`TRIAL_PRECHECK_BLOCKED`, al evaluar `D01_V1_VOICE_CLEAN_DEV_001`.
La generación había terminado correctamente y la evaluación seguía `PENDING`.
El bloqueo precedió a la compilación, descarga y prueba conductual.

El diagnóstico rechazaba `audio/reference.txt`, `audio/clean_audio.wav` y
`audio/asr_result.json` como rutas fuera del ensayo. Los archivos estaban dentro
del directorio correcto y sus hashes coincidían con el manifiesto.

## Causa y cambio

`verify_trial_integrity`, en `src/trial_experiments/deferred_evaluator.py`,
comparaba el padre inmediato del archivo con la raíz del ensayo. Esto aceptaba
archivos directos, pero rechazaba cualquier evidencia en una subcarpeta.
El generador del manifiesto sí incorpora las rutas relativas `audio/...`.

Se sustituyó esa comparación por una comprobación de pertenencia a la raíz
resuelta. Se admiten descendientes relativos; se siguen rechazando rutas
absolutas o ancladas y escapes de directorio. La comprobación de hashes permanece
activa. No se modificaron ASR, interpretación, generación SCL ni Oracles.

## Verificación

- Nuevas pruebas de rutas anidadas válidas, audio ausente o alterado, rutas
  absolutas, `..` y enlaces a directorios externos.
- El ensayo integrado de voz comprueba primero la integridad del audio original
  y después su rechazo al alterarlo.
- El ensayo real pendiente supera la comprobación de sus diez archivos.
- Se cotejaron 409 archivos con la instantánea anterior. Solo cambió el archivo
  fuente del verificador; se conservaron audio, ensayo, lote y manifiesto V4.
- La ejecución completa de pruebas de software se registra en
  `runtime/voice_integrity_fix_20261023/full_suite/summary.json`, con salidas por
  grupo: 2223 pruebas recogidas en 151 módulos, 2214 aprobadas, 8 omitidas y un
  fallo esperado (`xfail`); estado final `PASSED`. Son comprobaciones de software,
  no nuevos experimentos PLC. La prueba de enlace simbólico se omitió por falta
  de permisos para crear ese enlace en Windows.

La instantánea, respaldo y comprobante están en
`runtime/voice_integrity_fix_20261023/`. No se ejecutaron lotes reales, llamadas
al servicio ASR/LLM ni operaciones TIA/PLC durante esta corrección.

## Continuación del lote de desarrollo

1. Cerrar y volver a iniciar la aplicación para cargar el verificador corregido.
2. Abrir el lote existente `VCLEAN_DEV_20261023_001` desde el control de voz limpia.
3. Elegir **REINTENTAR ESTE ENSAYO** e indicar, por ejemplo:
   «Corrección del verificador de rutas de audio; continuar el ensayo guardado».

La rama correspondiente a `BLOCKED` con evaluación `PENDING` continúa la
evaluación del mismo ensayo guardado. No requiere otra grabación ni regenerar
su programa. No editar manualmente los estados o los hashes del manifiesto.

## Identidad experimental

Este lote está identificado como `DEVELOPMENT_VALIDATION` / `DEVELOPMENT_TRIAL`;
sus resultados no constituyen los datos formales de voz de la tesis.

El archivo corregido pertenece al inventario congelado de V4. El manifiesto
original se conserva intacto para proteger la identidad de los resultados TEXT
históricos. Antes de una campaña formal con el verificador corregido, se debe
documentar y registrar una nueva revisión experimental y su relación con V4.
Esta corrección no actualiza silenciosamente el freeze ni reclasifica ensayos.
