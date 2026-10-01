# Diseño experimental v2

> Fuente de verdad ejecutable: [`data/experimental_design.json`](../data/experimental_design.json)
> (módulo `src/trial_experiments/experimental_design.py`). Este documento describe la metodología;
> no contiene resultados. El anteproyecto no se modifica: este diseño lo concreta y lo corrige
> donde el anteproyecto usaba condiciones que ya no se consideran factores (ver §15).

## 1. Propósito y alcance

Evaluar si **una única arquitectura** (lenguaje natural o voz → interpretación semántica con LLM →
asignación de E/S → IR → generación SCL → verificación → compilación en TIA Portal → descarga a
simulador → Oracle) genera programas PLC correctos y seguros a partir de requisitos de
automatización, y cómo varía su desempeño según el dominio, la complejidad, la paráfrasis del
comando y la modalidad de entrada.

No se comparan modos de parser (Reglas / LLM / Híbrido). Esos modos siguen en el software solo
para depuración; en los ensayos, `parser_mode` es metadata técnica y no forma parte ni del
`trial_id` ni del análisis.

## 2. Plataforma experimental

| Elemento | Valor |
|---|---|
| Herramienta de ingeniería | Siemens TIA Portal V18 (TIA Openness) |
| PLC | S7-1500, CPU 1516-3 PN/DP |
| Simulador | S7-PLCSIM Advanced V5 (instancia `TESIS_PLC_SIM`), Runtime API V5 |
| Destino de descarga | `PLCSIM_ADVANCED` exclusivamente (`physical_download = forbidden`) |
| Evaluación | Oracle ejecutado mediante la Runtime API (lectura/escritura de E/S BOOL) |

La plataforma es el S7-1500 con PLCSIM Advanced V5, no el S7-1200. No se descarga nunca a un PLC
físico durante los ensayos.

## 3. Benchmark v2

- 32 casos canónicos: 20 discretos (D01–D20) y 12 de supervisión PID (P01–P12), definidos en
  `data/experiment_cases/canonical_cases.json`, que es la única fuente de verdad.
- Cada caso tiene un comando canónico, requisitos verificables (`command_requirements`) y
  tres variantes lingüísticas: V1 (canónica), V2 (coloquial) y V3 (reformulada). Las 96 variantes
  se validan contra los requisitos (`variant_consistency_report.json`, 96/96 consistentes).
- Cada caso tiene un Oracle `oracle-1.0` aprobado y congelado (FROZEN) por el investigador. Su
  hash SHA-256 se registra en cada ensayo.
- Complejidad por caso: LOW, MEDIUM o HIGH.

## 4. Factores y niveles

| Factor | Niveles | Tipo |
|---|---|---|
| DOMAIN | DISCRETE, PID_SUPERVISOR | entre casos |
| COMPLEXITY | LOW, MEDIUM, HIGH | entre casos (anidado en el caso) |
| VARIANT | V1, V2, V3 | dentro del caso |
| INPUT_MODE | TEXT, VOICE_CLEAN, VOICE_NOISE | dentro del caso |
| CASE | D01–D20, P01–P12 | unidad experimental (efecto aleatorio en el análisis) |

`parser_mode`, el proveedor y el modelo LLM, y el commit de git se registran como metadata. No
son factores.

## 5. Modalidades de entrada

- **TEXT.** El comando de la variante se introduce como texto. Mide interpretación, generación,
  compilación, ejecución y seguridad sin contaminación del ASR.
- **VOICE_CLEAN.** El mismo comando se pronuncia en condiciones acústicas limpias: audio → ASR →
  el mismo pipeline.
- **VOICE_NOISE.** El mismo comando de voz con ruido industrial controlado. Solo cambia la condición
  acústica; el caso, la variante y el contenido funcional se conservan.

Los campos de voz ya están en el modelo de ensayo: `audio_reference`, `asr_transcript`, `wer`,
`noise_profile` y `snr_db`. **El protocolo de ruido (perfil, SNR, locutores y grabación) está
pendiente de definirse** y no forma parte de esta fase.

## 6. Matriz formal

32 casos × 3 variantes × 3 modalidades = **288 FORMAL_TRIALS**, con una repetición por celda y
nueve ensayos por caso. El planificador (`formal_design_matrix`) genera la matriz y la valida
(`validate_formal_matrix`). La matriz no se ejecuta hasta que el software esté congelado (§7).

## 7. Tipos de ensayo, fases y congelación

| trial_kind | experiment_phase | Uso |
|---|---|---|
| DEVELOPMENT_TRIAL | BASELINE | Fotografía del sistema actual (§12) |
| DEVELOPMENT_TRIAL | DEVELOPMENT_VALIDATION | Validación durante el desarrollo (fase por defecto de la GUI) |
| FORMAL_TRIAL | FORMAL | Resultados de la tesis |

- El tipo de ensayo lo decide **la fase de la sesión**, nunca el estado del Oracle (todos están
  FROZEN).
- Los resultados se guardan en directorios separados:
  - `results/development_baseline_v2/`;
  - `results/development_validation_v2/`;
  - `results/experiments/` (formal).
- `formal_statistics_records` excluye de las estadísticas formales todo lo que no sea
  FORMAL_TRIAL de fase FORMAL con benchmark v2.
- **Guard de congelación:** un FORMAL_TRIAL exige `data/software_freeze_manifest.json` en estado
  FROZEN, con hashes coincidentes del catálogo canónico y de los 32 Oracles. El manifiesto no
  existe todavía, así que la GUI bloquea la fase FORMAL.
- El software se congelará después de:
  1. el baseline D;
  2. la corrección de gaps;
  3. la validación D;
  4. la extensión Runtime PID;
  5. la corrección y validación PID;
  6. la suite de regresión completa.

## 8. Identificación y metadatos del ensayo

- **IDs:** `D01_V1_TEXT_001` (formal) y `D01_V1_TEXT_DEV_001` (desarrollo). El ID nunca contiene
  RULES, LLM ni HYBRID.
- **`trial.json` registra:**
  - identidad: trial_id, trial_kind, experiment_phase, case_id, variant, input_mode, domain y
    complexity;
  - benchmark: benchmark_version, canonical_case_hash y variant_hash;
  - Oracle: oracle_id, oracle_version y oracle_hash;
  - contenido: command_text, reference_command_text y la salida semántica;
  - etapas y resultados: estado por etapa (semantic, verification, compile, download, runtime,
    functional, safety), final_status, final_verdict, failure_category e infrastructure_error;
  - latencias: semantic_ms, generation_ms, compile_ms, download_ms, runtime_ms, oracle_ms y
    total_ms;
  - aclaraciones solicitadas;
  - modelo (proveedor y nombre, sin secretos), campos ASR y git_commit;
  - intento y retry_reason.

## 9. Oracles y veredicto

- **Precedencia del veredicto:** INFRASTRUCTURE_ERROR > FAIL (seguridad) > REVIEW > FAIL
  (funcional) > PASS.
- **Severidades:** una invariante CRITICAL es seguridad; MAJOR es funcional.
- **Ejecución:** el Oracle resuelve roles sobre el `io_map_snapshot.json` congelado del ensayo,
  ejecuta una única secuencia de E/S en PLCSIM y restaura las entradas (cleanup verificado).
- **Límite actual:** P01–P12 requieren extender el Runtime (valores analógicos/PID), por eso hoy
  devuelven REVIEW (`REQUIRES_RUNTIME_EXTENSION`) y quedan fuera del baseline.

## 10. Métricas

**Primarias:**
- Semantic Success;
- Compilation Success;
- Functional Success;
- Safety Violation (invariante CRITICAL violada);
- latencia extremo a extremo (`total_ms`).

**Secundarias:**
- WER (voz);
- tasa de aclaración;
- categoría de fallo;
- robustez entre V1, V2 y V3;
- desempeño por complejidad, dominio y modalidad.

Los datos crudos (trial.json, trazas del Oracle y reportes de TIA y PLCSIM) se conservan siempre.
Las tasas se calculan sobre ensayos válidos: un INFRASTRUCTURE_ERROR se informa aparte y nunca
cuenta como FAIL.

## 11. Taxonomía de fallos

| Categoría | Significado |
|---|---|
| SUCCESS | PASS del Oracle |
| SEMANTIC_FAILURE | Interpretación inválida o aclaración sin respuesta |
| IO_ALLOCATION_FAILURE | El IOAllocator no resolvió las E/S |
| IR_FAILURE | Fallo al construir la IR |
| CODEGEN_FAILURE | Fallo o excepción al generar código |
| VERIFICATION_FAILURE | El verificador rechazó el programa |
| COMPILE_FAILURE | TIA no compiló el programa (fallo del sistema) |
| DOWNLOAD_FAILURE | Fallo de descarga a PLCSIM (infraestructura) |
| RUNTIME_FAILURE | La CPU no quedó en RUN o la Runtime API no respondió (infraestructura) |
| FUNCTIONAL_FAILURE | Comportamiento distinto del exigido por el Oracle |
| SAFETY_FAILURE | Violación de una invariante CRITICAL |
| INFRASTRUCTURE_ERROR | TIA, PLCSIM, Runtime o un servicio externo falló |
| REVIEW | No es posible decidir de forma inequívoca |

Un fallo de TIA, PLCSIM o Runtime nunca se cuenta como FAIL funcional. Una excepción en la
interpretación solo se clasifica como infraestructura si delata al servicio externo (red, timeout
o API); cualquier otra excepción cuenta como fallo del sistema.

## 12. Baseline de desarrollo (Fase 4A.1)

**Alcance:** D01–D20 × V1–V3 × TEXT = **60 DEVELOPMENT_TRIALS** (fase BASELINE). Es una fotografía
objetiva del estado actual y la confirmación real de los `SYSTEM_CAPABILITY_GAP` antes de modificar
el generador. **No es un resultado formal.**

**Procedimiento** (`src/trial_experiments/batch_runner.py`):

1. **Preflight.** Aborta ante cualquier duda. Comprueba:
   - el diseño (60 y 288);
   - el benchmark v2 (32 casos, 96/96 variantes);
   - los 32 Oracles FROZEN con hash íntegro;
   - 0 inconsistencias y 0 requisitos ocultos;
   - D01–D20 ejecutables;
   - los mapas presentes;
   - el destino PLCSIM_ADVANCED y `physical_download=forbidden`;
   - que FORMAL no esté permitido;
   - que la GUI esté cerrada;
   - TIA Openness y el proyecto `.ap18`;
   - la instancia PLCSIM conectada, con CPU S7-1500 y red coincidente;
   - que el cliente LLM esté configurado (nunca se registra la clave).
2. **Ejecución secuencial** con el mismo pipeline que el botón EJECUTAR ENSAYO de la GUI. El
   comando es exactamente el texto canónico de la variante; se verifica antes de cada ensayo.
3. **Persistencia.** La cola persistente (`baseline_queue.json`) se guarda después de cada
   ensayo. El batch es reanudable y nunca repite un ensayo completado.
4. **Fallos.** Un FAIL funcional no detiene el batch. Nadie responde las aclaraciones: quedan
   registradas y el ensayo termina en SEMANTIC_FAILURE.
5. **Reintentos.** Solo existe el reintento técnico de INFRASTRUCTURE_ERROR, con
   `--retry-infrastructure --retry-reason "..."` explícitos. Cada intento es un ensayo nuevo:
   nunca se sobrescribe el anterior. No se reintentan fallos semánticos, de compilación,
   funcionales ni de seguridad.
6. **Detención.** El batch se detiene si:
   - hay dos INFRASTRUCTURE_ERROR consecutivos;
   - un ensayo supera el timeout;
   - falla el cleanup de entradas;
   - cambia algún mapa, el catálogo, las variantes, los perfiles, el diseño o un Oracle;
   - se viola el guard de descarga.
7. **Salidas.**
   - En `results/development_baseline_v2/`: `baseline_trials.csv`, `baseline_summary.json`,
     `baseline_summary.md` y `baseline_failures.json`, con desgloses por caso, variante,
     complejidad y familia lógica.
   - En `data/`: `capability_gap_baseline_validation.json`. Los gaps no se corrigen en esta
     fase.

**Comandos:**
- `python -m trial_experiments.batch_runner --preflight`
- `python -m trial_experiments.batch_runner --run [--max N]`
- `python -m trial_experiments.batch_runner --report`

Todos se ejecutan desde `src/`.

## 13. MANUAL_BASELINE (análisis secundario)

Es la comparación del tiempo de programación manual con el tiempo de la arquitectura, en un
subconjunto representativo de tareas por definir.
- Queda **fuera del factorial** (`included_in_factorial = false`).
- No se ejecuta en esta fase.

## 14. Integridad, seguridad y validez

- **Integridad del LLM:** se usa la configuración normal del producto. Sin prompts por caso; sin
  Oracle, salidas esperadas ni pistas; el LLM nunca sabe que se trata de un benchmark.
- **Anti-overfitting:** hay un test que prohíbe literales de caso o variante y condicionales
  `case_id`/`variant` en el core. Otro test verifica que el contexto LLM no contiene
  `related_cases`, Oracles, benchmark ni `case_id`.
- **Aislamiento de E/S:** cada ensayo usa su propio working I/O map y un snapshot congelado. Los
  mapas base no se modifican.
- **Política de recursos** (`src/trial_experiments/resource_policy.py`): en el benchmark v2,
  `profiles.json → allowed_variables` es metadata histórica y nunca funciona como whitelist. Un
  ensayo falla por recursos solo cuando:
  - hay un recurso sin binding en el working map (UNRESOLVED_RESOURCE, que cuenta como
    IO_ALLOCATION_FAILURE);
  - el programa usa un recurso externo inexistente o con otra dirección (GHOST_RESOURCE);
  - el tipo o la dirección del recurso no coinciden con el canal (TYPE_INCOMPATIBLE);
  - se modificó un canal LOCKED (LOCKED_VIOLATION).

  Los tres últimos casos cuentan como IR_FAILURE. La whitelist por perfil solo existe, aislada,
  para el benchmark legacy v1.
- **Seguridad:** hay dos capas.
  1. En la configuración y el preflight, el destino experimental debe ser PLCSIM_ADVANCED.
  2. En tiempo de descarga, el guard vuelve a verificar el destino y exige
     `purpose=experiment`.
- **Amenazas a la validez:**
  - un solo locutor o investigador en la fase de voz;
  - una repetición por celda;
  - la estocasticidad del LLM (se registran el modelo y el commit);
  - los Oracles fueron escritos por el mismo investigador (mitigado con la congelación previa,
    los hashes y la separación entre requisitos y Oracle);
  - la validez de la simulación frente al hardware real.

## 15. Hipótesis propuestas y condiciones legacy

Las hipótesis son **propuestas y aún no se han contrastado**. No hay resultados.

- **H1 — Desempeño general:** la arquitectura alcanza un Functional Success sustancialmente
  mayor que cero y sin violaciones de seguridad en los ensayos formales.
- **H2 — Complejidad:** el Functional Success disminuye al pasar de LOW a MEDIUM y a HIGH.
- **H3 — Robustez a la paráfrasis:** no hay una diferencia relevante de Functional Success entre
  V1, V2 y V3 del mismo caso.
- **H4 — Modalidad:** VOICE_CLEAN no reduce significativamente el éxito respecto a TEXT.
- **H5 — Ruido:** VOICE_NOISE reduce el éxito respecto a VOICE_CLEAN, y la caída se asocia
  al WER.
- **H6 — Dominio:** el desempeño difiere entre DISCRETE y PID_SUPERVISOR.

**Análisis previsto.** Proporciones con intervalos de confianza (Wilson); modelos logísticos de
efectos mixtos con el caso como efecto aleatorio y DOMAIN, COMPLEXITY, VARIANT e INPUT_MODE como
efectos fijos. Para las comparaciones pareadas dentro del caso: pruebas de McNemar o Cochran's Q.
Latencias con medianas y rangos intercuartílicos.

**Condiciones legacy (DEPRECATED).** Las condiciones C0–C4 del diseño anterior quedan
**obsoletas** como factores experimentales:
- C0: manual;
- C1: LLM directo;
- C2: texto estructurado con LLM;
- C3: voz;
- C4: voz con ruido.

Su intención se conserva así: C0 → MANUAL_BASELINE; C1/C2 → TEXT; C3 → VOICE_CLEAN;
C4 → VOICE_NOISE. La diferencia entre Reglas, LLM e Híbrido deja de ser un factor. El registro
legacy (`experiments/`) sigue existiendo en paralelo por compatibilidad, con la modalidad como
etiqueta de condición.
