# Semántica efectiva, provenance y separación Semantic / Functional

Documento técnico. Aplica desde la corrección de DEVELOPMENT registrada como DVL-002
(`development_validation_log.md`). **No es retroactivo**: los ensayos ejecutados antes conservan el
resultado que produjo el software con el que se ejecutaron.

## 1. Problema

Hasta esta corrección, el IR (`ir_builder.get_required_variables_for_intent`) y el generador
(`code_generator._param`) completaban en silencio los recursos externos que el parser no había dado
(`parameters.get("trigger_input", "I_Start")`). El programa usaba `I_Start`, `I_Stop` y
`Q_Motor_Enable`, pero `semantic_output.parameters` no los contenía. En consecuencia:

- el `io_map_snapshot.json` congelaba los canales, pero con `bindings = []` y `parameter_bindings = {}`;
- el Oracle, que resuelve roles **solo** desde `parameter_bindings` (`semantic_paths`), devolvía
  `ORACLE_ROLE_NOT_FOUND` y el ensayo quedaba en REVIEW **sin ejecutar el Runtime**, aunque el programa
  generado fuese funcionalmente correcto.

## 2. Etapa de semántica efectiva

Módulo: `src/effective_semantics.py`. Punto de inserción único: `llm_parser._repair_and_validate`, que
procesan las salidas de reglas, del LLM y de su reintento (y por tanto también el modo híbrido, Modo
Normal y Experimentación). Orden:

```
parser (reglas / LLM)
  -> semantic_repair (forma de parámetros; banco sin emergencia -> FALSE)
  -> SEMÁNTICA EFECTIVA                     <- nuevo
  -> validación semántica + IOAllocator (mismo lote de propuestas que antes)
  -> io_map_snapshot.json congelado (bindings + parameter_bindings + provenance)
  -> IR -> SCL
```

Fuente única de recursos por intent: `ir_builder.INTENT_RESOURCE_TABLE` (clave semántica, valor por
defecto), en el mismo orden en que el IR declara variables. La tabla sustituye al diccionario de
`get_required_variables_for_intent`, con salida idéntica (verificada sobre 9200 combinaciones antes del
cambio). Los valores funcionales que usa una plantilla cuando faltan (duraciones, preset) están en
`ir_builder.INTENT_VALUE_DEFAULTS`, que el generador lee.

### Reglas: nunca inventar

Una clave se completa (`source = DEFAULT`) solo si se cumplen todas estas condiciones:

1. el contrato del intent la exige (`INTENT_RESOURCE_TABLE`) y su valor por defecto es un recurso
   **externo** (`I_`, `Q_`, `AI_`, `AO_`);
2. el parser no la dio;
3. no es OPCIONAL (`OPTIONAL_PARAMETER_KEYS`: reset, alarma o pilotos solo si el comando los pidió);
4. no es una clave que el parser **debe** expresar (`INTENT_PARAMETER_RULES[intent].required`). Su
   ausencia sigue siendo el error de validación de siempre;
5. el programa no es compuesto (multi-actor o secuencia temporizada). Esos programas toman sus recursos
   de `functional_requirements`;
6. el recurso se resuelve sin ambigüedad:
   - existe en el mapa con ese nombre (LOCKED/ASSIGNED): `resolution = MAP_EXISTING`;
   - no existe: lo asigna **el mismo IOAllocator** dentro de la validación (canal FREE compatible;
     nunca LOCKED, nunca un tag fantasma): `resolution = IO_ALLOCATION`;
   - aparece dos veces en el mapa, o ese nombre ya cumple otro rol en `parameters`:
     `AMBIGUOUS_FUNCTIONAL_RESOURCE`. No se completa y la validación falla antes del IOAllocator, el IR
     y el SCL;
   - existe con otro tipo de señal: `FUNCTIONAL_RESOURCE_KIND_MISMATCH`.

La emergencia nunca se crea: si el banco no tiene `I_Emergency`, el valor es el literal `FALSE`
(categoría `SAFE_LITERAL`).

Los recursos internos (`M_`, `T_`, `C_`, `R_`) y los valores funcionales (duraciones, preset) **no** se
escriben en `parameters`. Solo se registran en `effective_semantics.internal_technical_defaults` y en
`effective_semantics.functional_value_defaults`.

### Formato

`parameters` conserva sus tipos (strings): no se convierte nada en objetos. Para D03 V2 (LLM con
`INT_MOTOR_LATCH` y sin parámetros):

```json
"parameters": {
  "emergency_input": "FALSE",
  "trigger_input": "I_Start",
  "stop_input": "I_Stop",
  "motor_output": "Q_Motor_Enable"
},
"parameter_provenance": {
  "emergency_input": {"source": "REPAIR", "original_value": null, "category": "SAFE_LITERAL",
                      "reason": "valor fijado por semantic_repair (...)"},
  "trigger_input": {"source": "DEFAULT", "category": "EXTERNAL_FUNCTIONAL_RESOURCE", "original_value": null,
                    "reason": "INT_MOTOR_LATCH exige 'trigger_input' y el parser no lo dio: ...",
                    "resolution": "MAP_EXISTING", "address": "%IX16.0", "state": "LOCKED"},
  "stop_input":    {"source": "DEFAULT", "resolution": "MAP_EXISTING", "address": "%IX16.1", "...": "..."},
  "motor_output":  {"source": "DEFAULT", "resolution": "IO_ALLOCATION", "address": null, "...": "..."}
},
"effective_semantics": {
  "schema_version": 1, "status": "RESOLVED", "intent_id": "INT_MOTOR_LATCH", "origin": "LLM",
  "interpreted_parameters": {"emergency_input": "FALSE"},
  "defaulted_keys": ["trigger_input", "stop_input", "motor_output"],
  "internal_technical_defaults": {"run_latch": "M_RunLatch"},
  "functional_value_defaults": {},
  "errors": []
}
```

`source`: `LLM` / `RULES` / `PARSER` (interpretación), `REPAIR` (semantic_repair) o `DEFAULT`
(semántica efectiva). `status`: `RESOLVED`, `UNRESOLVED` (con `errors`) o `NOT_APPLICABLE` (intent sin
plantilla o programa compuesto).

## 3. Snapshot: `parameter_bindings`

`io_map_snapshot.json` congela, además de `channels` y `bindings`:

```json
"parameter_bindings": {
  "trigger_input": {"functional_name": "I_Start", "name": "I_Start", "address": "%IX16.0",
                    "signal": "DI", "data_type": "BOOL", "state": "LOCKED", "provenance": "DEFAULT"},
  "stop_input":    {"functional_name": "I_Stop", "name": "I_Stop", "address": "%IX16.1", "signal": "DI", "...": "..."},
  "motor_output":  {"functional_name": "Q_Motor_Enable", "name": "Q_Motor_Enable", "address": "%QX8.x", "signal": "DO", "...": "..."}
},
"parameter_provenance": {"...": "..."},
"effective_semantics_status": "RESOLVED"
```

El Oracle resuelve START, STOP y MOTOR_MAIN desde aquí. Nunca lee `program.scl`. `signal` y `data_type`
admiten más adelante roles analógicos (AI/AO; REAL, INT o WORD) para P01–P12 sin rediseñar los
bindings. Para eso solo habrá que ampliar `oracle_runner._KIND_TO_SIGNAL` y el Runtime.

## 4. IR y generador: una sola decisión

- El IR declara exactamente los recursos de `parameters` efectivos (la misma tabla).
- El generador lee `parameters`. Si la semántica efectiva quedó `RESOLVED` y una plantilla de intent
  necesitara un recurso externo ausente, falla con `FUNCTIONAL_RESOURCE_UNRESOLVED`
  (`code_generator.FunctionalResourceUnresolvedError`) en lugar de introducir un default oculto.
- Los defaults literales del generador se conservan para llamadas legacy, pero una prueba de deriva
  exige que coincidan con `INTENT_RESOURCE_TABLE` para los 21 intents.
- Los programas compuestos y PID no cambian.

## 5. Tres medidas semánticas distintas

| Medida | Definición exacta | Dónde |
|---|---|---|
| `semantic_pipeline_success` | La interpretación fue estructuralmente válida y permitió continuar el pipeline (= `stages.semantic_success`, sin cambios). | `trial.json` stages, columna `semantic` y `semantic_pipeline_success` |
| `semantic_benchmark_match` | Todas las comprobaciones semánticas evaluables del Oracle se cumplen: intent aceptado, intent no prohibido, roles requeridos resueltos, requisitos funcionales y parámetros requeridos. Los parámetros se evalúan solo sobre los **interpretados** (un recurso `DEFAULT` nunca cuenta como algo que el comando dijo). `null` si no hay nada evaluable. | `stages.semantic_benchmark_match`, `trial.json.semantic_benchmark`, `evaluation_report.semantic.benchmark_match`, columna `semantic_benchmark` |
| `functional_success` | Todas las expectativas de `test_sequence` del Oracle se cumplen en PLCSIM (sin cambios). | `stages.functional_success` |

## 6. Política del Oracle runner

1. Se evalúan las expectativas semánticas y se registra `semantic_benchmark_match`.
2. Se resuelven los roles desde `parameter_bindings`.
3. Si los roles son resolubles se ejecutan preconditions, test_sequence, functional y safety. **Un
   intent distinto no impide la ejecución** (ya era así; lo que fallaba era la resolución de roles).
4. Si los roles no son resolubles (ausente, ambiguo, tipo o conflicto): REVIEW sin ejecutar el Runtime.

Veredicto global (`final_verdict`): **sin cambios**. La precedencia sigue siendo
INFRA > FAIL por seguridad > REVIEW por roles o evidencia > FAIL funcional > REVIEW por semántica > PASS.
Así, con un intent distinto:

- functional FAIL da **FAIL** (no REVIEW);
- functional PASS y safety PASS dan **REVIEW** con `verdict_reason = ORACLE_SEMANTIC_MISMATCH`. Esto
  coincide con la `final_rule` de los Oracles FROZEN ("PASS requiere semántica, compilación, descarga,
  runtime RUN, funcional y seguridad correctos").

La columna Functional nunca muestra REVIEW por un mismatch de intent: muestra PASS o FAIL.

**Propuesta pendiente de decisión (no implementada).** Antes de FORMAL conviene decidir si el veredicto
global debe seguir integrando la semántica:

- (a) mantener lo actual: REVIEW + `ORACLE_SEMANTIC_MISMATCH`;
- (b) un estado nuevo `PASS_SEMANTIC_MISMATCH`;
- (c) que `final_verdict` dependa solo de functional/safety/infra y que la semántica se informe
  únicamente como `semantic_benchmark_match`.

Cambiar el significado de la métrica principal requiere una decisión explícita del investigador.

## 7. Exportación

`batch_summary.csv` añade **al final** (las columnas anteriores no cambian):
`semantic_benchmark`, `semantic_pipeline_success`, `semantic_benchmark_match`, `functional_success`,
`safety_success`, `infrastructure_status`. Siguen existiendo `semantic`, `functional`, `safety` y
`final_verdict`.

## 8. Recomendación metodológica (artículo)

**Semantic Pipeline Success ≠ Semantic Benchmark Match ≠ Functional Success.**

Ejemplo de DEVELOPMENT (no es un resultado final): D03 V2 ("Quiero encender el motor con Start y que siga
encendido aunque suelte el botón; con Stop se apaga."):

- la interpretación fue válida y el pipeline continuó: Semantic Pipeline Success = sí;
- el intent producido (`INT_MOTOR_LATCH`) no coincide con la taxonomía esperada por el benchmark para
  D03 (`INT_MOTOR_START_STOP`): Semantic Benchmark Match = no;
- el programa generado implementa el comportamiento pedido (Start activa, soltar mantiene, Stop apaga y
  tiene prioridad): Functional Success = sí (medible desde esta corrección).

Informar una sola tasa "semántica" mezclaría la validez del pipeline con el acuerdo taxonómico. Informar
solo el veredicto global ocultaría que el sistema produjo un programa correcto con otra etiqueta de
intención. Se recomienda reportar las tres tasas por separado, con sus denominadores, y el veredicto
global con su regla explícita. Los resultados DEVELOPMENT no se usan como resultados finales.
