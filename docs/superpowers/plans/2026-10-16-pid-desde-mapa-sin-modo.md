# PID desde el mapa IO Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generar un controlador PID de nivel conectado al mapa IO, idéntico para PLCSIM y PLC compatible, con un modelo de tanque externo para comprobarlo.

**Architecture:** El normalizador resuelve conexiones hardware o REAL en DB y el generador produce un único controlador sin modo ni planta integrada. El servicio de descarga aplica los requisitos del destino. Un proveedor de prueba independiente alimenta exclusivamente las mediciones declaradas y observa el mando real mediante una sesión persistente de PLCSIM.

**Tech Stack:** Python 3, pytest, CustomTkinter, SCL, TIA Portal V18/Openness, C#/.NET Framework, PLCSIM Advanced Runtime API 5.0.

**Spec:** [Diseño aprobado](../specs/2026-10-16-pid-desde-mapa-sin-modo-design.md), aprobado expresamente por el usuario el 2026-10-16.

## Global Constraints

- Alcance: un lazo de nivel, acción FILL/DRAIN, actuador proporcional, PID_Compact 2.3 y OB de 100 ms.
- Misma orden y mapa producen SCL/OB idénticos entre destinos; el modelo y la conexión no participan en la huella del controlador.
- Sin modelo embebido, selección de entorno PID, dispositivos inventados ni confirmación automática de calibraciones.
- Conservar Start por flanco, Stop/emergencia prioritarios, fallo enclavado, Reset sin rearranque, un escritor y diagnóstico retenido.
- Rangos completos ASSUMED_FOR_TEST permiten generar/compilar/ensayar en PLCSIM; descargar a hardware exige confirmación y compatibilidad verificadas.
- No descargar al PLC físico durante este desarrollo; conservar plantilla original/MASTER, mapas activos y evidencias históricas.
- Paquetes v1 conservan su contrato; supervisor experimental, programas digitales, Oracles y freezes anteriores no se reescriben.
- Trabajar en runtime/worktrees/pid-io-map-driven, rama feat/pid-io-map-driven; no stage/stash/revert del índice original.
- Respaldo restaurable verificado: runtime/backups/pre_pid_io_unificado_20261016_143014; base de la rama: 66 pruebas aprobadas.
- Resultados online requieren sincronización manual con TIA antes de otra descarga; no agregar una carga online automática.

## Review Focus

1. Un sensor hardware y otro DB igualmente compatibles deben pedir aclaración, incluso al cambiar de destino (tarea 3).
2. Nombres de DB/miembros con distinta capitalización o colisión con calidad deben rechazarse antes de importar (tareas 1 y 5).
3. Consigna/sobrellenado en otra unidad deben convertirse una sola vez; NaN/Infinity nunca constituyen datos válidos (tareas 1, 3 y 4).
4. Un programa sustituido durante una prueba debe detener las escrituras sin ejecutar Stop/restauración con identidad antigua ni declarar PASS (tarea 6).
5. Un canal sin raw de fallo representable ni calidad declarada debe informar inyección no disponible, sin fabricar éxito (tareas 7 y 9).

---

## Estructura e interfaces compartidas

Mantener los módulos existentes y extraer únicamente las responsabilidades nuevas:

| Archivos | Responsabilidad |
| --- | --- |
| `src/process_signals.py` (nuevo), `src/gui_helpers.py`, `src/plc_maps/map_validator.py` | Contrato de señales DB, normalización, permisos y conflictos de almacenamiento. |
| `src/process_signal_editor.py` (nuevo), `src/io_variable_editor.py` | Edición de señales REAL de proceso y sus unidades. |
| `src/pid_control.py`, `src/plc_ir.py`, `src/ir_builder.py`, `src/llm_parser.py`, `src/normal_interaction.py`, `src/llm_context_builder.py`, `src/semantic_validator.py` | Resolución determinista y nueva IR sin modo/modelo. |
| `src/pid_scl.py`, `src/code_generator.py`, `src/platforms/siemens_scl_adapter.py`, `src/verifier.py` | Controlador único y fuentes de DB propios. |
| `src/pid_package.py`, `src/pid_tia_contract.py`, `src/tia_openness.py`, `tia_openness_bridge/PidControlSupport.cs`, `tia_openness_bridge/Program.cs` | Manifiesto v2, importación, propiedad, compatibilidad y descarga. |
| `src/pid_plant_io.py` (nuevo), `plcsim_runtime_bridge/PidPlantSession.cs` (nuevo), `plcsim_runtime_bridge/Program.cs` | Sesión persistente y acceso de prueba tipado con identidad comprobada. |
| `src/pid_tank_model.py`, `src/pid_plant_test.py` (nuevos), `src/pid_acceptance.py`, `scripts/validate_native_pid.py` | Modelo externo, trabajos cancelables y protocolo/evidencia. |
| `src/pid_commissioning.py`, `src/pid_commissioning_view.py`, `src/gui.py` | Puesta en marcha y prueba separada, sin selector de entorno PID. |
| `config/native_pid_map_defaults.json`, `config/pid_tank_test_profile.json`, `data/plc_maps/examples/pid_tank_db.json` (nuevos) | Defaults nuevos sin demo, perfil versionado y mapa DB separado, nunca activado automáticamente. Conservar config/native_pid_defaults.json para v1. |

**Binding serializable único:** dict con `schema_version=1`, `representation=HARDWARE_RAW/DB_ENGINEERING`, `name`, `role=MEASUREMENT/MANIPULATED`, `quantity`, `unit`, `engineering_min/max`, `permission` y `provenance`. Hardware añade `address`, `data_type=INT` y copia de `analog_config`; DB añade `data_type=REAL`, `storage={kind:GENERATED_DB,db,member}`, `validity_member` para medición o `fault_value` para mando. No contiene destino, modelo ni modo. No mantener dos esquemas de binding entre IR, manifiesto y pruebas.

**Almacenamiento de mapa DB:** entrada `class=internal`, `type=REAL`, `location=''`, nombre funcional conforme a la convención existente y `process_config` del diseño; conservar alias, función y `llm_allowed/state`. La representación depende de metadatos explícitos, no del prefijo del nombre. `process_config` se copia profundamente al normalizar/guardar.

**Protocolo de prueba persistente:** nueva acción de puente `pid_plant_session`, JSON Lines por stdin/stdout, un request/response por `id`. Inicio verifica manifiesto/instancia/RUN/16 palabras Build y captura entradas. Operaciones `probe_input_word`, `exchange`, `close`; `exchange` acepta solo medición/calidad declaradas y devuelve lectura del mando y diagnósticos. stderr contiene logs, stdout solo protocolo. EOF, plazo máximo e inactividad provocan cierre comprobado. Las órdenes de puesta en marcha conservan su ruta existente y sus guardas, fuera de los ticks del modelo.

### Tarea 1: Contrato y persistencia de señales de proceso

**Files:** crear `src/process_signals.py`, `tests/test_process_signals.py`; modificar `src/gui_helpers.py`, `src/plc_maps/map_validator.py`, `tests/test_map_persistence_isolation.py`.

**Interfaces:** produce `process_configuration_report(entry: dict) -> dict` con errors/warnings/is_valid; `normalize_process_binding(entry: dict, role: str) -> dict` (lanza ValueError con código/campo); `validate_process_storage(bindings: list[dict]) -> list[str]`. Consumir `analog_configuration_report` sin cambiar el significado histórico de ready/confirmed.

- [ ] Escribir pruebas `test_db_roundtrip_preserves_metadata_and_permission`, `test_storage_collision_case_insensitive`, `test_measurement_requires_distinct_quality`, `test_nonfinite_and_fault_value_rejected`. Afirmar copia independiente, calidad BOOL inicialmente false, sin dirección fabricada, rechazo de NaN/Infinity/rangos invertidos/fault_value fuera del rango y colisiones entre REAL y calidad.
- [ ] RED: ejecutar `& $py -B -m pytest -q tests/test_process_signals.py`; esperar fallo por contrato nuevo ausente.
- [ ] Implementar las tres funciones, validación de identificadores Siemens y representación, extensión acotada REAL/DB en helpers y validador; conservar reglas físicas existentes. Datos incompletos reportan nombre y campo; no mutar el mapa ni analog_config.confirmed.
- [ ] GREEN: ejecutar el archivo nuevo y `tests/test_plc_maps_map_validator.py tests/test_map_persistence_isolation.py tests/test_analog_configuration.py`; esperar todos aprobados.
- [ ] Commit acotado: `feat: define explicit process signal bindings` con los cinco archivos de esta tarea.

### Tarea 2: Editor y mapa DB de ejemplo

**Files:** crear `src/process_signal_editor.py`, `tests/test_gui_process_signals.py`, `data/plc_maps/examples/pid_tank_db.json`; modificar `src/io_variable_editor.py`, `tests/test_gui_variable_editor.py`.

**Interfaces:** consume contrato de tarea 1; produce `ProcessSignalConfigurationPanel(master, entry: dict)` con `get_config() -> dict`. Nuevo kind «Señal de proceso en DB» usa REAL sin location y rol seleccionable. Ejemplo declara `DB_TankProcess.Level`, calidad `LevelValid`, mando `FillCommand`, rango 0–100 %, más recursos digitales explícitos compatibles con el ejemplo.

- [ ] Escribir `test_db_kind_selects_real_and_hides_address`, `test_process_editor_roundtrip_and_units`, `test_example_does_not_change_active_map`; afirmar cambio de rol, selectores de magnitud/unidad existentes, errores visibles y conservación de permisos; hash del mapa activo/puntero idéntico.
- [ ] RED: `& $py -B -m pytest -q tests/test_gui_process_signals.py`; esperar kind/panel ausente.
- [ ] Implementar panel con los selectores de unidades existentes, validación tarea 1 y edición de db/member/calidad/fault_value; integrar en diálogo completo sin reestructurar GUI ni habilitar modelos al guardar. Añadir ejemplo separado.
- [ ] GREEN: ejecutar pruebas nuevas y `tests/test_gui_variable_editor.py tests/test_gui_full_map_window.py tests/test_gui_engineering_units.py`; esperar aprobadas, más comprobación visual con creación/edición y cancelación sin guardar.
- [ ] Commit acotado: `feat: edit explicit DB process signals` con los cinco archivos de la tarea.

### Tarea 3: Semántica y resolución independientes del destino

**Files:** modificar módulos semánticos/IR de la tabla, `tests/test_native_pid_resolution.py`; crear `tests/test_pid_map_driven_semantics.py`.

**Interfaces:** consume `normalize_process_binding`; produce `normalize_native_pid_command(semantic: dict) -> dict` en `pid_control.py`, copia sin flags antiguos y con `metadata.pid_legacy_fields_ignored` para su procedencia. Cambiar `resolve_pid_loops(requirements: list[dict], io_map: dict, target_platform: str) -> list[PLCPIDLoop]`. Nueva PLCPIDLoop conserva campos de proceso/control/recursos/símbolos y reemplaza mode/input_config/output_config/simulation por `input_binding: dict`, `output_binding: dict`, `overfill_limit: float | None`; no serializar propiedades antiguas. Los v1 se leen desde manifiesto, no se convierten a esta IR.

- [ ] Escribir `test_legacy_llm_modes_do_not_change_native_ir`, `test_hardware_db_ambiguity_has_no_destination_preference`, `test_missing_resources_never_create_model`, `test_units_convert_setpoint_and_overfill_once`, `test_yes_does_not_confirm_calibration`. Afirmar resolución por alias/permiso, diagnóstico concreto de faltante/ambigüedad/unidad, y equivalencia de IR de control ignorando únicamente la traza de procedencia.
- [ ] RED: ejecutar `& $py -B -m pytest -q tests/test_pid_map_driven_semantics.py`; esperar dependencia antigua de modo o falta de bindings.
- [ ] Implementar normalización antes de validar/reintentar en Normal; eliminar preguntas/ejemplos de entorno PID de contexto/política. Permitir generar con rangos completos no confirmados y traza intacta. Actualizar consumidores de la IR. Mantener supervisor histórico sin cambios y evitar eliminar globalmente el nombre intent_id que comparte con casos nativos.
- [ ] GREEN: ejecutar pruebas nuevas, resolución nativa y `tests/test_pid_supervisor.py tests/test_normal_functional_composition.py tests/test_autonomous_resource_resolution.py`; esperar aprobadas.
- [ ] Commit acotado: `feat: resolve native PID solely from process map` con módulos semánticos/IR y pruebas modificadas de esta tarea.

### Tarea 4: Un controlador SCL y manifiesto v2

**Files:** modificar `src/pid_scl.py`, `src/code_generator.py`, `src/platforms/siemens_scl_adapter.py`, `src/verifier.py`, `tests/test_native_pid_generation.py`; crear `tests/test_pid_map_driven_generation.py`, `config/native_pid_map_defaults.json`.

**Interfaces:** consume nueva PLCPIDLoop; conserva `render_pid_body(loop) -> str`, `build_pid_infrastructure(project) -> dict`, `render_pid_source(project, adapter) -> str`, `render_pid_cyclic_ob(project, capabilities) -> str`. Produce manifiesto schema_version=2, owner `VozLlmPlcAgent.NativePID.v2`, bindings y `process_dbs` (db, owner, miembros tipados/iniciales, huella). Fuentes DB agrupadas preceden FB consumidor. La huella incluye implementación de bindings/SCL/escalas, excluye perfil y destino.

- [ ] Escribir `test_identical_sources_across_destinations`, `test_relocated_hardware_is_read_scaled_and_written`, `test_db_quality_and_no_electrical_scaling`, `test_single_pid_call_and_latched_diagnostics`, `test_no_demo_or_implicit_auto`. Afirmar ausencia de mode/SimLevel/tasas, AO real en ambas conexiones, calidad false bloqueante, valores no finitos bloqueados, manual inicial cero y sin ganancias demo/ParametersConfirmed inventado.
- [ ] RED: `& $py -B -m pytest -q tests/test_pid_map_driven_generation.py`; esperar diferencias/fragmentos antiguos.
- [ ] Implementar orden de ciclo del diseño, conversión por representación y mandos digitales solicitados, prioridades/fallos retenidos y Reset+flanco nuevo; generar DB propios y v2. Defaults nuevos fijan tecnología2.3,period100 y controller.status=UNTUNED sin ganancias demo; conservar defaults v1 históricos. Actualizar verificador sin rebajar las restricciones de escritor único ni sustituir con un test textual la ejecución requerida.
- [ ] GREEN: ejecutar generación nueva/nativa, `tests/test_analog_scaling_generation.py tests/test_normal_program_bindings.py tests/test_normal_mode_hardening.py`; esperar aprobadas; comparar SCL y XML por bytes en la prueba de equivalencia.
- [ ] Commit acotado: `feat: generate one map-bound native PID controller` con archivos de esta tarea.

### Tarea 5: Importación TIA, propiedad y autorización de descarga

**Files:** modificar módulos de paquetes/TIA de la tabla, `tests/test_native_pid_package.py`, `tests/test_tia_pid_support.py`; crear `tests/test_pid_manifest_v2.py`.

**Interfaces:** consume manifiesto v2. Conservar `validate_pid_manifest(m: dict) -> dict`, `native_request(package_dir: Path, root: Path, template: str) -> dict`, `native_download_project(package_dir: Path, root: Path, target_type: str) -> str`; despachar validación explícita v1/v2. C# conservar `ValidateManifest(Dictionary<string,object>)` y agregar `ValidateProcessDbOwnership(manifest: Dictionary<string,object>, blocks: IEnumerable<PlcBlock>) -> void` en PidControlSupport. Revalidar compatibilidad y propiedad inmediatamente antes de descargar.

- [ ] Escribir `test_v1_restrictions_survive_v2_support`, `test_v2_assumed_ranges_compile_but_physical_download_denied`, `test_foreign_db_and_case_collision_fail_before_import`, `test_verified_offline_parameters_preserved_demo_not_promoted`. Afirmar sin migración por borrar mode, sin mutación de confirmación y cache segregada por contrato/huella.
- [ ] RED: `& $py -B -m pytest -q tests/test_pid_manifest_v2.py`; esperar rechazo v2/no guardas nuevas.
- [ ] Implementar dispatch Python/C#, validación de DB/miembros/fuentes/huellas, importación ordenada solo en copia Archive/Retrieve y marcadores propios verificables. Mantener las defensas de objetos ajenos/OB ejecutables y preservar solo parámetros offline verificados compatibles; no reutilizar demo v1 como parámetros confirmados v2.
- [ ] GREEN: ejecutar pruebas nuevas/paquetes/TIA y compilar ambos puentes con sus proyectos existentes. Después compilar paquete hardware y DB en copias aisladas TIA V18: reportar error_count=0, PID_Compact2.3, OB100000 µs y pertenencia; reimportar y comprobar parámetros offline. Registrar solicitudes Openness para aprobación del usuario si aparecen; nunca aceptarlas automáticamente.
- [ ] Commit acotado: `feat: import map-driven PID packages with ownership checks` con archivos de esta tarea. Guardar evidencia TIA en runtime separado, sin commit de binarios/proyectos.

### Tarea 6: Transporte persistente de prueba con guardas y palabra real

**Files:** crear `src/pid_plant_io.py`, `plcsim_runtime_bridge/PidPlantSession.cs`, `tests/test_pid_plant_io.py`; modificar `plcsim_runtime_bridge/Program.cs` y proyecto de compilación si usa inclusión explícita; añadir pruebas C# al contrato existente.

**Interfaces:** consume manifiesto v2/compilación/16 Build y bindings. Produce `PidPlantIOSession(package_dir: Path, target: dict, report_dir: Path, deadline_s: float)` con `start() -> dict`, `probe_input_word() -> dict`, `exchange(measurement: float, valid: bool) -> dict`, `close() -> dict`. Es context manager y propietario de un Popen; cada respuesta devuelve mando raw/EU y diagnósticos con tiempos y huella. C# `PidPlantSession.Run(request: Dictionary<string,object>) -> int` atiende el protocolo común descrito arriba.

- [ ] Escribir `test_rejects_q_m_foreign_db_and_physical_target`, `test_program_change_blocks_tick_and_stale_cleanup`, `test_timeout_eof_and_cancel_capture_failed_cleanup`, `test_word_probe_requires_both_readbacks_and_restore`. Afirmar validación antes de cada escritura, ausencia de cualquier escritura con descriptor caducado, no false PASS y un solo proceso para múltiples ticks.
- [ ] RED: `& $py -B -m pytest -q tests/test_pid_plant_io.py`; esperar sesión ausente.
- [ ] Implementar sesión con deadline/inactividad y cierre en finally. Guardar originales; leer QW o mando DB sin escribirlos; escribir únicamente IW INT16 o REAL/calidad declarados. Mantener intactas las guardas BOOL/REAL existentes. Usar API ReadBytes/WriteBytes para palabras y verificar TagInfos/símbolo; no ampliar capacidades históricas del Oracle automáticamente.
- [ ] GREEN offline: ejecutar pruebas nuevas, `tests/test_phase2b_runtime_io.py tests/test_process_variable_runtime.py tests/test_pid_commissioning.py` y selftests C#. GREEN Siemens: con TESIS_PLC_SIM/RUN y paquete v2 cargado, detener control y comprobar 0/13824/27648 por dirección y símbolo, determinar byte order, restaurar original; guardar informe. Si falla, bloquear modelo y reparar transporte, sin fallback embebido.
- [ ] Commit acotado: `feat: add guarded persistent PID plant IO` con archivos de esta tarea.

### Tarea 7: Modelo externo, trabajo cancelable y protocolo reproducible

**Files:** crear `src/pid_tank_model.py`, `src/pid_plant_test.py`, `config/pid_tank_test_profile.json`, `tests/test_pid_external_plant.py`; modificar `src/pid_acceptance.py`, `scripts/validate_native_pid.py`, `tests/test_native_pid_acceptance.py`.

**Interfaces:** consume PidPlantIOSession. Produce `TankModel(profile: dict, input_binding: dict, output_binding: dict)` con `step(command_percent: float, dt_s: float) -> float` y estado `level`; `run_tank_test(package_dir: Path, target: dict, profile: dict, cancel: threading.Event, report_dir: Path) -> dict`. Conservar evaluador numérico separado de la prueba de ejecución nativa. Mantener validación histórica v1 explícita, sin reescribir script/evidencias antiguas bajo significado nuevo.

- [ ] Escribir `test_profile_units_and_quantized_roundtrip`, `test_model_reads_actual_mapped_output_only`, `test_cancel_stops_and_restores_with_valid_identity`, `test_sensor_injection_unavailable_is_not_pass`, `test_evidence_is_unique_and_requires_native_proof`. Afirmar perfil v1: inicial20 %, fill2 %span/s, drain0.8 %span/s; dt medido explícito, límites, FILL/DRAIN y no escritura de PV/CV privados/ganancias.
- [ ] RED: `& $py -B -m pytest -q tests/test_pid_external_plant.py`; esperar modelo/trabajo ausente.
- [ ] Implementar integración del tanque independiente de IR/SCL y bucle nominal100ms en Python con el único proceso persistente. Recoger jitter/gaps, raw/EU/SP/CV/calidad/estado/error/parámetros y SHA de artefactos/perfil; carpeta UUID por intento y reporte incremental también en error. Inyección por raw INT16 representable fuera de rango o calidad explícita; sin opción, registrar UNSUPPORTED y no aprobar caso. No retocar tasas/umbrales automáticamente por convergencia fallida.
- [ ] GREEN: ejecutar nuevas pruebas y aceptación existente. Extender script con protocolo v2 hardware/DB: manual, presintonización nativa válida, Start,50/40/60 %, Stop, emergencia, sensor, límites, sobrellenado y Reset manteniendo Start; criterios ±2 puntos porcentuales convertidos al rango,10s continuos antes300s por consigna. Distinguir diagnóstico offline de ejecución Siemens.
- [ ] Commit acotado: `feat: test native PID with an external tank model` con archivos de esta tarea.

### Tarea 8: Interfaz sin entorno PID y prueba separada

**Files:** modificar `src/gui.py`, `src/pid_commissioning.py`, `src/pid_commissioning_view.py`, `tests/test_gui_pid_commissioning.py`, `tests/test_pid_commissioning.py`; crear `tests/test_gui_pid_plant_test.py`.

**Interfaces:** consume bindings v2 y `run_tank_test`. Conservar `build_pid_process_bindings(project) -> dict`, `validate_commissioning_write(bindings, name, value, execution_context) -> dict` (signal/value/pulse) y API read/write de PidCommissioningSession, con dispatch histórico explícito donde se abran v1. Extender `PidCommissioningPanel` con callbacks opcionales `on_test` y `on_cancel_test`, y `show_test_status(report: dict) -> None`. No pasar datos de widgets al hilo de trabajo.

- [ ] Escribir `test_no_pid_environment_selector_or_injection`, `test_open_panel_never_starts_model`, `test_test_job_background_cancel_and_single_owner`, `test_manual_to_tune_group_and_physical_selector_priority`. Afirmar generación sin pid_execution_mode, apertura sin writes y botón «Probar con modelo de tanque» separado, disponible solo con target/runtime/paquete válidos; thread UI sigue respondiendo.
- [ ] RED: `& $py -B -m pytest -q tests/test_gui_pid_plant_test.py`; esperar selector presente/callbacks ausentes.
- [ ] Retirar únicamente controles de entorno PID y su inyección semántica, conservar plataforma/parser/conexión/mapa y Auto/Manual. Publicar estado del trabajo mediante after/cola, cancelar al cerrar y mostrar cierre fallido/identidad cambiada. Separar gate de descarga física de las escrituras PLCSIM de puesta en marcha; no impedir prueba con rangos completos supuestos ni confirmarlos.
- [ ] GREEN: ejecutar nuevas pruebas, GUI/commissioning existentes y comprobar visualmente generación, apertura, ejecución/cancelación y cierre sin congelar interfaz. Mantener grupo CmdManual=false+pretune y bloqueos de mandos físicos.
- [ ] Commit acotado: `feat: expose destination-independent PID commissioning` con archivos de esta tarea.

### Tarea 9: Aceptación real, regresión, revisión e integración

**Files:** crear `docs/24_pid_unificado_desde_mapa.md`; modificar `docs/23_pid_nativo_desde_mapa.md` con enlace de evolución y `src/trial_experiments/software_freeze.py` solo para incluir módulos nuevos en futuras huellas; ampliar pruebas de freeze pertinentes. No editar resultados/freezes existentes.

**Interfaces:** consume todos los artefactos anteriores. Produce informe de entrega versionado en `runtime/pid_io_unification_delivery.json`: fuentes/commits, resultados offline y Siemens separados, hashes, guardas, modelo, calibración, limpieza, pendientes y lista exacta de archivos integrados.

- [ ] Escribir prueba `test_future_freeze_tracks_controller_and_model_separately` que detecte cambios en nuevos módulos sin cambiar freezes anteriores. Añadir comprobación de que fuentes/hash del controlador son idénticos con destinos diferentes y con perfiles distintos; cambiar escala sí cambia huella. RED antes de ajustar inventario; GREEN después.
- [ ] Ejecutar campañas Siemens nuevas para hardware IW4/QW4 y mapa DB en copias aisladas; conservar todos los intentos. Exigir probe real aprobado, PID nativo/OB real y 50/40/60 con criterios fijos más seguridad del protocolo tarea 7. No presentar UNSUPPORTED, tuning fallido o limpieza fallida como PASS; reparar causa dentro del alcance y repetir con carpeta nueva. No descargar hardware físico.
- [ ] Ejecutar `& $py -B -m pytest -q -p no:cacheprovider --basetemp .pytest_tmp/final` sobre toda la suite; registrar skips/xfail y distinguir previos de nuevos. Compilar ambos puentes y verificar hashes de plantilla, mapa activo y registros históricos conservados. Repetir checks solo tras cambios/fallos nuevos.
- [ ] Solicitar una revisión independiente nueva de la rama completa conforme a executing-plans, resolver hallazgos con pruebas específicas y revalidar lo afectado. Documentar alcance real, falta de campaña física/formal, parámetros online y restauración, sin declarar universalidad analógica.
- [ ] Commit documentación/inventario revisados con `docs: record map-driven PID validation and limits`. Integrar solo archivos propios cuya base/hash coincida con la entrega anterior o contenido previamente verificado; conflicto => inspeccionar y combinar conservando cambios del usuario. No copiar mapas de la copia aislada sobre su mapa activo, ni tocar índice original. Verificar SHA de cada archivo entregado, índice original intacto y smoke apropiado desde carpeta habitual; registrar entrega final.

## Ejecución y comprobación del plan

Al empezar en la copia aislada: `$py = 'C:/TESIS_HENRY/voz-llm-plc-agent/.venv/Scripts/python.exe'`; crear `.pytest_tmp` si falta y usar `-p no:cacheprovider --basetemp .pytest_tmp/<intento-unico>` cuando se necesiten fixtures temporales. Cada RED debe fallar por el comportamiento nuevo, no por importación/configuración accidental. Registrar comando real y resultado; los nombres de pruebas anteriores deben actualizarse únicamente cuando expresaban el contrato reemplazado, conservando cobertura v1 explícita.

Para cada commit usar `git add -- <lista exacta de Files de esa tarea>` dentro de la copia aislada y `git commit -m <mensaje indicado>`; revisar diff staged antes. No usar git add . ni modificar el índice de la carpeta habitual. Leer primero el proyecto .csproj/compilación existente antes de compilar; no adivinar versiones o rutas de MSBuild.

Autorrevisión del plan: las secciones comando/mapa/controlador/calibración/modelo/transporte/compatibilidad/evidencia del diseño corresponden a tareas 1–9. Los cinco focos de revisión tienen pruebas asignadas; los bindings y el protocolo se definen una sola vez. Las verificaciones TIA/SDK son puertas reales pendientes, separadas de las 66 pruebas de base. Este archivo planifica cambios; no certifica que estén implementados.
