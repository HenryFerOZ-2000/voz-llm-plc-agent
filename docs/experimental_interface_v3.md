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
  (que no se modifica).
- Interfaz de simulación disponible: `data/plc_maps/mapa_simulacion_completo.json` define `I_Emergency` en `%IX0.2`,
  utilizable como fuente de `SAFETY_TRIP` en simulación (roles `emergency_input` / `safety_trip_input`).
- **Pendiente de cableado (no implementado):** el flujo experimental actual parte siempre del mapa del banco físico
  (`trial_io_map.create_working_map` con `mapa_banco_fisico_base.json`), donde no hay entrada de disparo ni DI libre.
  Para evaluar D05/P07 en FORMAL hace falta seleccionar un mapa de simulación por caso o fase; mientras tanto el rol
  `SAFETY_TRIP` no se resuelve (REVIEW `ORACLE_ROLE_NOT_FOUND`).
- Riesgo a verificar en D05: `semantic_repair` conserva el requisito de emergencia cuando el intent es
  `INT_EMERGENCY_PRIORITY`; con el mapa físico la generación puede fallar antes de evaluar.

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
| `mapa_banco_fisico_base.json` | banco físico real (8 DI, 8 DO, 4 AI, 4 AO) | **intacto**; sin `I_Emergency`; sin DI libres |
| `mapa_simulacion_completo.json` | simulación con recursos ampliados | intacto |
| `mapa_pid_simulacion.json` | recursos físicos de simulación para P01-P12 | intacto |
| `mapa_pid_banco_fisico.json` | banco PID físico | vacío a propósito (no confirmado) |

**D14 (selección de velocidad):** requiere 3 entradas de selección y 3 salidas de velocidad. Verificación del mapa de
simulación: `mapa_simulacion_completo.json` tiene `I_Speed_Low/Medium/High` (`%IX1.1-1.3`) pero **no tiene salidas de
velocidad**. Para la evaluación formal de D14 hace falta un mapa de simulación con tres salidas `Q_Speed_*` (y que el
flujo experimental lo seleccione). No se ha creado ni se ha modificado ningún mapa.

## 7. Familias funcionales

D03, D04 y D11 implementan la misma capacidad (memoria de marcha Start/Stop) con distinta redacción; se conservan los
tres casos y se tratan como una **familia funcional** en el análisis secundario (para no sobreponderar esa capacidad
en métricas agregadas). En v3, D03 acepta semánticamente `INT_MOTOR_START_STOP` e `INT_MOTOR_LATCH`, igual que D04/D11.
