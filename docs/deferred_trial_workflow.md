# Ensayos con evaluación diferida: guía de uso

Esta guía explica cómo generar un ensayo y evaluarlo después, en otro momento. El fundamento
metodológico está en `docs/experimental_design_v2.md`, sección 12.1.

Actualización del producto: los ensayos nuevos de la GUI usan el motor `PRODUCT_SHARED_V1` y conservan el mapa declarado con `PRODUCT_DECLARED_V1`. Congelan su identidad y verifican su integridad antes de evaluar. La evaluación experimental del PID nativo queda pendiente de soporte y se bloquea antes de TIA, sin veredicto funcional. Los casos históricos de supervisión conservan su recorrido. Véase [motor compartido](26_motor_producto_compartido.md).

## Antes de empezar

- TIA Portal V18 instalado con Openness, y el usuario dentro del grupo *Siemens TIA Openness*.
- S7-PLCSIM Advanced V5 con la instancia `TESIS_PLC_SIM` en RUN, CPU S7-1500.
- Para ahorrar RAM: **no tengas abierto TIA Portal con interfaz gráfica mientras evalúas.** El
  evaluador abre su propia sesión de TIA, sin interfaz.

## Flujo oficial: EJECUTAR ENSAYO COMPLETO

A partir de la Fase 4A-FINAL, el flujo experimental oficial es **INVESTIGATOR-TRIGGERED AUTOMATED
TRIAL EXECUTION**:

1. En Experimentación, elige **Caso**, **Variante**, **Modalidad** y **Fase**.
2. Pulsa **EJECUTAR ENSAYO COMPLETO**. El comportamiento depende de la modalidad:
   - **TEXT:** usa el texto exacto de la variante; no se abre el micrófono.
   - **VOICE_CLEAN:** se abre la captura. El hablante (pseudónimo S01…) lee la frase de referencia:
     GRABAR → DETENER. Si cancelas antes de grabar, no se crea ningún ensayo.
   - **VOICE_NOISE:** usa el audio clean del ensayo VOICE_CLEAN emparejado, el perfil de ruido y el
     SNR. En DEVELOPMENT, el perfil y el SNR se eligen en el panel de voz con
     *Perfil de ruido (DEV)* y *SNR (DEV)*. En FORMAL se leen de `experimental_design.json`, en
     solo lectura.
3. A partir de ahí todo es automático: ASR congelado (voz) → generación → TIA en `tiaw/Txxxx` →
   compilación → `.zap18` verificado → PLCSIM → Oracle.
4. Al final se muestra la tabla de veredicto (Voice Capture, ASR, WER, Semantic, …, FINAL) con el
   botón **VER DETALLE**. **El siguiente ensayo no se inicia solo.**

Hay herramientas para casos especiales:
- **GENERAR SOLO** (DEVELOPMENT/DEBUG);
- **EVALUAR ENSAYO GUARDADO**, para retomar una evaluación que quedó pendiente o reintentar una con
  INFRASTRUCTURE_ERROR.

Evidencia de voz en la carpeta del ensayo (todo incluido en el `integrity_manifest.json`):

```
audio/
  reference.txt                 frase de referencia
  clean_audio.wav               RAW (antes del ASR); en VOICE_NOISE, copia identica del clean emparejado
  noise_profile_reference.json  (VOICE_NOISE) perfil, hash, SNR, regla de offset
  voice_noise.wav               (VOICE_NOISE) mezcla determinista que recibio el ASR
  asr_result.json               transcripcion congelada, modelo, latencia
```

## 0. Dos proyectos TIA independientes

La aplicación trabaja con dos proyectos TIA distintos. Ambos se guardan en
`config/tia_projects.json`, cada uno con sus propias claves.

| | PROYECTO TIA — MODO NORMAL | TIA MASTER — EXPERIMENTACIÓN |
|---|---|---|
| Clave | `tia.normal_project` (`path`, `validation`) | `tia.experiment_master` (`path`, `hash`, `validation`, `status`) |
| Uso | Modo Normal: comando → importar → PLC_Agent_IO → compilar; CARGAR PROGRAMA AL PLC descarga | Plantilla de Experimentación: cada evaluación trabaja sobre una copia nueva |
| ¿Se modifica? | Sí | **Nunca** |

Reglas que el software hace cumplir:
- **El MASTER no puede ser el proyecto Normal**, ni otro `.ap18` de la misma carpeta. Crea una
  copia aparte del proyecto, por ejemplo con *Guardar como* en TIA: `S71500_MASTER`.
- **El Modo Normal nunca usa el MASTER.** Si alguien lo intenta, la operación se rechaza con
  `NORMAL_PROJECT_IS_EXPERIMENT_MASTER`.
- **Experimentación nunca compila en el proyecto Normal**
  (`EXPERIMENT_MODE_NEVER_MODIFIES_NORMAL_PROJECT`). El pipeline inmediato antiguo, que usan
  EJECUTAR ENSAYO y el batch, solo funciona si en `tia_openness_config.json` pones
  `legacy_immediate_experiment_pipeline: true`.
- **La evaluación solo parte del snapshot del MASTER**, nunca de un ensayo anterior.

`tia_openness_config.json → project_path` se mantiene únicamente como espejo del proyecto Normal,
para el código que ya lo leía. Si `tia.normal_project` aún no existe, se usa ese valor y la
configuración lo indica como fuente `legacy`.

## 1. Configurar el TIA MASTER (una vez)

1. En el panel izquierdo, pulsa **Configurar TIA V18**.
2. En la sección **TIA MASTER — EXPERIMENTACIÓN**, pulsa **Seleccionar Master** y elige el `.ap18` del MASTER,
   que debe ser distinto del proyecto del Modo Normal.
3. Pulsa **Validar Master**. Openness abre el MASTER, describe su contenido y crea un snapshot
   con `Project.Archive`, guardado en `tia_master/snapshots/*.zap18`. **El MASTER no se guarda
   ni se modifica.**
4. Revisa el resultado:
   - CPU, modelo, interfaz X1, IP y PLC_Agent_IO;
   - estado: `DEVELOPMENT_READY`, `FORMAL_READY` o `INVALID`;
   - hash del snapshot y fecha de validación.
5. Si aparece `MASTER_CONTAINS_FUNCTIONAL_LOGIC`, el MASTER tiene bloques que la aplicación no
   administra. Se aceptan en desarrollo (`DEVELOPMENT_READY`), pero nunca en un ensayo formal.

Si el MASTER cambia después de validarlo, la evaluación se bloquea con
`MASTER_CHANGED_SINCE_VALIDATION`: vuelve a pulsar **VALIDAR MASTER**.

### Qué es APP_MANAGED

La aplicación administra estos objetos:
- los bloques que emite el generador (`FUNCTION_BLOCK "PLC_PRG"`, `DATA_BLOCK "DB_PLC_PRG"`,
  `ORGANIZATION_BLOCK "Main"`);
- los bloques declarados en el `program.scl` del ensayo;
- la fuente externa `siemens_source.scl`;
- la tabla `PLC_Agent_IO`.

Solo esos objetos se reemplazan o eliminan, y **solo dentro de la copia del ensayo**. El
hardware, la red y cualquier otro bloque nunca se tocan.

## 2. GENERAR ENSAYO

1. Activa el modo **Experimentación**.
2. Elige **Caso**, **Variante**, **Modalidad** y **Fase**. Para el baseline, la fase es
   **BASELINE**.
3. Pulsa **GENERAR ENSAYO**. Con la modalidad TEXT se usa siempre el texto exacto de la variante.

El sistema interpreta el comando con el LLM, asigna las E/S, congela el snapshot, genera
IR y SCL, verifica el resultado y guarda los artefactos y el `integrity_manifest.json`. **No abre
TIA.** El ensayo aparece en **Ensayos generados** con Generación = SUCCESS y Evaluación = PENDING.
Puedes cerrar la aplicación y evaluarlo otro día.

## 3. EVALUAR ENSAYO GUARDADO

1. Selecciona el ensayo en la lista y pulsa **EVALUAR ENSAYO GUARDADO**. También puedes pulsar
   **EVALUAR SIGUIENTE PENDIENTE**.
2. Se abre un resumen con el caso, la variante, el comando, el Oracle, el MASTER y la
   integridad, junto con el resultado del **precheck**. Si algo falla, el botón queda
   deshabilitado.
3. Pulsa **INICIAR EVALUACIÓN**. A partir de ahí todo es automático:
   1. copia del MASTER;
   2. PLC_Agent_IO;
   3. importación de `program.scl`;
   4. compilación;
   5. `.zap18`;
   6. descarga a PLCSIM y Start Module;
   7. CPU RUN;
   8. Oracle.
4. Al terminar se muestra la tabla de veredicto:

   | Etapa | Valores |
   |---|---|
   | Semantic | PASS / FAIL |
   | I/O Allocation | PASS / FAIL |
   | IR | PASS / FAIL |
   | Compilation | PASS / FAIL |
   | TIA Archive | OK / ERROR |
   | Download | PASS / FAIL |
   | Runtime | PASS / FAIL |
   | Functional | PASS / FAIL / REVIEW |
   | Safety | PASS / FAIL |
   | FINAL | PASS / FAIL / REVIEW / INFRASTRUCTURE_ERROR |

La GUI **nunca** encadena el siguiente ensayo: cada evaluación la inicia el investigador.

**Si el resultado es INFRASTRUCTURE_ERROR** (TIA cayó, PLCSIM no estaba disponible, etc.):
1. arregla el entorno;
2. selecciona el ensayo y pulsa **REINTENTAR EVALUACIÓN**;
3. indica el motivo del reintento.

El intento anterior se conserva. Los fallos semánticos, de E/S, de IR, de compilación,
funcionales y de seguridad **no se reintentan**.

### Desde la línea de comandos (misma lógica)

Ejecuta los comandos desde `src/`:

```
..\.venv\Scripts\python.exe -m trial_experiments.deferred_evaluator --validate-master
..\.venv\Scripts\python.exe -m trial_experiments.deferred_evaluator --list
..\.venv\Scripts\python.exe -m trial_experiments.deferred_evaluator --next
..\.venv\Scripts\python.exe -m trial_experiments.deferred_evaluator <carpeta_del_ensayo> --precheck
..\.venv\Scripts\python.exe -m trial_experiments.deferred_evaluator <carpeta_del_ensayo>
..\.venv\Scripts\python.exe -m trial_experiments.deferred_evaluator <carpeta_del_ensayo> --retry-reason "TIA reiniciado"
..\.venv\Scripts\python.exe -m trial_experiments.deferred_evaluator --consolidate BASELINE
```

## Workspace TIA corto (límite de 143 caracteres)

TIA Portal V18 rechaza rutas de más de **143 caracteres**. Es un límite real, observado en
`Project.Archive`: *"A maximum of 143 characters is allowed"*. Las rutas de resultados son mucho más
largas, así que TIA **solo trabaja dentro de un workspace corto**:

```
<project_root>/tiaw/            (configurable: deferred_workspace_root en tia_openness_config.json)
  _workspaces.json              registro persistente de IDs (T0001, T0002, ...; nunca se reutilizan)
  T0001/
    p/                          destino de Projects.Retrieve (copia NUEVA del snapshot MASTER)
    s.scl                       copia verificada por hash del program.scl congelado (fuente que importa TIA)
    T0001.zap18                 Project.Archive del proyecto del ensayo
    archived.json / proceed.json  handshake entre el bridge y Python
```

- **ID corto.** Cada intento de evaluación recibe un ID nuevo e independiente del `trial_id`, que
  nunca aparece en una ruta que reciba TIA. `trial.json` y `tia_project_manifest.json` guardan la
  relación entre `trial_id` y `tia_workspace_id`.
- **Comprobación previa.** Antes de llamar a TIA se calcula la longitud de cada ruta que verá TIA:
  la carpeta destino de Retrieve, el proyecto recuperado (en el peor caso, con una subcarpeta que
  lleva el nombre real del proyecto dentro del snapshot), la fuente que se importa y el archivo
  `.zap18`. Si alguna supera el límite, la evaluación se aborta con `TIA_PATH_TOO_LONG` y se
  registra la operación, la ruta, su longitud y el límite.
- **Nombre del snapshot MASTER.** Es corto (`M<aammddhhmmss>.zap18`) porque el proyecto que
  contiene se llama `<nombre>.ap18` y cada Retrieve hereda ese nombre.
- **Handshake.** En la misma sesión de TIA, sin un segundo Retrieve:
  1. TIA compila, guarda y archiva `T0001.zap18`;
  2. el bridge escribe `archived.json`;
  3. Python copia el `.zap18` a `<ensayo>/evaluation/attempt_NNN/tia/<trial_id>.zap18` y exige
     el mismo SHA-256 y un tamaño mayor que 0;
  4. solo entonces escribe `proceed.json` con `download: true`, y el bridge descarga a PLCSIM.

  Si la copia o su verificación fallan, el resultado es `TIA_ARCHIVE_COPY_FAILED` o
  `TIA_ARCHIVE_INTEGRITY_FAILED`: no hay descarga ni Oracle, y el intento termina como
  INFRASTRUCTURE_ERROR.
- **Limpieza.** El workspace se borra automáticamente solo cuando se cumplen todas estas
  condiciones:
  - la evidencia está copiada y verificada;
  - el manifiesto está escrito;
  - TIA está cerrado;
  - el intento está en un estado final que no es INFRASTRUCTURE_ERROR.

  Con INFRASTRUCTURE_ERROR, el workspace se conserva para diagnóstico. Para limpiar a mano:
  `python -m trial_experiments.deferred_evaluator --cleanup-workspaces [--include-kept]`. Nunca
  borra workspaces activos; las carpetas huérfanas solo se informan.
- **Rutas largas.** Las rutas largas de la evidencia las maneja únicamente la capa de filesystem de
  Python (prefijo `\\?\` en Windows). TIA nunca recibe rutas largas.
- **Permiso de TIA Openness.** La primera vez que un bridge nuevo o recompilado se conecta, TIA
  muestra la ventana **"Openness access"**. Hay que aceptarla (Sí / Sí a todo); si no, la operación
  queda esperando.

## Estructura de un ensayo

```
results/development_baseline_v2/D03/V1/D03_V1_TEXT_DEV_001/
  trial.json                 generation{status} + evaluation{status, attempt, attempts[], final_verdict}
  command.txt
  semantic_output.json
  variables.json
  program.scl
  io_map_snapshot.json
  generation_report.json
  integrity_manifest.json
  evaluation/
    attempt_001/
      compile_report.json
      download_report.json
      runtime_report.json
      oracle_trace.json
      evaluation_report.json
      tia/
        D03_V1_TEXT_DEV_001.zap18     copia verificada (SHA-256) del T000N.zap18 del workspace
        tia_project_manifest.json     trial_id, tia_workspace_id, rutas y longitudes, hashes
    attempt_002/              solo si hubo un reintento por INFRASTRUCTURE_ERROR
```

## Ciclo de vida

Estados de `trial.json` → `lifecycle_state`, en orden:

1. CREATED
2. PREPARING
3. IO_RESOLVED
4. EVALUATION_PENDING (generado)
5. EVALUATED

Además, `evaluation.status` toma uno de estos valores: PENDING, RUNNING, COMPLETED,
INFRASTRUCTURE_ERROR, INTEGRITY_FAILED o MASTER_INTEGRITY_FAILED.

El resultado final se registra en `final_status` (PASS / FAIL / REVIEW / INFRASTRUCTURE_ERROR).
Por debajo, cada intento recorre estas etapas: preparación del proyecto TIA, compilación, archivo,
descarga, runtime y Oracle. El estado de cada una queda en `stages` y en
`evaluation.attempts[]`.

## Consolidación

`--consolidate BASELINE` recorre los `trial.json` evaluados y regenera estos archivos:
- `baseline_trials.csv`;
- `baseline_summary.json`;
- `baseline_summary.md`;
- `baseline_failures.json`.

No calcula estadísticas formales.

## Persistencia del veredicto y limpieza del workspace

Orden de cierre de `evaluate_trial` (la limpieza es mantenimiento, nunca parte del resultado):

1. Veredicto (Oracle + precedencia de etapas).
2. Evidencias: `tia/tia_project_manifest.json`, `evaluation_report.json`, `oracle_trace.json`.
3. `trial.json` en UNA escritura atómica (temporal + `os.replace`): etapas, timing, `final_verdict`,
   `evaluation.status`, `evaluation.attempts[]`.
4. Verificación: se relee `trial.json`; si no es coherente, no se hace ningún mantenimiento.
5. Registro `tiaw/_workspaces.json`.
6. Limpieza del workspace (solo PASS/FAIL/REVIEW con `.zap18` verificado).

La limpieza primero intenta renombrar `tiaw/Tnnnn` (sondeo: en Windows falla si algún proceso, p.ej.
TIA Portal tras cerrar la sesión Openness, retiene un archivo dentro). Si falla —o si `shutil.rmtree`
falla (`PermissionError`, WinError 32)— el workspace queda `KEPT` con todos sus archivos y se registra
`workspace_cleanup` (`status = FAILED`, `error_type`, `error_message`, `workspace_path`, `timestamp`) en
el intento de `trial.json`, en `evaluation/attempt_NNN/workspace_cleanup.json` y en el registro. El
veredicto no cambia. Solo se borra `<tiaw>/<Tnnnn>` del propio ensayo e intento (nunca `tia_master/`,
`tia_projects/`, `results/`, la carpeta del MASTER ni otro workspace). Cuando el proceso libere el
archivo: `python -m trial_experiments.deferred_evaluator --cleanup-workspaces --include-kept`.

Una excepción inesperada ANTES de persistir el veredicto deja `evaluation/diagnostics/<stamp>_<fase>.json`
(tipo, mensaje, fase, trial_id, intento, traceback sin secretos) y `evaluation.last_unexpected_error`;
el ensayo sigue sin veredicto (el lote lo marca INTERRUPTED). Nunca se inventa un resultado.

### Recuperación de persistencia (ensayos históricos)

Ensayos cuyo Oracle terminó pero cuyo resultado no llegó a `trial.json` (`evaluation.status = RUNNING`,
`attempts = []`, `final_verdict = null`) se auditan en modo SOLO LECTURA:

```
.venv\Scripts\python.exe scripts\audit_trial_persistence.py D03_V1_TEXT_DEV_001 D03_V2_TEXT_DEV_001
.venv\Scripts\python.exe scripts\audit_trial_persistence.py --json D03_V1_TEXT_DEV_001 > audit.json
```

La auditoría no escribe nada, no llama al LLM, no genera SCL, no abre TIA/PLCSIM y no vuelve a ejecutar
el Oracle. Verifica identidad, hashes congelados, `evaluation_report.json`, intento, `.zap18`, MASTER y
registro del workspace, y muestra el registro reconstruido (`RECONSTRUCTIBLE`) sin aplicarlo. Aplicarlo
es una recuperación de persistencia (no un reintento ni una nueva generación) y exige autorización
explícita, respaldo previo de `trial.json` y registro de cada cambio; nunca se reemplaza el ensayo ni
se borran sus intentos.
