# Motor de producto compartido Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Hacer que Normal y los ensayos nuevos usen el mismo motor de interpretación, asignación y generación, conservando el aislamiento y la evidencia experimental.

**Architecture:** Una fachada Python reutiliza las reglas actuales de Normal y los componentes existentes. Los adaptadores de la GUI conservan la interacción, transacciones y persistencia propias de cada modo. La evaluación diferida identifica el programa congelado y bloquea preventivamente el PID nativo hasta disponer de su recorrido experimental completo.

**Tech Stack:** Python, pytest, CustomTkinter, JSON, SCL Siemens; TIA V18 y PLCSIM Advanced V5 permanecen detrás de sus puentes actuales. Sin dependencias nuevas.

**Spec:** [Diseño aprobado](../specs/2026-10-17-motor-producto-compartido-design.md), aprobado por Henry el 17 de octubre de 2026. Plan aprobado por Henry para ejecutar en esta sesión, con revisión independiente final.

## Global Constraints

- «No se exige igualdad byte a byte entre respuestas independientes del servicio LLM.» La equivalencia se verifica con mensajes/contextos iguales y respuestas controladas idénticas.
- «El LLM no recibirá respuestas esperadas, secuencias del Oracle, parámetros esperados por caso ni resultados previos como ayuda para producir el programa.»
- «Normal conserva sus transacciones y guardado en el mapa de trabajo del usuario.»
- «Experimentación solo escribe su working map durante CREATED/PREPARING y lo congela en IO_RESOLVED.»
- «Los 96 ensayos TEXT previos, lotes, audios, benchmark v3, Oracles y manifiesto FORMAL_V1_1 permanecen intactos.»
- No iniciar FORMAL, reescribir Oracles, sustituir P01–P12 por PID nativo, sintonizar ni descargar al PLC físico. No relajar la guarda del congelamiento anterior.
- Conservar el índice Git principal y las ediciones concurrentes. Commit únicamente en el worktree aislado; integrar por archivos y hashes, sin reset/stash/cherry-pick del árbol principal sucio.

## Review Focus

1. Señal DB o dispositivo analógico configurado sin procedencia de programa: conservar nombre, función, permisos y configuración; tareas 2 y 3.
2. Fallback por reglas o reintento LLM: conservar las restricciones del producto y no introducir la respuesta esperada del Oracle; tareas 1 y 3.
3. Composición válida con INT_UNKNOWN frente a respuesta vacía o inválida: aceptar solo la primera en ambos modos; tareas 1 y 3.
4. Ensayo guardado antiguo o contrato nuevo alterado: no regenerar ni completar metadata histórica; comprobar integridad antes de TIA; tareas 4 y 5.
5. Paquete PID nativo que conserva SCL pero pierde su manifiesto: no clasificarlo como discreto ni crear PASS/FAIL funcional por falta de capacidad del evaluador; tarea 5.

## Archivos y responsabilidades

- Crear `src/product_engine.py`: entrada común, identidad, preparación pura del mapa, asignación/revalidación y generación del producto.
- Modificar `src/llm_parser.py`: extraer la vinculación/revalidación existente sin cambiar los contratos históricos explícitos.
- Modificar `src/normal_program_bindings.py`: permitir liberación estricta de asignaciones con propietario verificable, conservando el comportamiento histórico de su firma predeterminada.
- Modificar `src/gui.py`: utilizar la fachada desde ambos modos; conservar las operaciones y persistencia propias de cada adaptador.
- Modificar `src/trial_experiments/trial_io_map.py`: política explícita de mapa del producto y compatibilidad histórica; permitir señales de proceso DB declaradas.
- Modificar `src/project_packager.py`: propagar identidad del motor en metadata generada cuando exista, sin añadirla a la respuesta del LLM.
- Crear `src/trial_experiments/product_contract.py`: contrato congelable del producto y clase del paquete; no conoce respuestas del Oracle.
- Modificar `src/trial_experiments/deferred_evaluator.py`, `text_batch.py` y los puntos de registro en `gui.py`: persistencia, integridad, precheck de capacidad y estado explícito de evaluación pendiente por capacidad.
- Pruebas nuevas: `tests/test_product_engine.py`, `tests/test_gui_product_engine.py`, `tests/test_product_trial_map.py`, `tests/test_product_trial_contract.py`, `tests/test_product_evaluation_capability.py`.

## Preparación y ejecución

- [x] Antes de cambiar código, leer diseño y plan completos. Registrar rama/HEAD y estado de ambos árboles. El worktree existente es `runtime/worktrees/pid-io-map-driven`, rama de diseño `design/shared-product-engine`, commit de diseño `7169067`; crear una rama de implementación desde él mediante la habilidad de worktrees.
- [x] Crear `runtime/backups/pre_shared_product_engine_<fecha>/` en el árbol principal: archivo ZIP de todos los archivos que se modificarán, manifiesto SHA-256, lista de rutas nuevas, estado Git e índice principal. Verificar CRC del ZIP y hashes de sus entradas antes de editar. Incluir también los contratos históricos y configuración como archivos protegidos, aunque no se vayan a modificar.
- [x] Registrar hashes de los resultados previos, corpus existente, benchmark/Oracles, manifiesto freeze, mapas del usuario, configuración y proyecto/snapshot MASTER. Si un archivo cambia concurrentemente, detener la integración de ese archivo sin restaurarlo por fuerza.
- [x] Ejecutar cada tarea con un ciclo RED → implementación mínima → GREEN y un commit local. Pruebas con clientes simulados o respuestas guardadas; no abrir TIA, llamar al LLM real ni iniciar descargas como efecto de una prueba unitaria.

Comando base desde el worktree, usando el Python del árbol principal:

```powershell
C:\TESIS_HENRY\voz-llm-plc-agent\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider --basetemp .pytest_tmp/shared_<tarea> <archivos_de_prueba>
```

Usar un directorio temporal nuevo por invocación. Las pruebas GUI pueden necesitar la escalación habitual para Tcl/Tk; no deben controlar aplicaciones del usuario.

## Task 1: Entrada común y resolución semántica del producto

**Files:** crear `src/product_engine.py`, `tests/test_product_engine.py`; modificar `src/llm_parser.py` y `src/project_packager.py`.

**Interfaces:**
- `ENGINE_ID = "PRODUCT_SHARED_V1"` y `MAP_POLICY = "PRODUCT_DECLARED_V1"` en `product_engine.py`.
- `interpret_product_command(command_text: str, *, io_map: dict, intents_catalog: dict, safety_rules: dict, mode: str | None = None, llm_client: Any = None, llm_response_text: str | dict | None = None, clarification_history: list[dict] | None = None, program_context: dict | None = None) -> dict`.
- `llm_parser.bind_semantic_resources(semantic_output: dict, io_map: dict, intents_catalog: dict, safety_rules: dict) -> dict`: extracción del bloque actual de bindings al final de `parse_command`; conserva los defaults de recursos que ese bloque vuelve explícitos.
- `resolve_product_assignments(semantic_output: dict, io_map: dict, proposals: list[dict], intents_catalog: dict, safety_rules: dict) -> tuple[dict, dict, list[dict]]`: devuelve semántica revalidada, mapa provisional e historial; no persiste. Propuestas bloqueadas provocan error, no se omiten silenciosamente.
- `generate_product_package(semantic_output: dict, *, target_platform: str, io_map: dict, intents_catalog: dict, safety_rules: dict, transcription_payload: dict | None = None, output_dir: Path | None = None) -> dict`: delega al empaquetador existente con identidad del motor.
- `is_generatable_product(semantic_output: dict) -> bool`: exige validación válida y una intención implementable o primitivas admitidas; no convierte INT_UNKNOWN vacío en programa.

- [x] Escribir `test_product_request_uses_current_normal_policy`, `test_product_retry_and_rule_fallback_keep_control_constraints`, `test_product_bindings_survive_provisional_allocation`, `test_product_composition_acceptance_requires_valid_logic`, `test_product_metadata_never_enters_llm_response_schema` y `test_legacy_parser_contract_is_unchanged`. Usar las respuestas de límite/histéresis/PID/supervisión de `test_normal_control_strategy.py` y fixtures renombrados del mapa.
- [x] Ejecutar `tests/test_product_engine.py tests/test_normal_control_strategy.py tests/test_parser_modes.py`; comprobar RED por la interfaz nueva ausente o conducta reproducida, no por un fallo de entorno.
- [x] Implementar las interfaces. La fachada selecciona siempre el perfil semántico actual `normal` y añade metadata `product_engine = {"schema_version": 1, "engine_id": ENGINE_ID}` después de interpretar. No enviar modo de trabajo, fase, caso, variante ni Oracle al LLM. Mantener el límite de reintentos existente. Extraer el binding una vez y reutilizarlo en parseo y revalidación.
- [x] Ejecutar las pruebas anteriores junto con `tests/test_normal_role_resolution.py tests/test_native_pid_resolution.py tests/test_pid_map_driven_semantics.py`; exigir cero fallos y revisar las solicitudes capturadas, requisitos y bindings, no solo la etiqueta de intención.
- [x] Commit: `feat: add shared product interpretation and generation entry`.

## Task 2: Preparación común del mapa sin perder dispositivos

**Files:** modificar `src/product_engine.py`, `src/normal_program_bindings.py`, `src/trial_experiments/trial_io_map.py`; crear `tests/test_product_trial_map.py`.

**Interfaces:**
- `prepare_product_map(io_map: dict, *, scope: str = "NEW_PROGRAM", previous_program_id: str | None = None) -> dict`, con claves `io_map`, `released` y `retained_unknown`. Usa los valores existentes `NEW_PROGRAM`/`EXTEND_PROGRAM`. Si no se proporciona propietario previo, solo puede obtenerlo de `io_map.metadata.current_program.program_id`, nunca del estado global de otro modo. Devuelve copias; no modifica el mapa recibido.
- Ampliar `release_auto_bindings(io_map: dict, *, strict_owner: bool = False, owner_program_id: str | None = None) -> tuple[dict, list[dict]]`. En modo estricto solo liberar ASSIGNED con `assignment_source == "AUTO"` y propietario no vacío igual al programa previo; conservar LOCKED/MANUAL/persistent y procedencia desconocida.
- Ampliar `create_working_map(trial_dir: Path, source_map_path: Path, *, map_policy: str = "LEGACY_CLEARED_V1", previous_program_id: str | None = None) -> dict`. La firma histórica conserva su resultado; los llamadores nuevos deben pasar `PRODUCT_DECLARED_V1`. Rechazar políticas desconocidas.

- [x] Escribir `test_product_map_preserves_analog_and_db_devices`, `test_product_map_retains_unknown_ownership`, `test_product_map_releases_only_matching_auto_owner`, `test_product_working_map_allows_db_only_scenario`, `test_product_map_policy_is_recorded_and_frozen` y `test_legacy_map_cleaning_remains_explicitly_available`. Afirmar igualdad de unidades, calibración, dirección, alias, permisos, metadata desconocida e historial de dispositivos conservados; incluir nombres y direcciones distintos de IW4/QW4.
- [x] Ejecutar `tests/test_product_trial_map.py tests/test_experiment_working_io_map.py tests/test_normal_program_bindings.py`; comprobar RED para las políticas nuevas.
- [x] Implementar preparación pura y política registrada en la referencia/snapshot. Un mapa DB válido no necesita canales físicos; la ruta histórica conserva su precondición actual. EXTEND_PROGRAM conserva el mapa. La ausencia de propietario verificable no se interpreta como permiso para liberar. La asignación posterior sigue usando el IOAllocator común.
- [x] Ejecutar esas pruebas y `tests/test_process_signals.py tests/test_analog_configuration.py tests/test_phase4a0b_resource_policy.py`; exigir cero fallos y verificar que los mapas base no cambian.
- [x] Commit: `feat: preserve declared devices in product trial maps`.

## Task 3: Conectar ambos modos al motor y conservar la interacción

**Files:** modificar `src/gui.py`; crear `tests/test_gui_product_engine.py`; actualizar únicamente fixtures de interceptación afectados en las pruebas GUI existentes.

**Consumes:** interfaces de tareas 1 y 2. La fachada no recibe `work_mode`; el adaptador decide dónde persistir y si recoge respuestas del usuario.

- [x] Escribir `test_normal_and_experiment_share_product_request`, `test_experiment_accepts_valid_composition_with_unknown_intent`, `test_both_modes_reject_unbound_measurement_and_wrong_actuator`, `test_trial_clarification_stays_unanswered`, `test_normal_keeps_explicit_extension_context` y `test_trial_allocation_never_commits_user_map`. Comparar mensajes efectivos del cliente grabador y semántica normalizada con la misma respuesta; excluir solo metadata operativa y timestamps.
- [x] Ejecutar `tests/test_gui_product_engine.py` y reproducir RED del gate actual `Normal and has_composable_program` y del perfil ausente en Experimentación.
- [x] Sustituir las llamadas GUI al parser/empaquetador por la fachada y el gate común. Usar preparación de tarea 2 desde `_prepare_program_scope` y `_prepare_trial_working_map`. Las transacciones de Normal y el working map experimental consumen la misma asignación provisional; cada adaptador conserva su guardado/congelamiento. Una aclaración del motor entra en la política existente de lote sin respuesta y no abre un camino para contestarla automáticamente.
- [x] Mantener separadas MAP_CONFIG explícita y generación de lógica; no habilitar edición manual del mapa durante un ensayo. La ampliación de programa solo recibe un programa previo declarado; nunca obtenerlo de respuestas esperadas del Oracle. No cambiar configuración de proyectos, adaptador de red o destino de descarga.
- [x] Ejecutar las pruebas nuevas junto con `tests/test_normal_functional_composition.py tests/test_normal_map_transactions.py tests/test_normal_execute_and_load.py tests/test_normal_voice_auto_flow.py tests/test_phase1_download_and_trials.py tests/test_gui_pid_generation.py`. Actualizar spies para observar la fachada real cuando corresponda, conservando todas las aserciones de resultados.
- [x] Commit: `feat: route normal and new experiments through product engine`.

## Task 4: Congelar identidad del motor y del programa generado

**Files:** crear `src/trial_experiments/product_contract.py`, `tests/test_product_trial_contract.py`; modificar `src/gui.py`, `src/trial_experiments/deferred_evaluator.py`, `src/project_packager.py` y las lecturas/escrituras puntuales de `trial_model.py` si son necesarias.

**Interfaces:**
- `build_product_contract(record: dict, package_dir: Path) -> dict`: contrato JSON `schema_version=1`, `engine_id`, `map_policy`, `interaction_policy="UNANSWERED_CLARIFICATION"`, `package_kind` y hashes de los artefactos adicionales presentes.
- `package_kind` solo admite `DISCRETE_OR_SUPERVISORY` o `NATIVE_PID`; detectar el segundo con `pid_infrastructure.json`, `pid_process_bindings.json` y evidencia consistente del paquete, no mediante `case_id` ni la familia P.
- `freeze_product_contract(trial_dir: Path, package_dir: Path, record: dict) -> dict`: escribir `product_contract.json`, copiar para identidad los manifiestos PID presentes y devolver los nombres adicionales que debe cubrir `integrity_manifest.json`. Esto no habilita evaluación nativa ni certifica un bundle nativo portátil completo.

- [x] Escribir `test_new_trial_freezes_product_identity`, `test_contract_tampering_fails_integrity`, `test_supervisor_is_not_native_by_case_name`, `test_native_source_without_manifest_is_not_discrete`, `test_legacy_trial_reads_without_backfill` y `test_saved_trial_evaluation_never_reinterprets`. Comprobar hashes antes/después de las lecturas de un fixture histórico.
- [x] Ejecutar `tests/test_product_trial_contract.py tests/test_phase4a_deferred_evaluation.py`; confirmar RED de contrato ausente/alterado.
- [x] Registrar la identidad en ensayos nuevos y metadata del paquete; construir el contrato desde los artefactos reales al finalizar generación. Verificar el contrato y todos sus archivos antes de usarlo. Contratos nuevos incompletos o incoherentes bloquean integridad; contrato histórico ausente conserva su ruta explícita sin escribir campos nuevos. No crear un contrato a partir de un programa guardado antiguo al abrirlo.
- [x] Ejecutar las pruebas anteriores y `tests/test_trial_experiments.py tests/test_trial_stage_summary.py tests/test_evaluation_persistence.py`; exigir cero fallos y verificar que la lectura no escribe metadata ni regenera evidencia.
- [x] Commit: `feat: freeze shared engine identity in new trial evidence`.

## Task 5: Guarda explícita de capacidad para PID nativo

**Files:** modificar `src/trial_experiments/product_contract.py`, `deferred_evaluator.py`, `text_batch.py`, `src/gui.py`; crear `tests/test_product_evaluation_capability.py`.

**Interface:** `evaluation_capability(contract: dict | None) -> dict` devuelve `supported: bool`, `code: str | None`, `reason: str | None`. Para NATIVE_PID, `supported=False`, `code="NATIVE_PID_EXPERIMENT_EVALUATION_UNSUPPORTED"`. Para programa discreto/supervisor, devuelve soporte del recorrido de importación actual; los requisitos Runtime del Oracle se comprueban por separado como hasta ahora.

- [x] Escribir `test_native_precheck_aborts_before_bridge_or_runtime`, `test_native_guard_preserves_generation_without_functional_verdict`, `test_batch_records_capability_block_without_retry_or_pass`, `test_native_identity_cannot_be_removed_to_bypass_guard` y `test_supervisor_still_reaches_existing_evaluator`. Los spies de bridge, Runtime y Oracle deben quedar en cero llamadas al bloquear un PID nativo.
- [x] Ejecutar `tests/test_product_evaluation_capability.py tests/test_text_batch.py` y comprobar RED.
- [x] Integrar la guarda después de verificar integridad y antes de abrir TIA/crear un intento. Devolver `capability_gap` con el código anterior; mantener `generation.status=SUCCESS`, `evaluation.status=PENDING` y `final_verdict=None`, añadiendo `evaluation.capability` con el motivo. La GUI lo presenta como «Evaluación PID nativa pendiente de soporte». El lote usa su entrada existente NOT_EVALUABLE con ese motivo; no consume un intento técnico ni registra FAIL funcional o PASS. Integridad alterada mantiene prioridad sobre capacidad.
- [x] Ejecutar las pruebas anteriores junto con `tests/test_phase4a_deferred_evaluation.py tests/test_trial_stage_summary.py tests/test_pid_supervisor.py tests/test_native_pid_package.py tests/test_software_freeze.py`. Confirmar que no se relajan las guardas FORMAL ni se modifica un resultado histórico.
- [x] Commit: `fix: block unsupported native PID trial evaluation before TIA`.

## Task 6: Verificación conjunta, documentación e integración protegida

**Files:** modificar `docs/25_contexto_evaluacion_y_cierre_analogico.md`, añadir documentación de motor compartido junto a los documentos existentes; actualizar solo los pasajes operativos pertinentes de `docs/deferred_trial_workflow.md` y `docs/text_batch_execution.md`. No reescribir los protocolos congelados ni sus resultados.

- [x] Ejecutar las cinco pruebas nuevas y todas las regresiones señaladas en las tareas 1–5. Añadir `tests/test_formal_audio_pairing.py tests/test_phase4a_experimental_design.py tests/test_normal_control_strategy.py tests/test_pid_map_driven_generation.py`. Exigir cero fallos; conservar logs completos en runtime. No sumar los conteos de ejecuciones solapadas como si fueran pruebas únicas.
- [x] Reproducir offline con los ocho casos guardados del intérprete (`runtime/level_pid_llm_audit_20261017T233217Z_ae1914`): mismas respuestas y mapas para ambos adaptadores, sin API ni regeneración de evidencia histórica. Escribir únicamente un informe nuevo en runtime. Distinguir aclaración/configuración pendiente de generación y ejecución aprobadas.
- [x] Solicitar revisión independiente de la rama completa con diseño y plan. Resolver hallazgos críticos/importantes mediante reproducción y regresiones; repetir las pruebas afectadas. La comparación de semántica y artefactos ignora solo identidad operativa, rutas y tiempos, no parámetros, prioridades, bindings ni código de control.
- [x] Documentar el recorrido nuevo, su identidad y la capacidad PID pendiente. Actualizar el estado del plan y memoria con comandos, resultados y límites reales; no afirmar compilación TIA o ejecución PLCSIM si no se efectuaron.
- [x] Comprobar hashes protegidos y CRC del respaldo. Integrar únicamente los archivos del cambio cuyo hash principal siga coincidiendo con el respaldo; copiar también todos los módulos nuevos importados. Conservar el índice principal. Ejecutar en el árbol integrado las cinco pruebas nuevas y un subconjunto de parser, composición, asignación y evaluación diferida que compruebe las importaciones reales.
- [x] Escribir `runtime/shared_product_engine_delivery.json` con commit, archivos/hashes, respaldo, suites, revisión, contratos probados y capacidades pendientes. Comprobar que el congelamiento histórico sigue bloqueando el árbol mejorado y que su manifiesto no cambió. Commit final de documentación únicamente en la rama aislada.

## Autorrevisión del plan

- Contrato común y ausencia de ayuda privilegiada: tareas 1 y 3. Preparación del mapa y persistencia aislada: tareas 2 y 3.
- Aclaraciones y programas componibles: tareas 1 y 3. Identidad y lectura histórica sin regeneración: tarea 4.
- Límite experimental PID nativo, P01–P12 y veredictos: tareas 4 y 5. Freeze, audio, evidencia, respaldo e integración: tarea 6.
- Se mantienen los mismos nombres y tipos entre productores y consumidores. Los cinco puntos de Review Focus tienen pruebas asignadas. El soporte dinámico experimental del PID nativo, puesta en marcha física y nueva campaña formal quedan fuera de esta entrega según el diseño aprobado.

## Método recomendado

Ejecución nativa en esta sesión: las tareas comparten los contratos del motor, el mapa y la evidencia, por lo que implementarlas secuencialmente reduce cambios concurrentes sobre `gui.py` y `deferred_evaluator.py`. Una revisión independiente de toda la rama se realiza antes de integrar. La alternativa por agentes requiere elección explícita del usuario. No iniciar implementación hasta revisar este plan y recibir la elección del método.

## Resultado de esta ejecucion

Implementado y verificado el 17 de octubre de 2026. Suite final: 1904 passed, 7 skipped, 1 xfailed; comprobacion integrada: 113 passed. Reproduccion offline: 8/8 interpretaciones equivalentes y 5/5 pares generables con SCL exacto. Revision independiente: dos hallazgos importantes reproducidos y corregidos en una sola pasada; sin menores diferidos. No hubo API nueva, TIA, PLCSIM, descarga, campa?a FORMAL ni nuevo freeze. Respaldo y hashes protegidos verificados. Informe: runtime/shared_product_engine_delivery.json.
