# 21 Supervisión PID (P01-P12)

## Propósito

Ampliación **aditiva** de la arquitectura existente (D01-D20, `functional_requirements`, IR, SCL,
TIA Openness) para soportar un segundo dominio experimental: control supervisor alrededor de un
bloque PID **estándar y ya validado** en TIA Portal (por ejemplo `PID_Compact`). Nada de lo ya
descrito en `19_perfiles_experimentales_d01_d20.md` / `20_modo_experimentacion.md` cambia — Modo
Normal, el pipeline voz/texto → parser → `semantic_output` → IR → SCL → TIA Openness, y los casos
D01-D20 siguen funcionando exactamente igual.

## El PID nunca se rediseña

La aplicación **no genera** el algoritmo PID, ni `Kp`/`Ki`/`Kd`, ni autotuning, ni la estructura
interna de ningún bloque. Se asume que el proyecto plantilla de TIA Portal ya tiene un bloque PID
estándar interconectado manualmente con las variables funcionales que el supervisor generado lee y
escribe (`Level_SP` como setpoint, `Level_PV` como entrada de proceso, `PID_Enable`/`Auto_Mode`
como habilitación). Esa referencia es **metadata informativa**, no código que instancie o llame al
bloque — ver `config/pid_supervisor_config.json` → `pid_block_reference` (`confirmed: false` hasta
que el bloque real del proyecto se confirme; el campo existe para configurarlo sin tocar código).

Lo que la arquitectura genera es exclusivamente la **lógica supervisora**: habilitar/deshabilitar
el PID, cambiar de modo automático/manual, validar y aplicar el setpoint, alarmas de nivel, fallo
de sensor, reset condicionado y parada segura por sobrellenado.

## Intent único + functional_requirements (sin explosión de intents)

Un solo intent principal, `INT_PID_SUPERVISOR` (`config/intents_catalog.json`), cubre los 12 casos.
Requiere solo la base de seguridad común (`I_Emergency`, `I_Reset`, `Q_Alarm`, `Q_Pump_Enable`); el
comportamiento específico de cada Pxx lo aporta `functional_requirements`, reutilizando el MISMO
mecanismo ya construido para comandos compuestos discretos (`src/functional_requirements.py`):
cobertura semántica, segunda pasada LLM controlada, detección de conflictos, y composición hasta
IR/SCL. No se creó `normal_validator.py`/`experimental_validator.py` ni un segundo pipeline.

Catálogo de tipos PID (`FUNCTIONAL_REQUIREMENT_TAGS` / `FUNCTIONAL_REQUIREMENT_PROCESS_VARIABLES`):

| type | recursos físicos (I_/Q_) | variables funcionales (software) |
|---|---|---|
| `set_auto_mode` | — | `Auto_Mode`, `Manual_Mode` |
| `set_manual_mode` | — | `Auto_Mode`, `Manual_Mode` |
| `set_level_setpoint` (`value`) | — | `Level_SP` |
| `enable_pid` | `I_Emergency` | `PID_Enable`, `Auto_Mode`, `Sensor_Fault`, `Safe_Stop` |
| `disable_pid` | — | `PID_Enable` |
| `high_level_alarm` (`limit`) | `Q_Alarm` | `Level_PV`, `High_Level_Alarm` |
| `low_level_alarm` (`limit`) | `Q_Alarm` | `Level_PV`, `Low_Level_Alarm` |
| `sensor_range_fault` | — | `Level_PV`, `Sensor_Fault`, `PID_Enable` |
| `conditional_alarm_reset` | `I_Reset` | `High_Level_Alarm`, `Low_Level_Alarm`, `Sensor_Fault` |
| `safe_overfill_stop` (`limit`) | `Q_Pump_Enable`, `Q_Alarm` | `Level_PV`, `Safe_Stop`, `PID_Enable` |
| `manual_pump_limit` | `Q_Pump_Enable` | `Manual_Mode` |

## Variables funcionales vs. recursos físicos

Regla explícita (no se debilita en ningún punto del pipeline): `Level_PV`, `Level_SP`,
`PID_Enable`, `Auto_Mode`, `Manual_Mode`, `High_Level_Alarm`, `Low_Level_Alarm`, `Sensor_Fault`,
`Safe_Stop` son **variables funcionales de software** (`PID_PROCESS_VARIABLES`), resueltas por el
mecanismo ad-hoc ya existente (`ir_builder._resolve_functional_variables`) — nunca se convierten en
tags `I_`/`Q_`, nunca requieren existir en el mapa PLC. Los únicos recursos físicos del dominio PID
son `I_Emergency`, `I_Reset`, `Q_Pump_Enable`, `Q_Alarm`, sujetos a la regla ya existente: deben
existir/estar autorizados en el mapa o perfil activo, o el pipeline se detiene (nunca se inventan).

`build_project_ir()` expande cada `functional_requirement` de catálogo PID en una entrada ad-hoc
(`{"name": "Level_SP", "type": "REAL", ...}`) automáticamente, antes de resolver variables — el
llamador nunca tiene que declararlas dos veces.

## Mapa y perfiles PID

`data/plc_maps/mapa_pid_simulacion.json` (`MAPA_PID_SIMULACION`) contiene únicamente los 4 recursos
físicos: `I_Emergency`/`I_Reset` en las MISMAS direcciones que `MAPA_SIMULACION_COMPLETO`
(`%IX0.2`/`%IX0.3`) — se asume el mismo botón de E-stop/reset físico del banco de pruebas — y
`Q_Pump_Enable`/`Q_Alarm` en el byte `%QX0.1`/`%QX1.0` para no colisionar con las salidas D01-D20 ya
asignadas.

`data/plc_maps/mapa_pid_banco_fisico.json` (`MAPA_PID_BANCO_FISICO`) se deja **vacío a propósito**:
el banco físico del proceso de nivel/bomba todavía no está confirmado. No se inventan direcciones
analógicas, módulos, canales, sensor de nivel ni señal de bomba reales — exactamente la misma
disciplina que ya se aplicó a D14/D19. Por eso **todo** perfil P01-P12 reporta
`hardware_ready=False` hasta que ese banco se defina; `simulation_ready` sí es `True` para todos.

`plc_maps/profiles.py::profile_readiness_summary()` ahora decide contra qué par de mapas
(simulación/hardware) comprobar la disponibilidad según el prefijo de `case_id` (`D` → mapas
discretos, `P` → mapas PID) — D01-D20 siguen comprobándose exactamente igual que antes.

`data/plc_maps/profiles.json` incluye los 12 perfiles P01-P12, cada uno con solo los recursos
físicos que su caso necesita (ver tabla de arriba); los recursos internos/funcionales nunca se
restringen por perfil.

## Validación de setpoint: determinística, no delegada al LLM

`config/pid_supervisor_config.json` define `level_setpoint.min`/`max` (10-90% por defecto),
`high_level_alarm`/`low_level_alarm`/`safe_overfill_stop.default_limit`, y `sensor_valid_range`.
`semantic_validator._detect_unsafe_level_setpoints()` rechaza cualquier `set_level_setpoint` fuera
de rango **antes** de generar IR/SCL, forzando `requires_clarification=True` con un mensaje que
indica el rango permitido — el LLM nunca decide si un setpoint es seguro, solo reporta el valor
pedido.

## Seguridad: prioridad de emergencia y modo manual

`code_generator._generate_pid_supervisor_body()` compone la lógica ST según qué
`functional_requirements` estén presentes (no una plantilla monolítica por caso). El primer bloque
generado, siempre presente, es incondicional:

```
IF I_Emergency THEN
    PID_Enable := FALSE;
    Q_Pump_Enable := FALSE;
END_IF;
```

El modo manual (`manual_pump_limit`) nunca elimina las condiciones de seguridad: la bomba solo se
habilita si `Manual_Mode AND NOT I_Emergency AND NOT Sensor_Fault AND NOT Safe_Stop`. La fórmula
agregada de `PID_Enable` (`enable_pid`) incluye `NOT I_Emergency` siempre, más `Auto_Mode`/`NOT
Sensor_Fault`/`NOT Safe_Stop` cuando esas variables están declaradas. Un `disable_pid` aislado
(p. ej. P07) no necesita una línea propia: el bloque de emergencia incondicional y el valor inicial
`FALSE` de `PID_Enable` ya lo cubren, sin duplicar lógica.

## Verificación de propagación

`verifier.py` añade `REAL` a los tipos de declaración soportados (antes bloqueaba cualquier
variable `REAL`, incluida `Level_SP`) y valida que **todo** tag que un `functional_requirement`
implica realmente llegó a la IR — si faltara, es un error explícito antes de tocar TIA, no un éxito
silencioso.

## Modo Experimentación: grupo PID

`Grupo de pruebas` ahora ofrece `Discreto D01-D20` y `PID P01-P12`. Al seleccionar PID, `Caso
experimental` solo lista P01-P12 (nunca mezclado con Dxx). Si el mapa activo no tiene
`Q_Pump_Enable`, la GUI ofrece cambiar a `MAPA_PID_SIMULACION` explícitamente (nunca lo cambia en
silencio). `experiment_family` en el registro del ensayo pasa a `"PID"` automáticamente cuando el
`case_id` empieza con `P`.

## Modo Normal

`INT_PID_SUPERVISOR` no está limitado a P01-P12: con `MAPA_PID_SIMULACION` (o cualquier mapa que
tenga los tags necesarios) activo, un comando en Modo Normal como *"Pon el setpoint de nivel en 55
% y activa modo automático"* usa el mismo pipeline sin pasar por el modo experimental.

## Condiciones C1-C4 y evidencia experimental

P01-P12 usan exactamente las mismas condiciones C1-C4, formato de `experiment_label`
(`C{condicion}_{caso}_{variante}_R{repeticion}`), cálculo de repetición, sistema de resultados
(`experimental_results.json/csv`) y taxonomía de errores E1-E10 ya existentes — no se creó ningún
mecanismo paralelo.

## Preparación para Factory I/O (no implementado en esta etapa)

No se instala, integra ni referencia Factory I/O. El único requisito para que se pueda añadir más
adelante sin tocar el pipeline semántico es que las variables físicas del proceso PID
(`I_Emergency`, `I_Reset`, `Q_Pump_Enable`, `Q_Alarm`, y eventualmente `Level_PV` analógica) tengan
direcciones PLC estables — ya es el caso en `MAPA_PID_SIMULACION`.

## Limitaciones conocidas

- `Level_PV` (entrada analógica real) no tiene dirección física confirmada — sigue siendo
  puramente funcional hasta que el banco PID se defina (`MAPA_PID_BANCO_FISICO` vacío a propósito).
- La referencia al bloque PID real (`pid_block_reference.confirmed=false`) es informativa; no se
  ha confirmado el nombre/tipo exacto del bloque en el proyecto TIA plantilla.
- No se completó una importación/compilación real en TIA Portal para PID en esta entrega (la
  consulta de tags existentes al proyecto TIA agotó el tiempo de espera); el SCL generado ya se
  verificó sintáctica y semánticamente (`verify_project_ir`), y las direcciones de `I_Emergency`/
  `I_Reset`/`Q_Alarm` se alinearon deliberadamente con las de D01-D20 para evitar conflictos de tag
  al momento de intentarlo.
