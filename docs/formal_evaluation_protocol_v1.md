# Protocolo de evaluación FORMAL v1

Estado congelado del sistema bajo prueba para los ensayos FORMAL de la tesis. Fuente de verdad del congelamiento:
`data/software_freeze_manifest.json` (`freeze_id = FORMAL_V1`).

## 1. Identificación

| Elemento | Valor |
|---|---|
| Rama canónica | `main` |
| Commit del software congelado (`git_commit` del manifiesto) | `8b7efbc01bbdf9c5023433f7f2a0063218ebb72c` |
| Tag | `formal-v1.0` (apunta al commit del freeze, que solo añade el manifiesto y esta documentación, fuera del alcance congelado) |
| Benchmark | v3 (`data/experiment_cases/canonical_cases.json`, SHA-256 normalizado `111d7fe3…0aad`) |
| Oracles | 32 FROZEN, validación técnica PASSED, aprobación humana formal APPROVED (Henry Ochoa, 2026-10-12T15:13:10) |
| Prompt LLM | `prompts/llm_semantic_parser_prompt.txt` (`8ed57cff…b2f1`) |
| Modelo | `gpt-5.6-terra` (OpenAI), temperatura 0, salida estructurada; ASR `gpt-4o-mini-transcribe` (sin semilla: la API usada no la fija) |
| TIA MASTER | `S71500_MASTER`, snapshot `M261006102233.zap18` (`4b2e5446…64fd`), CPU 1516-3 PN/DP 6ES7 516-3AN01-0AB0 V2.6, TIA V18, X1 192.168.0.1, 0 bloques, **FORMAL_READY** |
| Runtime | PLCSIM Advanced V5, instancia `TESIS_PLC_SIM`, PN/IE por "Siemens PLCSIM Virtual Ethernet Adapter", interfaz "1 X1", `io_settle_ms` 500 |
| Alcance congelado | 337 archivos versionados (código, prompt, catálogo, esquema, base de conocimiento, configuración versionada, bridges, benchmark, Oracles, mapas), con su SHA-256 en el manifiesto |

Limitación conocida no bloqueante: en D15, el contrato de `INT_MANUAL_AUTO_MODE` puede asignar entradas opcionales
históricas (`manual_input`, `trigger_input`, `stop_input`) que la lógica generada no usa (KNOWN_NON_BLOCKING_LIMITATION).

## 2. Diseño

- 32 casos (D01-D20 discretos, P01-P12 supervisión PID) × 3 variantes (V1, V2, V3) × 3 modalidades (TEXT,
  VOICE_CLEAN, VOICE_NOISE) = **288 celdas**; **un ensayo FORMAL por celda** (`repetitions_per_cell = 1`).
- Los ensayos DEVELOPMENT (baseline, validación, pilotos) quedan **excluidos** de las estadísticas formales
  (`experimental_design.formal_statistics_records` solo admite FORMAL_TRIAL del benchmark vigente). Los FORMAL se
  guardan en `results/experiments/`.
- Mapa de cada ensayo: selección determinista por capacidad (`config/experiment_maps.json`); D05 y P07 usan el mapa
  de simulación (SAFETY_TRIP simulado, solo PLCSIM), el resto el banco físico. Queda congelado en cada ensayo.
- `parser_mode = llm` con `allow_rule_fallback = true` es parte del sistema bajo prueba (congelado tal cual).

## 3. Reglas durante FORMAL

1. **No se modifica el software** mientras dure la evaluación. Todo punto de entrada FORMAL valida el entorno contra el
   manifiesto (`software_freeze.validate_freeze` dentro de `check_formal_trial_allowed`): precheck de entorno **antes
   del LLM**, precheck de evaluación **antes de TIA**, guardas del lote TEXT y preflight. Cualquier diferencia (código,
   prompt, Oracle, benchmark, mapa, configuración de ejecución, MASTER, versión de paquetes) **aborta** el ensayo.
   Un cambio necesario implica un nuevo freeze (nuevo manifiesto y nuevo tag), nunca un parche en caliente.
2. **PASS, FAIL y REVIEW son resultados válidos** del sistema bajo prueba (incluidas aclaraciones sin respuesta y
   sobrescrituras del arnés detectadas). Un FAIL o un REVIEW **nunca se reintenta** para obtener PASS.
3. **INFRASTRUCTURE_ERROR no es un resultado del DUT** (TIA, PLCSIM, memoria, archive no verificable): no cuenta en las
   métricas. Solo admite **reintento técnico explícito del mismo ensayo** (`attempt_002`, …) con motivo registrado;
   los intentos anteriores se conservan.
4. **Lote TEXT**: ante INFRASTRUCTURE_ERROR, ensayo interrumpido o precheck bloqueado, el lote se **pausa** (nunca
   continúa solo); se diagnostica, se reintenta explícitamente el mismo ensayo y se reanuda. Un FAIL funcional no pausa:
   es un dato y el lote continúa. "Pausar después del ensayo actual" nunca interrumpe TIA.
5. **Evidencia por ensayo** (inmutable): `trial.json`, comando, `semantic_output.json`, `program.scl`, `variables.json`,
   `io_map_snapshot.json`, `process_variable_bindings.json` (PID), `integrity_manifest.json`, por intento
   `compile/download/runtime_report.json`, `evaluation_report.json` (con `stage_summary` y `experiment_map`),
   `oracle_trace.json` y el `.zap18` verificado por hash, con todos los tiempos.
6. **Voz**: VOICE_CLEAN y VOICE_NOISE se ejecutan ensayo a ensayo (EJECUTAR ENSAYO COMPLETO, fase FORMAL) con el
   protocolo de voz congelado; sin corrección humana del ASR; VOICE_NOISE requiere el audio VOICE_CLEAN pareado.

## 4. Respaldo de resultados

- Tras cada lote (y al menos al final de cada sesión): copia de `results/experiments/` y `results/batches/` a un medio
  externo, más un archivo con el SHA-256 de cada `.zap18` y `trial.json` copiado.
- Los resultados no se versionan en git (`results/` está ignorado); el commit/tag `formal-v1.0` identifica el software
  que los produjo y cada ensayo registra `benchmark_version`, hashes de caso/variante/Oracle y el commit.
- Nunca se borran ensayos FORMAL, tampoco los INFRASTRUCTURE_ERROR (quedan como intentos registrados).

## 5. Verificación del congelamiento

```
.venv\Scripts\python.exe scripts\formal_freeze.py validate
```

Salida `"ok": true` = el entorno coincide con el manifiesto. Debe ejecutarse antes de cada sesión FORMAL.
