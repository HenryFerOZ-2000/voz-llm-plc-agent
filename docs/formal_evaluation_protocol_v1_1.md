# Protocolo de evaluación FORMAL v1.1 — estímulos de voz pareados clean/noisy

Extiende el [protocolo v1](formal_evaluation_protocol_v1.md) (`formal-v1.0`, que se conserva intacto como freeze
preliminar). Lo único que cambia es **cómo se producen los estímulos de voz**. El benchmark v3, los 32 Oracles, el
prompt, los intents, el generador, el Runtime PLCSIM, el MASTER, los mapas y la lógica de evaluación funcional son
los mismos de v1.

> **Estado: CONGELADO (`formal-v1.1`).** Fuente de verdad: `data/software_freeze_manifest.json`
> (`freeze_id = FORMAL_V1_1`, `parent_freeze = formal-v1.0`, motivo "paired reproducible voice stimuli").

| Elemento | Valor |
|---|---|
| Commit del software congelado (`git_commit`) | `95cd530686d1738dfbcfbe5ce2c896464277077f` (rama `main`) |
| Tag | `formal-v1.1`. Apunta al commit del freeze, que solo añade el manifiesto y esta documentación |
| Alcance congelado | 342 archivos versionados, 32 Oracles FROZEN/APPROVED, benchmark v3, MASTER `4b2e5446…64fd` FORMAL_READY |
| Suite al congelar | 1364 passed, 0 failed, 7 skipped |
| Ruido maestro | `formal_assets/audio/industrial_noise_master.wav`, SHA-256 `965e43af9baa4372e7c7d6283452e6e2a673d08aea00467af8a0c1774ce73fb5`, WAV PCM s16 mono 16 kHz, 194.352 s, pico −1.94 dBFS, sin clipping |
| Original | `formal_assets/audio/industrial_noise_original.mp3`, SHA-256 `36d9cc0f9e89bf284a25198d8c36a45183b1c4c7c08c5476d03ec69a05cdd704` (MP3 24 kHz estéreo 160 kb/s) |
| Procedencia | Pixabay, con licencia **Pixabay Content License**. La URL exacta de descarga consta en el Zone.Identifier del archivo descargado: `https://cdn.pixabay.com/download/audio/2022/02/07/audio_2c27218869.mp3?filename=freesound_community-general-fusion-industrial-workshop-factory-ambience10-heavy-machine-hum-changes-in-middle-with-alarm-siren-bg-activity-17218.mp3`. Búsqueda: `https://pixabay.com/es/sound-effects/search/ruido%20industrial/`. Autor y título no verificados: solo aparecen en el nombre del archivo servido |
| Conversión | FFmpeg 9.0.2 (Gyan.FFmpeg, winget): `ffmpeg -i industrial_noise_original.mp3 -map 0:a:0 -ac 1 -ar 16000 -c:a pcm_s16le -map_metadata -1 -fflags +bitexact -flags:a +bitexact industrial_noise_master.wav`. Solo decodifica, mezcla a mono, remuestrea y pasa a PCM16; sin recorte, normalización ni filtrado. Reproducible byte a byte |
| Revisión humana | `no_intelligible_speech = CONFIRMED`, revisado por Henry Ochoa el 2026-10-13T11:54:52; master aprobado por Henry Ochoa |

## 1. Diseño

| Modalidad | Celdas | Origen del estímulo |
|---|---|---|
| TEXT | 96 | comando canónico de la variante (sin cambios respecto a v1) |
| VOICE_CLEAN | 96 | **96 locuciones humanas únicas**: una por caso × variante |
| VOICE_NOISE | 96 | **derivado** de la misma locución clean + ruido maestro a SNR fija |
| **Total** | **288** | un ensayo FORMAL por celda |

**Pareado a nivel de señal.** VOICE_CLEAN y VOICE_NOISE de una celda usan la misma grabación. El noisy se calcula
así: `clean + g·ruido`, con un segmento del ruido maestro elegido de forma determinista. La única diferencia entre
ambas condiciones es, entonces, el ruido añadido. No varían ni la locución, ni el hablante, ni la prosodia, ni el
micrófono. Así, ΔWER (noise − clean) y la caída de éxito semántico/funcional se atribuyen al ruido. Grabar de nuevo
para VOICE_NOISE está **prohibido**.

## 2. Estímulos

Cada celda se graba una sola vez y produce estos archivos en `results/formal_audio/<caso>/<variante>/`:

| Archivo | Contenido |
|---|---|
| `capture_raw.wav` | captura tal cual |
| `clean_stimulus.wav` | WAV PCM s16, mono, 16 kHz; copia byte a byte si la captura ya es canónica. Nunca se remuestrea; si la frecuencia es otra, la celda se rechaza |
| `noise_stimulus.wav` | generado **inmediatamente después** de congelar el clean y **antes** de cualquier ASR |
| `audio_manifest.json` | hashes SHA-256 de los tres WAV y del ruido maestro, offset, SNR objetivo y medida, RMS, ganancias, pico, clipping, método de voz activa, versión de mezcla, hablante, freeze y benchmark |

Además, `audio_corpus_manifest.json` recoge el estado de las 96 celdas. Los estados posibles son
`NOT_RECORDED`, `PAIR_READY`, `USED_CLEAN` y `USED_CLEAN_AND_NOISE`, cada uno con los usos (trial_id).

Parámetros congelados (`config/formal_audio_config.json`):

- **SNR objetivo: 10.0 dB**, fija. **No se cambia después de ver resultados del ASR.**
- **Tolerancia: ±0.25 dB.** Fuera de ella, el estímulo se aborta.
- **Voz activa:** `ENERGY_FRAMES_TRIM_V1`. Tramas de 20 ms. Umbral = máx(RMS de trama máx. − 30 dB, 50). Región
  activa = de la primera a la última trama activa.
- **Mezcla:** `PAIRED_ACTIVE_RMS_SNR_V1`, con `g = RMS_voz / (RMS_ruido · 10^(SNR/20))` sobre la región activa.
- **Anti-clipping:** una única ganancia global posterior, que no altera la SNR. Si aun así hay saturación, el
  estímulo se aborta.
- **Offset:** `SHA256(caso|variante|FORMAL_V1_1) mod longitud_del_master`. Si hace falta, el segmento recorre el
  master en bucle, y ese bucle queda registrado.
- **Determinismo:** la misma captura da el mismo clean y un noisy idéntico byte a byte. La verificación de integridad
  regenera el noisy y compara los hashes.

## 3. Inmutabilidad

- El audio nunca se sustituye en silencio.
- Regrabar **antes** de usar la celda exige una decisión humana explícita (`rerecord_cell`: quién y por qué). El
  intento anterior se archiva y no se borra.
- Una celda queda marcada como usada **antes del ASR**. Desde ese momento la pareja es **INMUTABLE**.
- Los WAV no se versionan en Git (`results/` y `formal_assets/` están ignorados; `*.wav` también).

## 4. Ensayos

**VOICE_CLEAN**
1. Si la celda no está grabada, se graba una vez.
2. Se congela el clean.
3. Se genera y verifica el noisy.
4. El ASR recibe **exactamente** `clean_stimulus.wav`.

`trial.json` registra `audio_condition`, `audio_source_path`, `audio_sha256`, `paired_audio_sha256` y
`audio_manifest_sha256`, además de la transcripción, el comando efectivo y los tiempos del ASR.

**VOICE_NOISE**
- Nunca abre el micrófono.
- Exige una pareja íntegra, del mismo caso, variante, benchmark y freeze, cuyo clean ya se haya usado en un ensayo
  VOICE_CLEAN FORMAL.
- Registra `audio_source_clean_sha256`, `audio_sha256`, el trial clean pareado, `target_snr_db` y `measured_snr_db`.
- Si falta la pareja o está alterada: **PRECHECK ABORT antes del ASR/LLM**.

Sin corrección humana del ASR. Las reglas de PASS / FAIL / REVIEW / INFRASTRUCTURE_ERROR son las de v1. Un
reintento técnico por INFRASTRUCTURE_ERROR reutiliza **el mismo WAV**.

## 5. Lotes (orden determinista D01 V1 … P12 V3, un manifiesto por lote)

| Lote | Tipo | Comportamiento |
|---|---|---|
| EJECUTAR LOTE TEXT | automático | igual que en v1 |
| EJECUTAR LOTE VOICE_CLEAN | asistido | ver detalle abajo |
| EJECUTAR LOTE VOICE_NOISE | automático | ver detalle abajo |

**Lote VOICE_CLEAN.** Para cada celda sin grabar, la ventana muestra:
- el progreso X/96, el caso, la variante y el comando exacto;
- el estado del clean, de la pareja y del ensayo.

El operador pulsa *GRABAR Y EJECUTAR* y luego *DETENER Y EJECUTAR*. El ensayo arranca solo y el lote avanza a la
celda siguiente. *PAUSAR LOTE* no graba nada.
- PASS / FAIL / REVIEW: el lote continúa.
- INFRASTRUCTURE_ERROR: el lote se pausa.
- Un ensayo completado nunca se repite, y un audio usado nunca se regraba.

**Lote VOICE_NOISE.** El preflight exige **PAIRS READY: 96 / 96**. Si no se cumple, muestra la lista de celdas que
faltan y no empieza. Por lo demás:
- usa el mismo motor que el lote TEXT (secuencial, MASTER fresco por ensayo, pausa/reanudación);
- nunca reintenta un resultado funcional;
- solo admite un reintento técnico explícito de infraestructura;
- nunca usa micrófono, grabación ni selección de dispositivo de audio.

Para los lotes de voz, `batch_summary.csv/json` añade los hashes del audio, la SNR, la transcripción y el WER. Con
eso se calculan WER clean/noise y ΔWER. Las métricas primarias no cambian. La CSV de TEXT conserva exactamente sus
columnas.

El panel **FORMAL AUDIO CORPUS** muestra:
- los conteos de grabados, parejas listas, ensayos clean y ensayos noise;
- la SNR objetivo;
- el estado del master (READY / MISSING) y de la integridad;
- la tabla de las 96 celdas, con opción de reproducir clean/noisy y ver los metadatos (solo lectura).

## 6. Ruido maestro industrial (aprobado; ver la tabla del inicio)

- **Ubicación:** `formal_assets/audio/industrial_noise_master.wav`. Está fuera de Git; solo se versiona su SHA-256.
- **Propiedades:**
  - WAV PCM 16 bits, mono, 16 kHz;
  - **≥ 60 s**;
  - **sin voz inteligible**;
  - origen y licencia documentables. Es preferible una grabación propia del ambiente del laboratorio o la planta.
- **Restricciones:** no se descarga de Internet ni se genera artificialmente.
- **Aprobación humana:**
  ```
  .venv\Scripts\python.exe scripts\formal_audio.py approve-master --approved-by "Nombre" --provenance "..." --license "..."
  ```
  El comando valida el formato y la duración, y registra el SHA-256, quién lo aprobó y cuándo en
  `config/formal_audio_config.json`. Después de aprobarlo, cualquier cambio en el archivo bloquea FORMAL.

## 7. Congelamiento v1.1 (realizado)

Requisitos previos:
- suite en verde;
- pipeline de audio probado;
- `scripts\formal_audio.py status` con el master READY;
- 0 ensayos FORMAL.

Pasos:
1. Hacer commit de la aprobación y construir el manifiesto:
   ```
   .venv\Scripts\python.exe scripts\formal_freeze.py build --suite-passed N --suite-failed 0 --suite-skipped N ^
       --tag formal-v1.1 --freeze-id FORMAL_V1_1 --parent-freeze formal-v1.0 ^
       --reason "paired reproducible voice stimuli" --with-audio
   ```
   El manifiesto añade la sección `audio`: SNR, versión de mezcla, método de voz activa, salt, hashes de la
   configuración y del código de audio, y `industrial_noise_master_sha256`. `validate_freeze` comprueba ese mismo
   master en cada punto de entrada FORMAL.
2. Crear el tag anotado `formal-v1.1` con el mensaje "Formal evaluation freeze v1.1 — paired clean/noisy voice
   stimuli".
3. Hacer push del tag y de la rama canónica.

## 8. Respaldo

Tras cada lote de voz, y al cerrar cada sesión:

```
.venv\Scripts\python.exe scripts\backup_results.py backup --dest <medio externo>
.venv\Scripts\python.exe scripts\backup_results.py verify --target <carpeta del respaldo>
```

El respaldo copia `results/formal_audio`, `results/experiments` y `results/batches`, y escribe
`backup_manifest.json` con el SHA-256 de cada archivo, WAV incluidos. Un respaldo nunca se sobrescribe.
