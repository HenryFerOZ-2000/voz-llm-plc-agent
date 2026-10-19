# Cierre de validación PID y adaptación — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Completar la comprobación DEVELOPMENT de P01–P12, la evaluación nativa aislada, el guardado PID desde la GUI y la adaptación a mapas alternativos con evidencia reproducible.

**Architecture:** Reutilizar `product_engine`, los contratos congelados, el recorrido Archive/Retrieve del evaluador y las sesiones PID actuales. Añadir un contrato explícito de evaluación dinámica y un servicio de persistencia que compartan GUI y verificadores. El benchmark supervisor y la validación dinámica tendrán resultados separados; ninguna evaluación modificará Normal ni el MASTER.

**Tech Stack:** Python 3.13, pytest, CustomTkinter, C#/.NET Framework, TIA Portal V18 Openness, S7-1500/CPU 1516-3 PN/DP, PLCSIM Advanced V5.

**Spec:** `docs/superpowers/specs/2026-10-18-cierre-validacion-pid-y-adaptacion-design.md`.

Estado: aprobado por Henry el 18 de octubre de 2026. Ejecución en esta sesión,
en la rama aislada `feat/project-closure-20261018`; comprobaciones reales en curso.

## Global Constraints

- «No incluye congelar la versión final, iniciar FORMAL, grabar la campaña de voz ni descargar al PLC físico.»
- «P01–P12 comprueban supervisión, consignas, modos y fallos mediante variables del DB; no son doce ensayos de sintonización de PID_Compact.»
- «Una aclaración auténtica es un resultado de interpretación, no se contesta para obtener PASS en el lote.»
- «Los fallos funcionales se conservan.»
- «No se sustituirá un Oracle supervisor por una prueba de convergencia para adjudicarle PASS.»
- «La sintonización seguirá siendo una acción explícita autorizada por el operador.»
- «Se conserva la restricción de escritura a PLCSIM; este encargo no habilita el PLC físico.»
- «Los ajustes temporales quedarán en el entorno aislado y registrados.»
- Protocolo nativo inicial: un lazo de nivel en %, válvula de llenado, consignas 50/40/60 %, banda ±2 puntos, permanencia 10 s, plazo 300 s por consigna.
- No enviar Oracles, resultados esperados ni respuestas de referencia al LLM. Reutilizar la clave existente ya autorizada; nunca mostrarla ni copiar `.env` a evidencia.
- Mantener el índice Git principal y los archivos previos del usuario; el checkout está sucio por integraciones anteriores. Los commits del trabajo nuevo se harán solo en el entorno aislado, con rutas explícitas.

## Review Focus

- Cancelación, pérdida de proveedor o excepción tardía: no adjudicar PASS por una convergencia previa; restaurar señales y comprobar parada (tareas 3–4).
- Parámetros finitos pero de otro programa/configuración o procedentes de una lectura antigua: rechazar guardado antes de modificar TIA (tarea 5).
- Dispositivo ausente, nombre ambiguo o variable bloqueada en el mapa alternativo: no sustituir el equipo ni autorizar recursos por asumir que el ensayo debe pasar (tarea 7).
- Contrato histórico v1 y resultados anteriores: seguir leyéndolos sin completar identidad ni ejecutar un protocolo nuevo retrospectivamente (tarea 2).
- Cerrar la GUI, generar otro programa o pulsar dos operaciones mientras se guarda: serializar operaciones y no dejar un estado «guardado» falso (tarea 6).

## Mapa de archivos y responsabilidades

| Archivo | Responsabilidad |
|---|---|
| `src/trial_experiments/development_validation.py` (nuevo) | Ejecutar y registrar rondas DEVELOPMENT mediante el motor del producto y servicios existentes. |
| `scripts/validate_product_closure.py` (nuevo) | CLI delgada: preflight, ronda P, ensayo nativo y matriz de mapas; no implementa otro intérprete. |
| `src/trial_experiments/native_pid_protocol.py` (nuevo) | Validar, congelar y reconocer el alcance del protocolo de regulación. |
| `config/native_pid_evaluation_protocol.json` (nuevo) | Criterios versionados de la prueba de tanque, separados del benchmark. |
| `src/trial_experiments/product_contract.py` | Contrato v2 autosuficiente y lectura compatible de contratos previos. |
| `src/trial_experiments/deferred_evaluator.py` | Importación desde artefactos congelados y despacho por capacidad real. |
| `tia_openness_bridge/Program.cs`, `PidControlSupport.cs` | Construcción PID en copia experimental y persistencia offline comprobada. |
| `src/pid_native_validation.py` | Protocolo de ejecución con perfil congelado, cancelación y aplicabilidad de comprobaciones. |
| `src/pid_parameter_store.py` (nuevo) | Validar lectura de runtime, guardar mediante Openness y conservar evidencia de parámetros. |
| `src/pid_commissioning_view.py`, `src/gui.py` | Estado visible y acciones explícitas, fuera del hilo gráfico. |
| `tests/fixtures/closure_maps/` (nuevo) | Mapas alternativos de prueba; nunca son el mapa activo del usuario. |
| `docs/30_cierre_validacion_pid_y_adaptacion.md` (nuevo) | Guía operativa, resultados y límites comprobados. |

Los bloques comparten el contrato del paquete y la identidad del lazo; se ejecutarán secuencialmente. No se añaden un sistema genérico de plantas ni un backend de acceso al PLC físico.

## Preparación: aislamiento y preservación

- [ ] Leer spec y plan, aplicar `using-git-worktrees` y obtener checkout aislado basado en el estado actual respaldado, incluidos archivos nuevos relevantes. Verificar hashes antes de trabajar: no basta con partir de HEAD.
- [ ] Revalidar `runtime/backups/pre_project_closure_20261018_192454_572756/backup_report.json`; registrar cualquier edición del usuario posterior sin sobrescribirla. Usar una captura nueva si la base cambió.
- [ ] Guardar identidad de fuente, mapas, configuración de conexiones, índice principal, resultados históricos y MASTER. Copiar configuración necesaria al entorno aislado sin cambiar la conexión habitual.
- [ ] Antes de modificar un proyecto TIA, crear un Archive nuevo y comprobar ZIP y hash. Los archivos TIA del respaldo anterior son históricos verificados, no una captura del proyecto vivo.
- [ ] Registrar baseline existente: 95 pruebas aprobadas en `runtime/project_closure_baseline.xml`. La GUI necesita acceso a Tcl fuera del aislamiento actual; no instalar ni modificar Python para sortearlo.

## Task 1: Ronda P01–P12 reproducible con el motor actual

**Files:** Create `src/trial_experiments/development_validation.py`, `scripts/validate_product_closure.py`, `tests/test_development_validation.py`. Reuse `product_engine.py`, `trial_model.py`, `trial_io_map.py`, `benchmark_catalog.py`, `deferred_evaluator.py`, `text_batch.py`. Modify `src/gui.py` only if extracting a small existing preparation helper is necessary to share lifecycle behavior.

**Interfaces:**
- `build_pid_supervisory_plan(project_root: Path) -> list[dict]`: exactly P01–P12 × V1/V2/V3, benchmark order and original hashes.
- `run_supervisory_round(project_root: Path, output_root: Path, *, evaluate: bool, cancel: threading.Event | None = None) -> dict`: create a new DEVELOPMENT round; use existing trial creation, working map, product engine, generation finalization and `evaluate_trial`.
- CLI: `python scripts/validate_product_closure.py p-suite --phase DEVELOPMENT --generate-only` and `p-suite --phase DEVELOPMENT --evaluate`.

- [ ] **Step 1: Add failing tests.** Assert 36 unique ordered entries, exact canonical variant text/hash, DEVELOPMENT-only phase, unchanged source map, `PRODUCT_SHARED_V1`, frozen map policy and no Oracle context in fake LLM calls. A clarification must finish without an invented answer.
- [ ] **Step 2: Run red.** `python -m pytest tests/test_development_validation.py -q`; expect missing interface/behavior failures.
- [ ] **Step 3: Implement orchestration.** Use `interpret_product_command`, `resolve_product_assignments`, `generate_product_package`, existing trial numbering/directories and `finalize_generation`. Retain raw responses, model, timings and per-stage failures. Do not reproduce semantic logic in the runner.
- [ ] **Step 4: Run green and parity tests.** Compare saved response/map inputs through GUI adapter and new runner: semantic result, package kind and generated body must agree. Run `tests/test_product_engine.py` and `tests/test_gui_product_engine.py` too.
- [ ] **Step 5: Execute baseline live round.** Check credentials by presence only and use previously authorized key. Create a new DEVELOPMENT batch; classify every actual package. Evaluate supported supervisor artifacts in isolated MASTER copies. Pause on infrastructure failure, preserve FAIL/REVIEW and unanswered clarifications.
- [ ] **Step 6: Diagnose reproducible failures.** Add focused regressions before product fixes; do not alter frozen commands/Oracles. Save baseline and later corrected rounds separately. Commit only this task's changed files in the isolated branch.

## Task 2: Contrato nativo autosuficiente con protocolo congelado

**Files:** Create `src/trial_experiments/native_pid_protocol.py`, `config/native_pid_evaluation_protocol.json`, `tests/test_native_pid_trial_bundle.py`. Modify `src/trial_experiments/product_contract.py`, `deferred_evaluator.py`; extend `tests/test_product_trial_contract.py`, `tests/test_product_evaluation_capability.py`.

**Interfaces:**
- `validate_native_protocol(protocol: dict, loop: dict, profile: dict) -> dict`: normalize only supported tank/%/FILL scope; reject invalid timing, criteria or profile.
- `freeze_native_evaluation(trial_dir: Path, package_dir: Path, protocol: dict, profile: dict) -> dict`: copy `native_eval_protocol.json`, `plant_profile.json`, `verification.json`, native infrastructure, bindings, cyclic XML and generation metadata; return hashes and protocol identity.
- `create_native_validation_run(project_root: Path, package_dir: Path, protocol: dict, profile: dict, output_root: Path) -> Path`: create a unique `native_run.json` (`schema_version=1`, `domain=NATIVE_PID_DEVELOPMENT`, phase DEVELOPMENT) and freeze the same bundle. Preserve command/map/generation identity; do not invent a canonical Pxx identifier or relax `trial_model`'s historical case-id validation.
- Extend `freeze_product_contract(..., *, native_protocol: dict | None = None, plant_profile: dict | None = None) -> dict`. Existing calls remain valid.
- Contract schema 2 declares `native_evaluation` with `protocol_id`, `protocol_file`, `plant_profile_file` and `files`; schema 1 remains readable and native v1 remains unsupported for new dynamic evaluation.
- Protocol id `PID_TANK_LEVEL_V1`; tuning policy `REQUIRE_PRETUNE` or `REUSE_VERIFIED`, explicitly selected and frozen. No automatic attachment based only on a Pxx id.

- [ ] **Step 1: Add failing tests.** Deleting the generation directory after freezing must not break bundle validation. Tampering with source, XML, manifest, bindings, profile, protocol or verification must fail before bridge/runtime calls. Path traversal and external symlinks must fail.
- [ ] **Step 2: Run red.** `python -m pytest tests/test_native_pid_trial_bundle.py -q`.
- [ ] **Step 3: Implement schema 2 and validation.** Bind frozen files to source/build/configuration identity. Add all new hashes to the integrity manifest. Distinguish absence of a supported protocol from corrupt identity. Never read a live profile at evaluation time.
- [ ] **Step 4: Run green and compatibility.** Test old supervisor and native schema 1 contracts remain unchanged, with no retroactive upgrade. Callers without a protocol keep the explicit capability gap. Run contract and capability suites.
- [ ] **Step 5: Commit** task files in isolated branch with message `feat: freeze complete native PID evaluation bundles`.

## Task 3: Importación y archivo nativo dentro de la copia experimental

**Files:** Modify `tia_openness_bridge/Program.cs: ExecuteEvaluateTrial`, `tia_openness_bridge/PidControlSupport.cs: Ensure`, `src/trial_experiments/deferred_evaluator.py: _evaluate_trial`, `src/pid_package.py`. Create `tests/test_native_pid_experimental_import.py`; extend `tests/test_phase4a_deferred_evaluation.py`, `tests/test_tia_pid_support.py`.

**Interfaces:**
- Keep bridge action `evaluate_trial`. Add optional `native_pid` request block containing validated manifest, staged cyclic XML, source/bindings hashes and protocol identity from Task 2.
- Add `build_native_trial_request(trial_dir: Path, workspace: Path, contract: dict) -> dict` to `native_pid_protocol.py`: stage only verified frozen files beneath the current attempt's workspace; no Normal project cache.
- Reuse `PidControlSupport.Ensure(PlcSoftware plc, Dictionary<string,object> manifest)` and existing native import/OB validation in the project retrieved by `ExecuteEvaluateTrial`.
- Extract `execute_isolated_trial_request(project_root: Path, request: dict, workspace: Path, on_archived: Callable) -> dict` in `deferred_evaluator.py` around the existing bridge boundary. Both canonical and standalone native evaluation use it with the same MASTER/source/path/archive guards; retain the original supervisor verdict handling.
- Add `validate_experimental_pid_project(package_dir: Path, root: Path, context: dict) -> str` in `pid_package.py`. Require the actual attempt workspace, MASTER snapshot hash, verified archive/hash, compiled project/source/configuration identity and actual TO/OB attributes. Do not broaden `native_download_project`'s default Normal/runtime-project whitelist.
- Stage an execution copy of the frozen bundle inside the attempt workspace, including the verified `program.scl` bytes under the existing `siemens_source.scl` filename expected by the runtime services. Preserve the immutable trial bundle and report the actual experimental compile/archive result as `native_execution_context.json`; never fabricate a Normal compile report to pass a guard.

- [ ] **Step 1: Add failing tests.** A native request must Retrieve only the configured MASTER snapshot, construct its TO/OB in that copy and withhold download until archive evidence is copied and verified. Assert physical target, source/hash mismatch, foreign block collision and wrong OB period abort.
- [ ] **Step 2: Run red.** `python -m pytest tests/test_native_pid_experimental_import.py -q`.
- [ ] **Step 3: Implement shared construction.** Extract only the required native import helper from the Normal bridge path, preserving ownership checks. Both callers share construction, but only the experimental caller owns its retrieved project and archive/download handshake.
- [ ] **Step 4: Run green and bridge checks.** Build through the existing `tia_openness.build_openness_bridge(project_root)` API; run existing self-tests and Python import/evaluator suites. Add cancellation-before-download, wrong attempt/context, alias source mismatch and missing archive tests; none may download or return functional PASS.
- [ ] **Step 5: Compile-only real probe.** Use a new MASTER copy, validate actual PID_Compact 2.3 and OB30/100 ms, verify archive CRC/hash and unchanged MASTER/Normal fingerprints. Handle Openness permissions through Henry; never click security prompts or terminate TIA to bypass them.
- [ ] **Step 6: Commit** verified task files in isolated branch.

## Task 4: Evaluación dinámica con aplicabilidad y limpieza correctas

**Files:** Modify `src/pid_native_validation.py`, `src/trial_experiments/deferred_evaluator.py`, `text_batch.py`, `product_contract.py`. Create `tests/test_native_pid_experimental_evaluation.py`; extend `tests/test_pid_native_validation_v2.py`, `tests/test_native_pid_acceptance.py`.

**Interfaces:**
- Extend `run_map_pid_validation(project_root: Path, package_dir: Path, *, download: bool = True, cancel: threading.Event | None = None, profile: dict | None = None, protocol: dict | None = None, report_dir: Path | None = None, execution_context: dict | None = None) -> dict`. Preserve default callers; experimental callers must pass frozen inputs, Task 3's validated context and `download=False`. With an experimental context, require the experimental project validator; otherwise retain `native_download_project` unchanged.
- `evaluate_native_trial(project_root: Path, trial_dir: Path, *, cancel: threading.Event | None = None) -> dict` in `native_pid_protocol.py`: return a separately named `native_validation` report, not the old supervisory Oracle verdict.
- `run_frozen_native_development(project_root: Path, run_dir: Path, *, cancel: threading.Event | None = None) -> dict` in `deferred_evaluator.py`: verify Task 2's standalone record/bundle, use Task 3's common isolated bridge boundary, then run `evaluate_native_trial`. Store native generation/compile/archive/runtime/validation statuses in that standalone record, outside formal totals and canonical Pxx verdicts.
- Add `summarize_required_checks(checks: list[dict]) -> dict` to `pid_native_validation.py`: every required check must have execution proof and PASS; optional undeclared emergency/overfill checks use `NOT_APPLICABLE`. Cleanup and native identity are always required.

- [ ] **Step 1: Add failing tests.** A command without declared emergency/overfill must not fail merely because those optional checks are absent. A declared but failing check must fail. Missing mandatory observations, provider failure after convergence, cleanup failure or cancellation must prevent PASS.
- [ ] **Step 2: Run red.** `python -m pytest tests/test_native_pid_experimental_evaluation.py tests/test_pid_native_validation_v2.py -q`.
- [ ] **Step 3: Implement frozen-protocol execution.** Use actual mapped measurement/output and native state transitions. For `REUSE_VERIFIED`, require confirmed compatible parameters and assert no states 1/2. For `REQUIRE_PRETUNE`, require explicit test authorization and observed state 1→3 before convergence tests. GUI evaluation uses a standalone native run rather than attaching a fictitious Pxx case to a Normal program.
- [ ] **Step 4: Integrate result routing.** Supported native bundles can execute the dynamic protocol in DEVELOPMENT. Preserve generation/compile/archive/runtime/native/cleanup statuses separately. P01–P12 keep their original Oracle: a native dynamic success never substitutes its PASS; unresolved original bindings retain a concrete benchmark capability reason.
- [ ] **Step 5: Real PLCSIM run.** Execute 50/40/60 %, ±2 points continuously for 10 s before 300 s each, relevant stops/faults and checked cleanup. Confirm command filtering never changes the generated program to help the model pass. Save samples and independently recompute acceptance.
- [ ] **Step 6: Commit** verified task files and preserve the run's immutable evidence.

## Task 5: Guardado de parámetros comprobados mediante Openness

**Files:** Create `src/pid_parameter_store.py`, `tests/test_pid_parameter_store.py`. Modify `src/tia_openness.py`, `tia_openness_bridge/Program.cs`, `PidControlSupport.cs`; extend `tests/test_pid_normal_project.py`, `tests/test_tia_pid_support.py`.

**Interfaces:**
- `inspect_parameter_state(package_dir: Path, live_values: dict, saved_record: dict | None) -> dict`: return one of `UNVERIFIED`, `TUNING`, `PENDING_SAVE`, `SAVED_VERIFIED`, `INCOMPATIBLE`, with reason.
- `save_verified_parameters(project_root: Path, package_dir: Path, session: PidCommissioningSession, *, cancel: threading.Event | None = None) -> dict`: refresh live identity/readings, validate and call bridge; return archive, project/configuration identity, before/after values and verified status.
- Bridge action `native_pid_save_parameters`; implementation `ExecuteSaveNativePidParameters(Dictionary<string,object> request)` in `Program.cs`. Request identifies exact Normal project, owned TO, configuration/source hash and freshly read Kp/Ti/Td; report preserves before/after and verified archive.
- Parameter comparison absolute tolerance `0.0001`; valid finite gain > 0, Ti > 0 and Td >= 0, matching the supported controller contract. No extra assumption that gains transfer to other plants.

- [ ] **Step 1: Add failing tests.** Reject stale build signature, changed map/scale/configuration, NaN/Inf, running tuning, unconfirmed parameters, missing ownership and a different project before writes. Cancellation must not leave an unverifiable «saved» record.
- [ ] **Step 2: Run red.** `python -m pytest tests/test_pid_parameter_store.py -q`.
- [ ] **Step 3: Implement Python service.** Read via the existing session immediately before save; bind data to package/loop identity. Serialize source/project operations and atomically persist successful records under managed runtime state. Never infer success from the presence of a local JSON alone.
- [ ] **Step 4: Implement and probe V18 bridge save.** In a disposable project copy verify writable Openness parameter names already used by `Ensure`: `_Retain.CtrlParams.SetByUser` and `Retain.CtrlParams.Gain/Ti/Td`. Archive first, reject unsaved user edits, write, reread and save. Read back project values; retain earlier archive on any failure. Do not use editor clicks as the product's persistence backend.
- [ ] **Step 5: Run green and live persistence.** Save in the backed-up Normal project only after the copy probe passes. Regenerate identical loop, compile, download to PLCSIM, compare parameters within tolerance and repeat regulation with `REUSE_VERIFIED`. A deliberately changed scale in a copied map must not inherit saved verification.
- [ ] **Step 6: Commit** verified task files. If an installed V18 API prevents the required save, retain the TIA workflow and report the limitation; do not mark this task complete by writing an unverified file.

## Task 6: GUI integrada de puesta en marcha y evaluación

**Files:** Modify `src/pid_commissioning_view.py`, `src/gui.py: open_pid_commissioning`, `src/pid_commissioning.py`. Extend `tests/test_gui_pid_commissioning.py`, `tests/test_gui_pid_plant_test.py`; create `tests/test_gui_pid_parameter_store.py`.

**Interfaces:**
- Extend `PidCommissioningPanel(..., on_save=None, on_evaluate=None)` without breaking current constructor calls. Add `show_parameter_state(state: dict)` and `set_operation_state(operation: str | None)`.
- Labels: `Guardar parámetros verificados en TIA`, `Evaluar PID en PLCSIM`, state/reason and actual sensor/actuator/unit. Preserve existing manual, tuning and model buttons.
- GUI callbacks call Tasks 4–5 services on worker threads; consume messages and update widgets on the UI thread. Evaluation requires explicit protocol and tuning authorization when requested.

- [ ] **Step 1: Add failing tests.** Opening/closing panel must never start, tune, write or save. No program/no download/stale identity must disable destructive actions. Double-save, generation of another program during save, closing during work and provider failure must produce an accurate final state.
- [ ] **Step 2: Run red.** `python -m pytest tests/test_gui_pid_parameter_store.py -q` in a Tcl-capable environment.
- [ ] **Step 3: Implement panel and callbacks.** Bind display to verified runtime/record data; display complete phase/reason rather than generic success. Disable incompatible controls while busy, cancel safely and wait for cleanup when closing. Never relax the physical-write guard.
- [ ] **Step 4: Run green and real UI check.** Verify one save/reuse/evaluation flow from the actual app using the product services; unit-test mocks alone do not prove Openness persistence. Check readability of the new status and error text.
- [ ] **Step 5: Commit** only GUI/service integration changes after related suites pass.

## Task 7: Mapas alternativos, ronda corregida y entrega

**Files:** Create `tests/fixtures/closure_maps/` fixtures and `tests/test_pid_map_adaptation.py`; extend `development_validation.py`, `scripts/validate_product_closure.py`. Create `docs/30_cierre_validacion_pid_y_adaptacion.md`; update `docs/00_indice_documentacion.md`, `docs/25_contexto_evaluacion_y_cierre_analogico.md` with current evidence and limits.

**Interfaces:**
- `build_map_adaptation_cases(project_root: Path) -> list[dict]` in `development_validation.py`: explicit command + copied map + expected capability, never an Oracle-fed prompt.
- CLI: `python scripts/validate_product_closure.py maps --phase DEVELOPMENT --evaluate`; a new run directory/manifests for every invocation.
- Stable delivery record `runtime/project_closure_delivery.json`: task completion, source/configuration identity, backups, round references, individual outcomes, parameter persistence, cleanup and protected-file checks.

- [ ] **Step 1: Add failing tests.** Positive fixtures: renamed/disjoint digital and analog addresses, declared DB measurement/output and digital level sensor/electrovalve. Negative fixtures: absent/blocked/ambiguous actuator, overlap, invalid scale, incompatible units and stale gains. Assert no source map mutation and no hardcoded bank addresses in output.
- [ ] **Step 2: Run red, implement minimum corrections, run green.** `python -m pytest tests/test_pid_map_adaptation.py tests/test_natural_tank_commands.py tests/test_pid_map_driven_generation.py tests/test_pid_map_driven_semantics.py -q`. Unsupported equipment must be reported honestly, not assigned synthetic channels.
- [ ] **Step 3: Run real adaptation matrix.** For compatible virtual S7-1500 maps, compile and execute discrete latch, finite fill, hysteresis and PID. Include declared DB signals only where supported; if support is incomplete implement and prove it before claiming coverage. Different map names alone do not count as a second hardware platform.
- [ ] **Step 4: Execute final 36-variant DEVELOPMENT round.** Use Task 1 runner, same canonical commands and unchanged Oracles. Compare baseline/corrected results by stage; record all FAIL/REVIEW and native capability reasons without rerunning to manufacture PASS.
- [ ] **Step 5: Run final regressions.** Focused suites first, then `python -m pytest -q --junitxml=runtime/project_closure_final_tests.xml --basetemp=runtime/project_closure_final_pytest` in the verified environment. Do not add overlapping counts as unique tests. Classify skips/xfails/warnings explicitly.
- [ ] **Step 6: Review implementation and evidence.** Check changed files against spec, archived artifacts, source/TO identities, real execution proof and cancellation paths. A fresh final reviewer may be used only as allowed by the chosen execution workflow; fix reproducible findings and rerun affected checks.
- [ ] **Step 7: Guarded integration.** Compare each root file with its pre-change hash before copying the approved implementation from isolation; preserve concurrent user edits. Do not stage/reset root files. Run integrated focused regressions and recheck historical results, config, maps, MASTER and index, allowing only recorded intended changes.
- [ ] **Step 8: Deliver guide and status.** Explain project/map selection, generate/compile/download, manual checks, when to tune, how to save/reuse and how to run isolated evaluation. Identify virtual instruments/model and physical validation still pending. No new freeze or FORMAL batch.

## Acceptance and self-review

- Tasks 1/7 cover all 36 variants, true engine parity, retained outcomes and both baseline/final evidence.
- Tasks 2–4 preserve frozen identity, historical schema compatibility, isolated MASTER import and separate supervisory/dynamic verdicts.
- Tasks 4/5 cover actual mapped loop response, optional checks, cancellation, verified save and reuse without tuning.
- Tasks 6/7 cover GUI state, concurrency, another map and regression preservation.
- Unknown V18 parameter behavior is resolved by a disposable-copy probe; an unavailable API remains a reported limitation, never false completion.
- A global PASS is not inferred from generation, numerical trace processing, a skipped check or a local saved-state file.
- Each new interface is defined above, with consistent names used by its consumers. No product dependency or PLC physical connector is added.

## Execution handoff

Propuesta: ejecución directa por el agente en esta sesión, tarea por tarea, seguida
de revisión final según la habilidad de ejecución. Las tareas comparten contratos
y archivos y no conviene implementarlas en paralelo sin coordinación.

Henry aprobó este plan y la ejecución directa con «apruebo». La implementación
está en `runtime/worktrees/project-closure`; el registro de avance se conserva
en `.superpowers/sdd/2026-10-18-cierre-validacion-pid-y-adaptacion/progress.md`.
La evidencia actual y los pendientes se describen en
`docs/30_cierre_validacion_pid_y_adaptacion.md`. Esta actualización de estado no
modifica el alcance aprobado ni declara completadas las tareas pendientes.
