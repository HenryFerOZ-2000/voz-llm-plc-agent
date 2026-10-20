# Campaña discreta de tesis — THESIS_DISCRETE_V2

Alcance aprobado por Henry el 20 de octubre de 2026, después de consultar con su tutor.
Se evalúan D01–D20 del benchmark v3: 3 variantes lingüísticas por caso y las modalidades
TEXT, VOICE_CLEAN y VOICE_NOISE. Son **180 celdas**, 60 por modalidad y un ensayo por celda.
El catálogo completo y los Oracles permanecen intactos. PID continúa como desarrollo para
un artículo; no integra esta campaña ni es condición para terminar la tesis discreta.

## Qué se demuestra

El recorrido evaluado es comando → ASR cuando corresponde → interpretación LLM → resolución
del mapa IO → IR/SCL → verificación → compilación TIA V18 → descarga a PLCSIM Advanced →
Oracle de estímulos/respuestas y comprobaciones de parada. Generar o compilar no equivale a
demostrar el comportamiento funcional. No se atribuye validación física a la simulación.

La plataforma es CPU 1516-3 PN/DP, S7-1500, TIA Portal V18 y PLCSIM Advanced V5.
Normal conserva su proyecto S71500_Prueba. Cada ensayo experimental usa una copia nueva del
MASTER aprobado y archiva el proyecto antes de descargar. No ejecutar los ensayos formales
desde Modo Normal ni desde Prueba de I/O; esas herramientas sirven para comprobaciones manuales.

## Identidad y mapas

- Campaña y freeze: `THESIS_DISCRETE_V2`; manifiesto activo: `data/software_freeze_discrete_v2.json`.
- El manifiesto anterior `data/software_freeze_manifest.json` se conserva como histórico.
- El código completo queda congelado, incluido el PID que comparte módulos. Desarrollar el
  artículo en una copia/rama separada; cambiar código, prompts o configuración invalida las guardas.
- El mapa experimental se selecciona por capacidad mediante `config/experiment_maps.json`:
  banco base preferido y mapa de simulación cuando el banco no cubre el caso. No se usa
  automáticamente el mapa activo de Normal. La selección y los bindings se congelan por ensayo.
- Para la redacción, usar el mapa efectivamente registrado en `trial.json` y
  `io_map_snapshot.json`, sus direcciones, roles, permisos y hashes. No afirmar que todos los
  casos usan exactamente el mismo mapa ni que una dirección proviene del PLC físico conectado.

## Antes de comenzar

1. Reiniciar la aplicación para cargar esta versión. Abrir PLCSIM Advanced y arrancar
   `TESIS_PLC_SIM` con la configuración habitual. Conservar TIA disponible y aceptar
   personalmente las solicitudes de acceso Openness si aparecen.
2. Ejecutar `.venv\Scripts\python.exe scripts\thesis_campaign.py --check-runtime --write-report`.
   Debe indicar `ready: true`. El informe y las 180 celdas planificadas quedan en
   `runtime/thesis_discrete_v2/`. Esta orden no llama al LLM ni descarga programas.
   Que `noise_phase_ready` sea falso inicialmente es normal: todavía faltan las grabaciones.
3. En Experimentación, abrir **LOTE TEXT**. Seleccionar fase **FORMAL**, D01–D20,
   variantes V1/V2/V3. Dejar P01–P12 desmarcado y el rango vacío. El total debe ser **60**.
4. Usar un participante anónimo válido, por ejemplo `S01`. No editar el mapa, el prompt,
   el modelo ni el programa durante la campaña. No usar Prueba de I/O mientras el Oracle trabaja.

## Orden de ejecución

1. **TEXT (60):** iniciar el lote y conservar todos sus resultados.
2. **VOICE_CLEAN (60):** abrir el lote de voz limpia con la misma selección y fase.
   Leer el comando exacto mostrado y usar **GRABAR Y EJECUTAR / DETENER Y EJECUTAR**.
   La aplicación conserva una locución humana por caso/variante. No corregir la transcripción.
3. **VOICE_NOISE (60):** iniciar solo después de terminar voz limpia y tener **60/60** parejas
   íntegras con clean ya usado. Es automático y nunca pide otra locución ni abre el micrófono.

Audio: PCM16 mono a 16 kHz. El noisy se deriva del mismo clean con el ruido industrial ya
aprobado, SNR 10 dB ±0,25 dB y el algoritmo pareado existente. No cambiar la SNR después
de observar resultados. El nuevo corpus vive en `results/formal_audio_discrete_v2`.
Los pilotos anteriores de `results/development_audio` no cuentan como pruebas formales.

PASS, FAIL y REVIEW se conservan. Las aclaraciones formales no se contestan para obtener PASS.
Un error de infraestructura pausa el lote; corregir su causa y registrar un reintento técnico
con motivo, conservando el intento anterior y el mismo audio. No repetir fallos funcionales
para escoger una respuesta favorable. PAUSAR deja terminar el ensayo actual y permite reanudar.

## Evidencia y resultados de la tesis

Resultados nuevos e históricos permanecen en `results/experiments` y `results/batches`;
los nuevos llevan `campaign_id` y `software_freeze_id`. El número de ensayo continúa sin
reutilizar identificadores. Un lote de la campaña anterior no se puede reanudar como si fuera nuevo.

Para analizar esta campaña, filtrar **FORMAL_TRIAL + FORMAL + benchmark v3 +
campaign_id THESIS_DISCRETE_V2 + D01–D20**. No mezclar los 52 PASS/8 FAIL del lote de texto
del 13 de octubre con los ensayos nuevos. Se conservan como antecedentes de otra versión.

Presentar por modalidad y complejidad: éxito semántico, compilación, comportamiento funcional,
comprobaciones de parada, aclaraciones, categorías de fallo, tiempos y WER de voz. Informar
infraestructura y etapas no ejecutadas por separado, con sus denominadores. Una prueba local
aprobada o una auditoría de preparación no sustituyen los 180 resultados experimentales.

Después de cada lote:

```powershell
.venv\Scripts\python.exe scripts\audit_trial_persistence.py --help
.venv\Scripts\python.exe scripts\backup_results.py backup --dest runtime\backups
```

El respaldo de resultados incluye el nuevo corpus. Para protegerlo frente a pérdida del disco,
copiar el respaldo verificado a otra unidad. El punto anterior a la preparación está en
`runtime/backups/before_thesis_discrete_20261020/RESTORE.md`; no incluye una instantánea del
proyecto TIA Normal abierto ni el secreto `.env`.

## Límites del cierre

Esta preparación no ejecuta los ensayos formales ni garantiza que todos obtengan PASS.
No cambia el intérprete ni la lógica discreta para satisfacer resultados esperados.
La conservación pendiente de ajustes PID no bloquea esta campaña. La tesis debe describir
el alcance discreto evaluado y reservar PID, plantas físicas y generalización adicional
para el artículo/trabajo futuro. Verificar con el tutor que objetivos y conclusiones usen ese alcance.
