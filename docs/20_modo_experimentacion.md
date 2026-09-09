# 20 Modo Experimentacion

## Proposito

Segundo modo de trabajo dentro de la misma GUI (`Modo de trabajo: Normal / Experimentacion`) para correr ensayos controlados sobre el banco discreto D01-D20 y capturar automaticamente evidencia por ensayo mas un log maestro CSV/JSON. Reutiliza integramente `MAPA_SIMULACION_COMPLETO`, `MAPA_BANCO_FISICO` y los perfiles D01-D20 (`18_mapa_maestro_plc.md`, `19_perfiles_experimentales_d01_d20.md`) sin duplicarlos.

## Modo Normal vs Modo Experimentacion

Los dos modos de trabajo tienen proposito distinto y **nunca comparten un perfil Dxx activo por accidente**:

- **Modo Normal** es el uso funcional/oficial de la arquitectura: programacion libre dentro de las capacidades soportadas (parser reglas/LLM/hibrido, intenciones del catalogo, IEC 61131-3, `SiemensSCLAdapter`, reglas de seguridad). Usa siempre `GENERAL / SIN FILTRO` — el mapa PLC activo completo, sin ningun filtro de perfil — y no depende de D01-D20 para nada. No limita artificialmente lo que se puede programar; solo esta acotado por lo que la arquitectura realmente soporta (intenciones implementadas, variables que existen en el mapa, reglas de seguridad).
- **Modo Experimentacion** es un entorno controlado para evaluar sistematicamente la arquitectura: D01-D20 (y en el futuro P01-P12), cada uno con un perfil que restringe que recursos fisicos/externos estan autorizados para ese caso especifico.

`self.active_profile_id` (el "contexto" activo) es siempre automatico, nunca una eleccion manual:

| Cambio de modo | `active_profile_id` resultante |
|---|---|
| Normal (por defecto al abrir la app) | `None` (GENERAL) |
| Normal -> Experimentacion + caso Dxx | `profile_id` del caso seleccionado |
| Cambiar de caso dentro de Experimentacion | se actualiza al `profile_id` del nuevo caso |
| Experimentacion -> Normal | vuelve a `None` (GENERAL) |

El selector "Perfil de prueba" del panel izquierdo queda **permanentemente deshabilitado** (`state="disabled"` desde su construccion) — nadie elige un perfil a mano nunca, ni siquiera en Modo Normal. Su etiqueta cambia segun el modo ("Contexto (Modo Normal)" / "Perfil de prueba (automatico - Modo Experimentacion)") pero es solo informativo.

## Regla de recursos externos vs internos

Esta regla ya estaba implementada en la arquitectura (clasificacion por prefijo en `ir_builder.EXTERNAL_PREFIXES`/`INTERNAL_PREFIXES`, reutilizada por `plc_maps.apply_profile_filter` y `semantic_validator.validate_semantic_output`) y esta tarea la documenta y la expone claramente en la GUI:

> **Los perfiles experimentales restringen unicamente los recursos externos autorizados (`I_`/`Q_`: sensores, pulsadores, salidas fisicas, VFD, senales analogicas reales). Los recursos internos necesarios para implementar la logica (`M_`/`T_`/`C_`/`R_`/`F_`: temporizadores TON/TOF/TP, contadores CTU/CTD, flancos R_TRIG/F_TRIG, memorias, latches, estados) pueden ser generados automaticamente por la arquitectura sin importar el perfil activo.**

`apply_profile_filter(io_map, profile)` nunca filtra variables internas. `semantic_validator.py` excluye explicitamente los tags con `INTERNAL_PREFIXES` antes de calcular `unauthorized_tags` — un recurso interno nuevo jamas cuenta como incompatibilidad de perfil, solo un recurso externo no autorizado lo hace.

## Incompatibilidad experimental vs aclaracion semantica

Antes, cualquier interpretacion invalida (`semantic_validation.is_valid=False`) mostraba el mismo dialogo generico "Aclaracion requerida" con el `clarification_question` que el LLM hubiera generado — incluso cuando la causa real era que el comando pedia recursos fisicos (p. ej. `I_Stop`, `Q_Motor_Enable`) que el perfil D01 no autoriza, lo que producia mensajes confusos del estilo "¿Puede autorizarse un mapa I/O que incluya...?" sugiriendo ampliar el hardware del caso.

`process_command()` ahora distingue la causa usando `semantic_validation.unauthorized_tags` (que ya viene filtrado a solo recursos externos):

- **`unauthorized_tags` no vacio + Modo Experimentacion** -> dialogo "Incompatibilidad experimental": indica el caso activo, los recursos fisicos autorizados por el perfil y los solicitados por el comando, y ofrece reformular el comando, elegir otro caso o usar Modo Normal. **Nunca** ofrece ampliar el mapa o el perfil automaticamente. Si hay un ensayo activo, se registra como fallo con `error_type="E3"` (Variable) en vez de `"E2"` (Semantico), preservando toda la evidencia (`_capture_trial_parse_failure`, sin cambios en su logica de guardado).
- **`unauthorized_tags` no vacio + Modo Normal** -> dialogo "Recurso fisico no encontrado": indica la variable solicitada y el mapa activo, y ofrece agregar la variable, elegir otro mapa o cancelar — aqui si tiene sentido ofrecer modificar el mapa porque Modo Normal no esta sujeto a un protocolo Dxx.
- **`unauthorized_tags` vacio pero `requires_clarification=True`** -> se mantiene exactamente el dialogo "Aclaracion requerida" de siempre, para ambiguedades reales del lenguaje (p. ej. "enciende la bomba cuando sea necesario").

En el panel de Modo Experimentacion, mientras hay una interpretacion pendiente (`self.pending_semantic_output`) se muestra una linea "Compatibilidad: ✓ Compatible" o "Compatibilidad: ⚠ Recursos no autorizados: ..." (`plc_maps.check_case_compatibility`, reutiliza `unauthorized_tags` ya calculado — no vuelve a invocar el LLM). Se limpia (`pending_semantic_output = None`) al cambiar de caso, para no mostrar una compatibilidad calculada contra un caso distinto.

## Aclaracion importante: dos taxonomias de condiciones distintas

El proyecto ya tenia un protocolo de evaluacion documentado (`14_protocolo_evaluacion.md`) con 6 condiciones (`C0_MANUAL`...`C5_HYBRID_VOICE_NOISE`) usadas por `src/evaluation_runner.py`, un harness batch independiente que corre todo el banco de pruebas por script y que **no fue modificado** por esta funcionalidad. El Modo Experimentacion de la GUI usa una taxonomia propia de 4 condiciones (C0 eliminado a proposito):

| Condicion GUI | parser_mode | Requiere voz | noise_level |
|---|---|---|---|
| C1 - LLM directo desde texto | `llm` | No | siempre `none` |
| C2 - Texto estructurado + LLM + verificacion | `hybrid` | No | siempre `none` |
| C3 - Voz + ASR + interpretacion + LLM + verificacion | `hybrid` | Si | `none` por defecto, editable |
| C4 - Voz con ruido industrial simulado | `hybrid` | Si | obligatorio `medium`/`high` |

No se implementa inyeccion real de ruido acustico: `noise_level` es un campo de metadata que el usuario configura manualmente antes de grabar (el proyecto ya documentaba en `12_integracion_voz.md` que no procesa ruido de forma avanzada).

## Compatibilidad con Modo Normal

Todo el enganche es aditivo: dos bloques `if self.active_trial:` en `process_command()` y `generate_package()`, envueltos en su propio try/except. En Modo Normal `self.active_trial` siempre es `None`, asi que el comportamiento es identico al actual. La confirmacion humana existente antes de generar (`askyesnocancel`) no se salta ni se duplica.

## "Caso experimental" reemplaza a "Perfil de prueba" como selector principal

El usuario no elige un perfil por separado en Modo Experimentacion: selecciona un **Caso experimental** (D01-D20) y la GUI resuelve automaticamente el `profile_id` asociado (`case_id == profile_id` en el esquema actual de `data/plc_maps/profiles.json`), fija `self.active_profile_id` y por tanto filtra `allowed_variables` igual que lo haria el selector manual (`_load_runtime_configuration`, sin cambios). El selector "Perfil de prueba" del panel izquierdo esta permanentemente deshabilitado (ver seccion "Modo Normal vs Modo Experimentacion" mas arriba); solo cambia de etiqueta segun el modo. La infraestructura de perfiles (`src/plc_maps/profiles.py`, `apply_profile_filter`, `profile_readiness_summary`, `check_case_compatibility`) no se duplica ni se modifica — solo se reutiliza desde un punto de entrada distinto.

Debajo del selector de caso, la GUI muestra como informacion tecnica secundaria: "Perfil asociado: `<profile_id>`", "Variables mapa: X   Variables habilitadas: Y", y el estado `Simulation:`/`Hardware:` (`profile_readiness_summary`).

## Variantes linguisticas por caso

Las variantes V1-V3 (minimo) por caso se leen de `data/plc_maps/experiment_variants.json` (`src/trial_experiments/variants.py`), no de `tests/test_cases.json` ni hardcodeadas en el widget. Cada entrada es `{"variant": "V1", "command": "..."}`. Al cambiar de caso o variante, la GUI muestra "Comando V1: \"<texto>\"" y un boton `[Usar este comando]` que copia el texto al cuadro de comando (referencia editable, no un envio automatico). Agregar V4/V5, editar V1-V3 o cargar variantes nuevas no requiere cambios de codigo en la GUI: basta con editar el JSON.

## Formato de archivos

```text
experiments/
  .trial_counter.json          # contador persistente, nunca reutiliza un trial_id
  automated/<case_id>/<trial_id>/
    command.txt                # solo si hay contenido
    transcript.txt             # solo si hubo voz
    metadata.json               # evidencia tecnica (nunca se sobrescribe con una generacion posterior)
    observations.json           # campos manuales, editable sin tocar metadata.json
  experimental_results.csv
  experimental_results.json
```

`metadata.json` no copia los artefactos grandes que `generate_project_package` ya escribe en `generated_code/SIEMENS/active/<run>/` (SCL, variables.json, verification.json, tia_compile_report.json) — guarda un campo `package_dir` que apunta ahi.

`experiments/` esta en `.gitignore` (estado local generado, mismo criterio que `generated_code/*/active`).

## Etiqueta experimental legible

Cada ensayo tiene, ademas del `trial_id` interno unico (`TRIAL_000123`), una etiqueta legible con formato `C{condicion}_{caso}_{variante}_R{repeticion}` (ej. `C3_D05_V2_R02`). La repeticion **no se guarda en un contador separado**: se calcula consultando `experimental_results.json` (`compute_next_repetition`, `src/trial_experiments/trial_store.py`) y contando cuantos ensayos ya guardados coinciden en `condicion+caso+variante` — un ensayo iniciado y abandonado sin llegar a `record_trial_summary()` no consume un numero de repeticion. Cambiar de variante o condicion arranca su propio conteo en R01, sin afectar los demas. Antes de iniciar el ensayo, la GUI muestra en todo momento "Proximo ensayo: C{...}_R{...}" (funcion de solo lectura, se puede llamar repetidamente sin efecto secundario), recalculado cada vez que cambia caso/condicion/variante. Los campos `trial_id`, `experiment_label`, `condition`, `case_id`, `variant` y `repetition` se guardan en `metadata.json`, `experimental_results.csv` y `experimental_results.json`.

## Flujo de un ensayo

1. Seleccionar Grupo (solo Discreto D01-D20 disponible; PID muestra aviso y revierte), Caso experimental, Variante (con su "Comando de referencia"), Condicion, Participante (`speaker_id` anonimo, ej. `P01`), Ruido, Entorno.
2. El estado muestra "Proximo ensayo", el perfil asociado al caso, compatibilidad (si ya hay una interpretacion pendiente), variables habilitadas y `simulation_ready`/`hardware_ready`. Si Entorno=Hardware y `hardware_ready=False`, se bloquea solo el boton `[EJECUTAR ENSAYO]`, nunca la seleccion del caso.
3. `[EJECUTAR ENSAYO]` (`run_experiment_trial()`) arma el ensayo (`trial_id`, `metadata.json` inicial, `parser_mode` de la condicion) y corre automaticamente el mismo pipeline que `[EJECUTAR COMANDO]` en Modo Normal (`execute_full_pipeline()`: `process_command()` -> `generate_package()` -> `validate_latest_package_in_tia()`) — el usuario ya no pulsa por separado "Procesar comando"/"Generar paquete PLC"/"Importar y compilar" durante un ensayo (esos botones siguen existiendo en "Herramientas avanzadas" para depuracion). Para C3/C4 se graba voz primero con `[Grabar comando]`/`[Detener y transcribir]` (que ya transcribe automaticamente al cuadro de comando) antes de pulsar `[EJECUTAR ENSAYO]`.
4. Al procesar el comando, se captura `command_text`/`transcript`/`semantic_output` en el ensayo activo. Si el parser falla, produce `INT_UNKNOWN`, o el comando pide recursos fisicos no autorizados por el caso (incompatibilidad experimental, ver seccion correspondiente mas arriba), se registra igual (`E2` para ambiguedad semantica, `E3` para incompatibilidad de recursos) y el ensayo se cierra sin bloquear la GUI.
5. Al generar el paquete (tras la confirmacion humana existente) y al importar/compilar en TIA (segunda confirmacion, tambien existente), se captura `compile_result`/errores/advertencias/`package_dir`/`tia_compile_status`, y aparece la seccion "Resultado del ensayo" (Resultado fisico, Violacion de seguridad, Tipo de error E1-E10, Observaciones).
6. `[Guardar resultado]` cierra el ensayo (`state=COMPLETED`), calcula `total_time`, y actualiza el log maestro.

## Log maestro

`record_trial_summary()` hace upsert por `trial_id` (nunca duplica filas): si se repite D03, se crea un `trial_id` nuevo (nunca se reutiliza), pero si se re-edita el resultado manual de un ensayo ya completado, su fila existente se actualiza en el mismo lugar. `git_commit` se captura con `git rev-parse HEAD` (timeout 10s, nunca lanza excepcion; `None` fuera de un repo git).

## Pestana "Historial experimental" y exportacion

Nueva pestana de resultados (Trial/Caso/Condicion/Compila/Ejecucion/Tiempo/Error) con doble clic para ver el detalle completo de un ensayo. Boton `[Exportar resultados]`: CSV o JSON segun la extension elegida en el dialogo. No se agrego XLSX (no hay `openpyxl`/`pandas` en `requirements.txt`; agregarlo violaria la restriccion de no sumar dependencias innecesarias). Sin analisis estadistico dentro de la app.

## Limitaciones conocidas

- D14 (seleccion de velocidad) y D19 (piloto detenido) no tienen intencion implementada — el perfil y su readiness se muestran igual, pero un comando real cae en `INT_UNKNOWN` y el ensayo se registra como fallo E2 (comportamiento esperado, documentado en `19_perfiles_experimentales_d01_d20.md`).
- D02/D05/D11 mantienen las ambiguedades ya conocidas del parser por reglas.
- No hay reasignacion automatica de entradas fisicas compartidas entre pruebas (explicitamente fuera de alcance).
- PID/P01-P12: el campo `experiment_family` acepta `"PID"` desde ya, pero no existe ningun caso/perfil/logica PID todavia.
