# Cierre pre-FORMAL del benchmark v3 (rama `feat/preformal-readiness-v3`)

Fecha: 2026-10-12. Objetivo: cerrar los bloqueos conocidos antes del freeze del software, sin tocar el benchmark v3,
los Oracles congelados, el benchmark v2 histórico, el mapa físico ni el MASTER TIA. Ningún cambio se hizo para
"conseguir PASS" en un ensayo concreto: todos son capacidades generales derivadas de intent, requisitos, roles,
contratos, capacidades y mapa experimental (nunca de `case_id`). El ensayo `P06_V1_TEXT_DEV_004` se conserva como
evidencia DEVELOPMENT válida.

## 1. Conflictos internos de requisitos funcionales

- Tabla declarativa `functional_requirements.FUNCTIONAL_REQUIREMENT_CONFLICTS` (tipos incompatibles + parámetros que
  anulan el conflicto). Revisado todo el catálogo: solo `set_auto_mode` ↔ `set_manual_mode` son incompatibles por sí
  mismos; con `auto_input` (selección del operador) forman un selector coherente. `enable_pid`/`disable_pid` componen;
  `automatic_mode`/`manual_mode` describen un selector; los tipos por actor se comparan por `target`.
- `detect_functional_requirement_conflicts(requirements, parameters)` → `INCOMPATIBLE_REQUIREMENTS` estructurado →
  `semantic_validation.is_valid = False`, `requires_clarification = True` (política actual): nunca llega a IR/SCL.
- La interpretación real de `P06_V1_TEXT_DEV_004` se detiene ahora en la semántica (test dedicado).

### Defectos del parser corregidos (encontrados al auditar el pipeline)

1. `_attach_rule_based_functional_requirements` comparaba el TIPO de requisito con NOMBRES de variables de proceso
   (`PID_PROCESS_VARIABLES`): la condición nunca era cierta y adjuntaba tipos PID a interpretaciones discretas. Ahora usa
   el catálogo de tipos PID (igual que `compute_semantic_coverage`).
2. La fusión LLM+reglas añadía requisitos detectados por palabras clave que el LLM no produjo **sin volver a validar**
   (sin detección de conflictos). Ahora solo fusiona tipos del mismo dominio que la intención final y **revalida** el
   resultado fusionado.
3. Con respuesta inyectada (`llm_response_text`), la segunda pasada por cobertura llamaba al LLM real. Ahora nunca hay
   reintento en red con respuesta inyectada; la auditoría usa además un cliente que prohíbe cualquier llamada.
   **Incidente:** antes de esta corrección, la primera medición de referencia de esta sesión disparó ~7 llamadas reales
   al LLM (reintentos de cobertura de D05, D13, P03, P06, P08 y dos depuraciones de D05). No afectaron a ningún ensayo
   ni se persistieron.

## 2. PRE-FORMAL PROMPT REFINEMENT

Refinamiento del catálogo semántico antes de la evaluación formal (no es una corrección de resultados):

- Sección PID del prompt reescrita: sin IDs de casos ni ejemplos cercanos al benchmark (se eliminó el ejemplo "similar
  a P12" y la mención "casos P01-P12"); nueva subsección **ACCIÓN frente a CONDICIÓN**; semántica de cada tipo PID:
  `set_auto_mode`/`set_manual_mode` = orden explícita de cambiar el modo (con `auto_input`, el modo sigue la selección);
  `enable_pid` = habilitación supervisora bajo las condiciones del sistema, **no implica cambiar el modo**;
  nuevos `reject_unsafe_setpoint`, `enable_pump`, `manual_pump_enable`; ejemplos neutrales.
- Ejemplo de `INT_MUTUAL_INTERLOCK` con el contrato vigente (una orden por contactor), sin texto del benchmark.
- `expected_parameters` de cada intent se DERIVA ahora de sus contratos (`INTENT_RESOURCE_TABLE`, claves opcionales,
  valores funcionales, reglas): antes muchos intents no comunicaban al LLM los nombres de parámetro por los que el arnés
  resuelve los roles.
- Descripciones del catálogo enviadas al LLM sin IDs de casos.
- Heurística de cobertura (palabras clave) alineada con ACCIÓN/CONDICIÓN y sin tildes: "modo automático", "alarma
  activa", "bloquea el arranque", "fuera de ese rango" o "reinicia la cuenta" ya no sugieren al LLM requisitos que el
  comando no pide. Sobre el comando canónico y las 96 variantes solo queda una sugerencia, lingüísticamente correcta
  (P12 V3, "deshabilita el PID" → `disable_pid`, que compone con la condición segura).

## 3. P03: rango 0-100 %

`config/pid_supervisor_config.json → level_setpoint` = 0-100 %. `semantic_validator` lee la configuración sin valores
codificados (sin rango configurado no inventa uno). Apariciones legacy de 10/90: config (corregida, activa); fallback
codificado del validador (eliminado, activo); test de rango (actualizado); docs 21 y p03 (actualizadas); convención C-PID
dentro de los Oracles P congelados (texto informativo histórico, no se evalúa, no se modifica).

## 4-5. SAFETY_TRIP simulado y mapa experimental de simulación

- `data/plc_maps/mapa_experimental_simulacion.json` (16 DI + 16 DO en un rango disjunto del banco; `simulation_only`;
  `harness_signals.SAFETY_TRIP = I_Emergency`). El mapa físico sigue byte-idéntico.
- `config/experiment_maps.json` + `trial_experiments.experiment_maps`: selección determinista por capacidad (roles IO
  del Oracle: entradas, salidas, señales restringidas). Cableada en la GUI/lote (`_prepare_trial_working_map`) y
  congelada como evidencia (`trial.json → experiment_map`, también en `evaluation_report.json`).
- `INT_EMERGENCY_PRIORITY` admite la ruta de arranque (`trigger_input`, y `stop_input` si hay paro) subordinada a la
  emergencia; salida auxiliar y alarma pasan a opcionales (evitaban ambigüedad de roles).
- Resultado: D05/P07 → simulación; D14 cabe en el banco (3 DI + 3 DO de 8/8).

## 6. Taxonomía de requisitos

`FUNCTIONAL_REQUIREMENT_ALIASES` (`manual_pump_limit` → `manual_pump_enable`, `enable_pid_in_auto` → `enable_pid`),
normalizados al entrar al pipeline y al comparar con `required_functional_requirements` del Oracle (sin tocar Oracles).
`manual_pump_limit` designa el mismo concepto (operación manual de la bomba en Manual); su implementación anterior no
leía ninguna orden manual (GAP-P08) y ahora sigue la orden del operador. `INT_MUTUAL_INTERLOCK`: `trigger_input` /
`stop_input` son alias históricos de `request_a` / `request_b` (`ir_builder.INTENT_SLOT_ALIASES`).

## 7. Capacidades generales completadas

| Capacidad | Antes | Ahora |
|---|---|---|
| `set_auto_mode` + `auto_input` | `Auto_Mode := TRUE` incondicional | el modo sigue la selección del operador |
| `reject_unsafe_setpoint` | inexistente (constante del comando) | `Level_SP_Command` → `Level_SP` solo en [min, max]; fuera, conserva el último válido |
| SAFETY_TRIP / `disable_pid` | sin señal en el banco | señal de simulación; `enable_pid` incluye `NOT emergency` |
| `manual_pump_enable` | bomba ON en Manual sin orden | en Manual la bomba sigue solo `manual_pump_input` |
| `sensor_range_fault` + `conditional_alarm_reset` | la falla no activaba la alarma | la falla enclava la alarma; Reset solo la borra sin falla |
| `enable_pump` / `safe_overfill_stop` | bomba nunca habilitada; parada segura enclavada (exigía Reset) | bomba en marcha normal; condición segura solo mientras dure (`comparison` `>=` / `>`), recuperación automática |
| `INT_MUTUAL_INTERLOCK` | Start/Stop como órdenes, contactores enclavados | cada contactor sigue su orden con exclusión mutua |
| `INT_VFD_ENABLE_NO_ALARM` | leía una SALIDA de alarma | `alarm_input` (condición de entrada) |
| `INT_MANUAL_AUTO_MODE` | selectores + Start/Stop comunes | `auto_input` + orden propia por modo |
| `INT_SEQUENCE_THREE_STEPS` | un paso por ciclo, sin espera | salida principal + auxiliar tras `delay_time` |
| `INT_SENSOR_TIMEOUT_ALARM` | supervisaba desde el arranque del PLC | supervisión armada por `trigger_input` |
| `INT_STATUS_PILOTS` | sin piloto de detenido, falla = emergencia | `run_state_input`/`fault_input` → detenido/marcha/falla, uno solo |
| `INT_AUTO_CYCLE` | un estado por ciclo, sin finalizado | ciclo temporizado `cycle_time`, `complete_output` hasta Reset |
| `INT_SPEED_SELECTION` (nuevo) | sin intent (D14) | solo la velocidad seleccionada; nunca dos |

Las formas históricas se conservan donde no contradicen la capacidad (claves opcionales/alias).

## 8. Validación de composición

`composition_check.analyze_composition` (mismo parser que el simulador, con plegado de constantes): escritores por
variable (incondicionales/condicionales) y `COMPOSITION_CONFLICT` si una variable recibe dos escrituras
incondicionales distintas en el mismo ciclo (p.ej. `Auto_Mode := TRUE` y `Auto_Mode := FALSE`). Integrado en
`project_packager`: un conflicto invalida la verificación y queda `composition_report.json` en el paquete. Calibrado
con los 170 programas generados reales: solo marca los dos programas contradictorios de P06 (0 falsos positivos).

## 9. evaluation_report completo

El informe se construía con un `trial.json` leído antes de persistir el patch de la evaluación (compile/download/runtime
nulos). Ahora se reescribe tras persistir el resultado definitivo, con `stage_summary` de la fuente única
`deferred_evaluator.trial_stage_summary` (semantic, semantic_benchmark, io_allocation, ir, compilation, tia_archive,
download, runtime, functional, safety, final_verdict) más `experiment_map`, `io_map` y `tia_archive`. Los resultados
históricos no se modifican.

## 10. Auditoría de preparación (`scripts/preformal_readiness_audit.py`)

READ-ONLY, sin LLM/TIA/PLCSIM. Para cada caso: Oracle FROZEN, capacidad semántica, requisitos soportados, recursos de
mapa, generación (IR + SCL + verificador + composición), roles del Oracle, capacidades Runtime y comportamiento del SCL
generado simulado contra el Oracle congelado (`trial_experiments.scl_sim`). Interpretaciones de referencia en
`data/preformal/reference_interpretations.json` (nunca se envían al LLM). El simulador reproduce exactamente el
veredicto de los 37 ensayos reales TIA/PLCSIM existentes (PASS, FAIL por sobrescritura, REVIEW). Resultado:
**32/32 EVALUABLE** (`docs/preformal_readiness_report.md`). Evaluable no significa PASS del LLM.

## Riesgos conocidos (no bloqueantes)

- `INTENT_PARAMETER_RULES.required` exige al parser recursos que el comando no menciona (p.ej. `stop_input` en
  `INT_DELAYED_START`, `reset_input` en `INT_COUNTER_PULSES`); el LLM los ve en `expected_parameters` y los suele
  incluir, pero si los omite el ensayo falla en semántica. Es una decisión de diseño previa que no se cambió.
- El mapa de simulación usa bytes de E/S (`%I20.x`/`%Q20.x`) sin módulo en el hardware del MASTER; el bridge escribe por
  imagen de proceso. Los pilotos reales lo verifican.
- Las descripciones `related_cases` del catálogo conservan IDs (no se envían al LLM).
