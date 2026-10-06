# Lote automático TEXT

## 1. Propósito

**EJECUTAR LOTE TEXT** (Modo Experimentación) ejecuta varios ensayos TEXT del benchmark v2 **uno por uno**,
sin intervención, hasta un máximo de 32 casos × V1–V3 = **96 ensayos**. Convive con
**EJECUTAR ENSAYO COMPLETO**, que se mantiene igual.

El lote **no es un pipeline nuevo**. Cada ensayo pasa exactamente por el mismo flujo que un clic en
EJECUTAR ENSAYO COMPLETO:

```
comando del benchmark → Semantic → I/O Allocation → IR → SCL      (generación, GUI: run_complete_trial)
→ copia fresca del MASTER → workspace tiaw/ propio → TIA → Compilation → Archive .zap18 verificado
→ Download → CPU RUN → Runtime → Oracle → Functional / Safety → FINAL   (deferred_evaluator.evaluate_trial)
```

El lote solo decide **qué ensayo sigue** y **qué hacer con su resultado**, y lo deja todo persistido.
Los estados de etapa salen siempre de `deferred_evaluator.trial_stage_summary(record)`, la misma fuente
que la vista de detalle y el resumen principal.

| Pieza | Archivo |
|---|---|
| Motor del lote (plan, manifiesto, reglas, resúmenes, guardas FORMAL) | `src/trial_experiments/text_batch.py` |
| Controlador y diálogo en la GUI | `src/gui.py` (`start_text_batch`, `_batch_run_next`, `TextBatchDialog`) |
| Pruebas | `tests/test_text_batch.py` |

El `batch_runner.py` antiguo (baseline de 60 ensayos, pipeline *inmediato* en el proyecto Normal) **no**
se reutiliza como motor. Solo se reutilizan sus helpers de integridad (`integrity_snapshot`).

## 2. DEVELOPMENT y FORMAL

| | DEVELOPMENT | FORMAL |
|---|---|---|
| Uso | validar el lote, pilotos, subconjuntos | resultados oficiales de la tesis |
| Selección | cualquier subconjunto de casos y variantes | la que se elija, pero todas las guardas deben pasar |
| IDs de ensayo | `Dxx_Vy_TEXT_DEV_NNN` | `Dxx_Vy_TEXT_NNN` |
| Ensayos | `results/development_validation_v2/...` | `results/experiments/...` |
| Lote | `results/batches/TEXT_DEV_<fecha>_NNN/` | `results/batches/TEXT_FORMAL_<fecha>_NNN/` |

Nunca se mezclan: cada lote tiene una sola fase, y sus resúmenes solo contienen sus propios ensayos.

**Guardas FORMAL.** Si cualquiera falla, el lote no se crea y se muestra qué falta:
- software congelado (`software_freeze_manifest`, igual que un ensayo FORMAL individual);
- benchmark íntegro: v2, 32 casos y 96 variantes consistentes;
- los 32 Oracles FROZEN con su hash;
- diseño experimental válido;
- MASTER FORMAL_READY con snapshot íntegro, destino solo PLCSIM y memoria (`environment_precheck`);
- PLCSIM Runtime conectado;
- árbol Git limpio, con el commit registrado en el manifiesto;
- comandos TEXT idénticos a los del benchmark congelado;
- todos los casos evaluables con el Runtime actual. Hoy P01–P12 requieren extensión del Runtime, así que un FORMAL debe limitarse a D01–D20.

## 3. Ejecución estrictamente secuencial

- Nunca hay dos ensayos ni dos operaciones TIA/PLCSIM simultáneas. El ensayo N+1 se programa **solo**
  desde el callback de fin del ensayo N, después de persistir su resultado. Si hay cualquier operación en
  curso, el lote espera.
- Cada ensayo es independiente: copia fresca del MASTER congelado, workspace corto propio y `.zap18` propio
  (`<ensayo>/evaluation/attempt_NNN/tia/<trial_id>.zap18`). Ningún ensayo parte de otro.
- **Antes de generar cada ensayo** se ejecuta el mismo `environment_precheck` del flujo individual. Si el
  entorno no está listo, el lote se pausa **sin gastar el ensayo** (no se llama al LLM).
- **Modo desatendido.** Durante la generación ningún diálogo bloquea:
  - los mensajes se registran (también en `trial.json → batch_dialogs`);
  - las confirmaciones responden "no";
  - las **aclaraciones quedan sin responder** (el ensayo registra `clarification_requested`).

  Es el mismo protocolo del baseline anterior: en un lote nadie responde.
- Si una celda ya tiene ensayos previos, el nuevo se enlaza (`repeat_of_trial_id`) con el motivo
  `Lote <batch_id>`. El anterior nunca se toca.

## 4. Resultado de cada ensayo

| Resultado persistido | Entrada del lote | El lote… |
|---|---|---|
| FINAL **PASS** | COMPLETED | continúa |
| FINAL **FAIL** (Semantic, IR, Compilation, Functional o Safety) | COMPLETED | **continúa**; es un dato experimental y nunca se reintenta |
| FINAL **REVIEW** | COMPLETED | continúa |
| **INFRASTRUCTURE_ERROR** (TIA, PLCSIM, memoria, archive no verificable…) | INFRASTRUCTURE_ERROR | **se pausa**: "LOTE PAUSADO POR INFRASTRUCTURE_ERROR" |
| Oracle no ejecutable hoy (P01–P12: requiere extensión del Runtime) | NOT_EVALUABLE | continúa; se genera (Semantic/IR son datos), no se abre TIA |
| Precheck de evaluación no superado por el entorno | BLOCKED | se pausa |
| Ensayo cortado (cierre de la GUI o caída a mitad) | INTERRUPTED | se pausa y lo reporta |

**Reintento: solo explícito** (REINTENTAR ESTE ENSAYO, con motivo obligatorio). Sigue la política de
`deferred_evaluator`:
- **INFRASTRUCTURE_ERROR en la evaluación:** nuevo intento del **mismo** ensayo (`attempt_002`, …). `attempt_001` se conserva.
- **Ensayo bloqueado por el entorno:** se evalúa el mismo ensayo (seguía PENDING).
- **Generación caída o ensayo interrumpido:** se crea un ensayo **nuevo** para esa celda. El anterior se conserva y queda en `superseded`.

## 5. Pausar, detener y reanudar

- **PAUSAR DESPUÉS DEL ENSAYO ACTUAL:** nunca interrumpe TIA. El ensayo en curso termina, se persiste y el lote queda PAUSED.
- **DETENER LOTE:** cierra el lote (CANCELLED). Si hay un ensayo en curso, se aplica al terminarlo. No se mata ningún proceso y no se borra nada.
- **REANUDAR:** contrasta el manifiesto con cada `trial.json`; nunca deduce el progreso por la existencia de carpetas.
  - Un ensayo que ya había terminado se registra.
  - Uno generado y sin evaluar se evalúa (el mismo ensayo).
  - Uno cortado a mitad deja el lote en PAUSED con el detalle.
  - Los ensayos completados **nunca** se repiten.
- **Al abrir la aplicación**, un lote incompleto se anuncia en la consola y en el botón (`LOTE TEXT (46/96) · PAUSED`). Nunca se reanuda solo.

## 6. Almacenamiento

```
results/batches/TEXT_DEV_20261006_001/
  batch_manifest.json   estado del lote; escritura atómica tras CADA paso (sobrevive a cierre, reinicio o caída)
  batch_summary.json    una entrada por ensayo + progreso + totales
  batch_summary.csv     una fila por ensayo, columnas estables
results/development_validation_v2/Dxx/Vy/<trial_id>/   cada ensayo, con todos sus artefactos de siempre
```

**`batch_manifest.json`:**
- **Identidad del lote:** `batch_id`, `phase`, `trial_kind`, `input_mode`, `benchmark_version`, `selection`.
- **Tiempos y estado:** `created_at`, `started_at`, `completed_at`, `updated_at`, `status` (CREATED / RUNNING / PAUSED / COMPLETED / CANCELLED), `pause_requested`, `pause_reason`, `pause_detail`.
- **Entorno:** `git_commit`, `git_dirty`, `host_id`.
- **Progreso:** `total_trials`, `completed_trials`, `current_index`, `next_trial`, `trial_ids`, `results`.
- **`ordered_trial_plan`:** una entrada por celda, con `index`, `case_id`, `variant_id`, `reference_text`, `variant_hash`, `evaluable`, `status`, `trial_id`, `trial_dir`, `superseded`, `started_at`, `completed_at`, `notes` y `result` (la fila del resumen).
- **`events`:** historial del lote.

**Columnas de `batch_summary.csv`** (`text_batch.CSV_FIELDS`), por grupos:
- **Identificación:** `batch_id, index, trial_id, case_id, variant_id, input_mode, phase, domain, complexity, benchmark_version, canonical_case_hash, variant_hash, oracle_hash, entry_status, evaluable`.
- **Etapas** (desde `trial_stage_summary`): `semantic, io_allocation, ir, compilation, tia_archive, download, runtime, functional, safety, final_verdict`.
- **Clasificación:** `failure_category, clarification_requested`.
- **Tiempos:** `semantic_ms, generation_ms, compile_ms, runtime_ms, evaluation_ms, total_ms`.
- **Trazabilidad:** `attempts, trial_dir, zap18_path, zap18_hash, started_at, completed_at, superseded_trial_ids`.

Valores ausentes: celda vacía (`null` en el JSON). Nunca se inventan.

**Métricas de la tesis.** Los datos quedan listos para calcular después:
- Semantic, Compilation y Functional Success Rate (columnas de etapa);
- Safety Violation Rate (`safety == FAIL`);
- End-to-End Latency (`total_ms`);

agrupando por `case_id`, `variant_id`, `domain` o `complexity`. Los denominadores salen de las filas
registradas (`batch_summary.json → totals.*.recorded`). Los ensayos NOT_EVALUABLE tienen etapas `-` y no
cuentan como PASS ni como FAIL.

## 7. Piloto: DEVELOPMENT, D01–D03 × V1–V3 = 9 ensayos (PC EVAL)

1. `git pull` y `.venv\Scripts\python.exe scripts\check_environment.py`: todo en OK (MASTER validado, PLCSIM y Openness presentes).
2. Abrir PLCSIM Advanced con la instancia `TESIS_PLC_SIM` en RUN, como para un ensayo individual.
3. Abrir la aplicación → **Modo de trabajo: Experimentación** → **EJECUTAR LOTE TEXT**.
4. Fase **DEVELOPMENT**. En "Rango opcional" escribir `D01-D03`. Variantes V1, V2 y V3. Debe mostrar **Total de ensayos: 9**.
5. **INICIAR LOTE**. El diálogo muestra el ensayo actual (`n / 9`), sus etapas y los conteos. Se puede cerrar y volver a abrir: el lote sigue.
6. Al terminar: "LOTE TEXT COMPLETADO". Revisar `results/batches/TEXT_DEV_<fecha>_NNN/batch_summary.csv` y abrir algún `.zap18`.
7. Probar también **PAUSAR DESPUÉS DEL ENSAYO ACTUAL** → REANUDAR.

## 8. Lote completo

- **DEVELOPMENT, 96 ensayos:** D01–D20 y P01–P12, V1–V3. Los 36 ensayos P01–P12 quedan NOT_EVALUABLE mientras el Runtime no soporte PID analógico.
- **FORMAL:** primero congelar el software (`software_freeze_manifest`) y validar el MASTER como FORMAL_READY. Hacer commit y dejar el árbol limpio. Después ejecutar FORMAL con **D01–D20 × V1–V3 = 60 ensayos**, y P01–P12 cuando exista la extensión del Runtime.
