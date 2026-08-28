# 20 Modo Experimentacion

## Proposito

Segundo modo de trabajo dentro de la misma GUI (`Modo de trabajo: Normal / Experimentacion`) para correr ensayos controlados sobre el banco discreto D01-D20 y capturar automaticamente evidencia por ensayo mas un log maestro CSV/JSON. Reutiliza integramente `MAPA_SIMULACION_COMPLETO`, `MAPA_BANCO_FISICO` y los perfiles D01-D20 (`18_mapa_maestro_plc.md`, `19_perfiles_experimentales_d01_d20.md`) sin duplicarlos.

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

El usuario no elige un perfil por separado en Modo Experimentacion: selecciona un **Caso experimental** (D01-D20) y la GUI resuelve automaticamente el `profile_id` asociado (`case_id == profile_id` en el esquema actual de `data/plc_maps/profiles.json`), fija `self.active_profile_id` y por tanto filtra `allowed_variables` igual que lo haria el selector manual (`_load_runtime_configuration`, sin cambios). El selector "Perfil de prueba" del panel izquierdo se deshabilita mientras el modo de trabajo es Experimentacion (se re-etiqueta como "Perfil de prueba (automatico - Modo Experimentacion)") y su seleccion previa se restaura al volver a Modo Normal. La infraestructura de perfiles (`src/plc_maps/profiles.py`, `apply_profile_filter`, `profile_readiness_summary`) no se duplica ni se modifica — solo se reutiliza desde un punto de entrada distinto.

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

1. Seleccionar Grupo (solo Discreto D01-D20 disponible; PID muestra aviso y revierte), Caso experimental, Variante (con su "Comando V1/V2/V3" de referencia), Condicion, Participante (`speaker_id` anonimo, ej. `P01`), Ruido, Entorno.
2. El estado muestra "Proximo ensayo", el perfil asociado al caso, variables mapa/habilitadas y `simulation_ready`/`hardware_ready` (`plc_maps.profiles.profile_readiness_summary`, sin cambios). Si Entorno=Hardware y `hardware_ready=False`, se bloquea solo el boton `[Iniciar ensayo]`, nunca la seleccion del caso.
3. `[Iniciar ensayo]` crea `trial_id` (`TRIAL_000001`, ...), fuerza el `parser_mode` de la condicion en el selector existente, y guarda un `metadata.json` inicial. No reemplaza los botones "Procesar comando"/"Generar paquete PLC" — el usuario los sigue usando normalmente (necesario para C3/C4, que requieren grabar voz de verdad; el boton `[Usar este comando]` puede prellenar el cuadro de texto con la variante seleccionada como referencia).
4. Al procesar el comando exitosamente, se captura `command_text`/`transcript`/`semantic_output` en el ensayo activo. Si el parser falla o produce `INT_UNKNOWN`, se registra igual (clasificado `E2`) y el ensayo se cierra sin bloquear la GUI (seccion 24 del pedido).
5. Al generar el paquete (tras la confirmacion humana existente), se captura `compile_result`/errores/advertencias/`package_dir`, y aparece la seccion "Resultado del ensayo" (Resultado fisico, Violacion de seguridad, Tipo de error E1-E10, Observaciones).
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
