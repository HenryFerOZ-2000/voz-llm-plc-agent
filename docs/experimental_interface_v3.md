# Interfaz experimental del benchmark v3 (FORMAL)

Este documento fija las convenciones de la interfaz de prueba (test harness) con la que los Oracles congelados
estimulan y observan el programa generado. **No forman parte de los comandos en lenguaje natural**: los comandos dicen
*qué* debe hacer el sistema; esta interfaz dice *cómo lo mide* el evaluador. Aplica a los 32 casos del benchmark v3
(`data/experiment_cases/canonical_cases.json`, `benchmark_version = 3`). El benchmark v2 queda como histórico
DEVELOPMENT en `data/experiment_benchmark/versions/benchmark_v2/`.

## 1. Polaridad de las señales

- **Todas las entradas digitales son activas en ON** (TRUE = accionado / condición presente), **incluido Stop**.
  Un pulsador de paro se modela como contacto normalmente abierto: `STOP = TRUE` significa "Stop pulsado".
- Un *pulsador* se modela como un pulso de 300 ms (C-PULSE); una *orden* o *selección* se modela como una señal
  mantenida mientras dura (C-D07-HELD, C-D12-REQ, C-D15-MODES).
- Las salidas observadas son activas en ON (TRUE = energizada / indicador encendido).

## 2. Modo de operación Manual / Automático

- Convención experimental global: **un único selector lógico** `MODE_AUTO`.
  - `MODE_AUTO = TRUE` → modo **Automático**.
  - `MODE_AUTO = FALSE` → modo **Manual** (Manual ≡ "no Automático").
- El modo lo **selecciona el operador** (lo fija el arnés de prueba). El programa no debe cambiarlo por su cuenta: si
  reescribe una variable de modo que el Oracle controla como entrada, el evaluador lo registra como
  `PROGRAM_OVERWRITES_HARNESS_INPUT` (Functional FAIL), nunca como fallo de infraestructura.
- Casos afectados: D15 (rol `MODE_AUTO`), P01 (`AUTO_MODE` como salida que sigue a la selección), P06, P07, P08 y P12
  (`AUTO_MODE` como entrada del arnés).
- Esta convención **no altera** el Modo Normal del producto ni el mapa físico del banco (que conserva
  `I_Mode_Auto` e `I_Mode_Manual` como entradas independientes).

## 3. Señales externas proporcionadas por el arnés

Señales que el Oracle fuerza como **condiciones de entrada**; el programa las consume, no las genera:

| Caso | Rol | Significado | Convención |
|---|---|---|---|
| D05 | `SAFETY_TRIP` | condición de emergencia (activa = TRUE) | C-D05-TRIP |
| D06 | `SAFETY_OK` | condición de seguridad cumplida (TRUE = cumplida) | — |
| D13 | `ALARM_ACTIVE` | alarma activa del sistema | C-D13-ALARM |
| D19 | `RUN_STATE`, `FAULT_ACTIVE` | señales de marcha y de falla del sistema | C-D19-INPUTS |
| P06, P07, P08, P12 | `AUTO_MODE` | selector de modo (sección 2) | C-P06, C-P07-PRE |
| P07 | `SAFETY_TRIP` | condición de emergencia (activa = TRUE) | C-P07-TRIP |

Nótese la polaridad opuesta entre `SAFETY_OK` (D06, TRUE = condición segura) y `SAFETY_TRIP` (D05/P07, TRUE = disparo).

## 4. Emergencia simulada (`SAFETY_TRIP`)

- En D05 y P07 la emergencia es una **señal lógica de simulación**. **No representa hardware físico**: el paro de
  emergencia real del banco está cableado fuera del PLC y **no** existe `I_Emergency` en `mapa_banco_fisico_base.json`
  (que no se modifica y sigue byte-idéntico).
- La señal la aporta el **mapa experimental de simulación** `data/plc_maps/mapa_experimental_simulacion.json`
  (`metadata.simulation_only = true`, `metadata.harness_signals = {"SAFETY_TRIP": "I_Emergency"}`): canal LOCKED
  `I_Emergency` en `%IX20.2`, descrito como "SAFETY_TRIP SIMULADO: señal lógica del test harness". Solo se usa con
  PLCSIM; nunca se descarga a hardware.
- **Selección automática por caso** (`config/experiment_maps.json`, `trial_experiments.experiment_maps`): el Oracle de
  D05/P07 tiene un rol IO cuyos `semantic_paths` incluyen `emergency_input`/`safety_trip*`; esa es una señal
  RESTRINGIDA que solo cubre un mapa que la declare en `harness_signals`. El banco no la declara, así que esos casos
  se ejecutan sobre el mapa de simulación; el resto sigue en el banco físico.
- En el banco físico la emergencia nunca se convierte en una entrada: `semantic_repair`/semántica efectiva la dejan en
  el literal seguro `FALSE` (sin tag fantasma). En el mapa de simulación `INT_EMERGENCY_PRIORITY` conserva
  `emergency_input = I_Emergency`, el Oracle la escribe en PLCSIM y el cleanup la devuelve a `FALSE`.

## 5. Variables de proceso (`PROCESS_VARIABLE`, P01-P12)

- Los casos PID no usan E/S analógicas (AI/AO). El Oracle escribe y lee **variables internas** del programa generado:
  estáticas del DB de instancia `DB_PLC_PRG` (`Level_PV`, `Level_SP` REAL en % de ingeniería; `Auto_Mode`,
  `PID_Enable`, `High_Level_Alarm`, `Low_Level_Alarm`, `Sensor_Fault`, `Safe_Stop` BOOL).
- Contrato de nombres: `functional_requirements.PID_PROCESS_VARIABLES`. Por ensayo se congelan en
  `process_variable_bindings.json` (derivado de `variables.json` + contrato). El nombre Runtime se resuelve en PLCSIM
  contra `TagInfos` (nunca se asume su formato).
- Solo los roles `INPUT` con binding `PROCESS_VARIABLE` se escriben, solo en PLCSIM, solo durante el Oracle, con
  readback (REAL ±0.001) y restauración al valor del cleanup del Oracle.
- Sin escalado RAW: los valores son unidades de ingeniería (%).

## 6. Mapa físico y mapas de simulación

| Mapa | Uso | Estado |
|---|---|---|
| `mapa_banco_fisico_base.json` | banco físico real (8 DI, 8 DO, 4 AI, 4 AO) | **intacto** (byte-idéntico); sin `I_Emergency` |
| `mapa_experimental_simulacion.json` | mapa FORMAL/EXPERIMENTAL de simulación (16 DI `%IX20.0-21.7`, 16 DO `%QX20.0-21.7`, rango disjunto del banco) | nuevo; `simulation_only`; aporta `SAFETY_TRIP` |
| `mapa_simulacion_completo.json` | simulación con recursos ampliados (Modo Normal) | intacto |
| `mapa_pid_simulacion.json` | recursos físicos de simulación para P01-P12 | intacto |
| `mapa_pid_banco_fisico.json` | banco PID físico | vacío a propósito (no confirmado) |

**Selección del mapa base de cada ensayo** (determinista, por capacidad, nunca por `case_id`): se recorren los mapas
de `config/experiment_maps.json` por prioridad (banco físico primero) y se elige el primero que cubre las necesidades
derivadas de los roles IO del Oracle congelado (entradas/salidas digitales y señales restringidas). La base
experimental del banco libera todo canal ASSIGNED (solo `I_Start`/`I_Stop` son LOCKED), por lo que ofrece 8 DI y 8 DO.
La selección queda congelada en el ensayo (`trial.json → experiment_map`: `map_id`, `map_hash` canónico, `source`,
`simulation_only`, motivo) y se copia en `evaluation_report.json`. Resultado vigente: D05 y P07 → simulación; los
otros 30 casos → banco físico.

**D14 (selección de velocidad):** 3 entradas de selección + 3 salidas de velocidad caben en el banco (8 DI / 8 DO), así
que la selección por capacidad lo mantiene en el banco físico; el mapa de simulación tiene recursos de sobra si el
banco no alcanzara. La capacidad de generación es el intent `INT_SPEED_SELECTION` (salida solo de la velocidad
seleccionada; con dos selecciones simultáneas ninguna se activa → invariante "como máximo una").

## 7. Familias funcionales

D03, D04 y D11 implementan la misma capacidad (memoria de marcha Start/Stop) con distinta redacción; se conservan los
tres casos y se tratan como una **familia funcional** en el análisis secundario (para no sobreponderar esa capacidad
en métricas agregadas). En v3, D03 acepta semánticamente `INT_MOTOR_START_STOP` e `INT_MOTOR_LATCH`, igual que D04/D11.
