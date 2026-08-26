# 06 MVP Funcional

## Ejecucion del sistema

Desde la raiz del proyecto:

```powershell
python src/main.py
```

La interfaz grafica se ejecuta con:

```powershell
python src/gui.py
```

El menu terminal mantiene estas opciones:

1. Probar comando manual
2. Ejecutar comandos de prueba desde `tests/test_cases.json`
3. Archivar codigos generados
4. Limpiar codigos generados
5. Salir

## Flujo funcional actual

El MVP ya no trabaja solo con archivos ST sueltos. La cadena funcional actual es:

`Texto o voz -> transcripcion opcional -> normalizacion -> parser RULE_BASED / LLM / HYBRID -> JSON semantico -> validacion de esquema y negocio -> PLCProjectIR -> verificacion de IR -> generacion ST -> adaptador de plataforma -> paquete PLC -> verificacion de paquete -> guardado`

Esto permite separar:

- la comprension del comando,
- la representacion intermedia del problema de automatizacion,
- la sintaxis final propia de OpenPLC o CODESYS,
- la trazabilidad experimental de cada ensayo.

## Modulos principales

### `src/semantic_parser.py`

Convierte el comando industrial a una salida semantica con:

- `intent_id`,
- `command_text`,
- `normalized_command`,
- `parameters`,
- `confidence`,
- `ambiguities`,
- `requires_clarification`,
- `recognized_tags`,
- `unrecognized_terms`.

### `src/llm_parser.py`

Actua como capa orquestadora de interpretacion semantica y define tres modos:

- `rule_based`
- `llm`
- `hybrid`

En esta etapa:

- `rule_based` usa `src/semantic_parser.py`,
- `llm` usa `src/llm_client.py` y salida estructurada,
- `hybrid` combina reglas, LLM, comparacion y fallback seguro,
- si no existe proveedor configurado, el sistema aplica fallback seguro a reglas.

### `src/semantic_validator.py`

Valida despues del parser:

- estructura semantica,
- tags autorizados,
- tiempos IEC,
- enteros positivos en contadores,
- presencia de emergencia en logicas criticas,
- coherencia entre intencion y parametros,
- posibilidad real de generar plantilla deterministica.

### `src/speech_recognizer.py`

Permite:

- iniciar y detener captura de voz,
- guardar WAV temporal,
- transcribir con API si existe configuracion,
- mantener el texto editable antes de generar.

## `src/plc_ir.py`

Define la representacion intermedia independiente de la plataforma:

- `PLCVariable`,
- `PLCFunctionBlockInstance`,
- `PLCPOU`,
- `PLCTask`,
- `PLCProjectIR`.

Cada modelo incorpora `to_dict()` para serializacion y registro.

### `src/ir_builder.py`

Construye la IR a partir del resultado semantico:

- selecciona variables requeridas por intencion,
- toma solo variables autorizadas del `io_map.json`,
- crea la POU `PLC_PRG`,
- crea la tarea `MainTask`,
- agrega reglas de seguridad,
- genera casos de prueba basicos.

### `src/code_generator.py`

Genera la implementacion ST desde la IR mediante:

```python
generate_implementation_from_ir(project_ir)
```

Las plantillas funcionales actuales cubren, entre otras:

- `INT_TIMED_PULSE`
- `INT_MOTOR_START_STOP`
- `INT_DELAYED_START`
- `INT_DELAYED_STOP`
- `INT_EMERGENCY_PRIORITY`
- `INT_COUNTER_PULSES`
- `INT_MUTUAL_INTERLOCK`
- `INT_MANUAL_AUTO_MODE`
- `INT_STATUS_PILOTS`
- `INT_MAINTENANCE_BLOCK`
- `INT_SENSOR_TIMEOUT_ALARM`
- `INT_AUTO_CYCLE`

### `src/platforms/`

Contiene la capa de adaptacion por plataforma:

- `base_adapter.py`
- `openplc_adapter.py`
- `codesys_adapter.py`

Cada adaptador transforma la misma IR en artefactos concretos de proyecto.

### `src/project_packager.py`

Coordina el flujo de empaquetado:

1. construye `PLCProjectIR`,
2. genera la implementacion ST,
3. selecciona adaptador OpenPLC o CODESYS,
4. arma manifiestos, tarea y pruebas,
5. guarda el paquete,
6. ejecuta verificacion final.

### `src/verifier.py`

Valida dos niveles:

- `verify_project_ir(project_ir)`
- `verify_generated_package(package_dir)`

Tambien se mantiene `verify_code(...)` para compatibilidad y revisiones puntuales de ST.

### `src/logger.py`

Gestiona:

- guardado por carpeta de paquete,
- log JSON por generacion,
- archivado de carpetas completas,
- limpieza controlada con confirmacion.

## POU y tarea del MVP

La IR genera por defecto:

- `POU`: `PLC_PRG`
- `POU type`: `PROGRAM`
- `language`: `ST`
- `task`: `MainTask`
- `interval`: `T#100ms`
- `priority`: `1`

## Artefactos del paquete PLC

Cada generacion valida produce una carpeta de paquete por plataforma con:

1. `full_program.st`
2. `declarations.st`
3. `implementation.st`
4. `variables.json`
5. `project_manifest.json`
6. `pou_manifest.json`
7. `task_config.json`
8. `test_cases.json`
9. `semantic_input.json`
10. `semantic_validation.json`
11. `generation_metadata.json`
12. `retrieved_context.json`
13. `verification.json`

## Gestion de archivos generados

La estructura operativa es:

```text
generated_code/
|-- OPENPLC/
|   |-- active/
|   |-- logs/
|   `-- archived/
`-- CODESYS/
    |-- active/
    |-- logs/
    `-- archived/
```

- `generated_code/OPENPLC/active/` guarda paquetes activos para OpenPLC.
- `generated_code/OPENPLC/logs/` guarda metadata JSON por generacion.
- `generated_code/OPENPLC/archived/` conserva ensayos anteriores.
- `generated_code/CODESYS/active/` guarda paquetes activos para CODESYS.
- `generated_code/CODESYS/logs/` guarda metadata JSON por generacion.
- `generated_code/CODESYS/archived/` conserva ensayos anteriores.

Desde el menu terminal o la GUI:

- `Archivar codigos generados` mueve carpetas completas desde `active/` a `archived/`.
- `Limpiar codigos generados` elimina paquetes activos y logs actuales, pero nunca borra `archived/`.

## Interfaz grafica del sistema

La GUI de escritorio conserva el dashboard y ahora muestra:

- `Voz`
- `Interpretacion`
- `Comparacion reglas/LLM`
- `Parametros`
- `Representacion intermedia`
- `POU`
- `Tarea`
- `Proyecto OpenPLC`
- `Proyecto CODESYS`
- `Casos de prueba`
- `Verificacion`
- `Archivos`
- `Historial`

La interfaz reutiliza la misma logica del modo terminal y no duplica reglas de negocio.

Antes de crear el paquete, la GUI separa dos acciones:

1. `Procesar comando`
2. `Generar paquete PLC`

Esto permite revisar:

- transcripcion,
- intencion,
- parametros,
- tags reconocidos,
- ambiguedades,
- reglas de seguridad,
- plataformas seleccionadas.

## Criterio de seguridad del MVP

El sistema sigue estas reglas base:

- no usar tags fuera de `config/io_map.json`,
- priorizar `I_Emergency` sobre salidas criticas,
- priorizar `I_Stop` sobre `I_Start`,
- impedir autoarranque al liberar emergencia,
- exigir comentarios en la logica generada,
- registrar casos de prueba basicos.

## Ejemplo funcional base

Comando:

```text
Haz que el motor se encienda con Start y se apague con Stop
```

Resultado esperado:

- `intent_id = INT_MOTOR_START_STOP`
- `semantic_validation.is_valid = true`
- `POU = PLC_PRG`
- `task = MainTask`
- variables autorizadas del mapa I/O
- casos de prueba basicos
- paquete OpenPLC y/o CODESYS segun la seleccion
- `verification.is_valid = true`
- para OpenPLC, `compilation_status = COMPILATION_PASSED`
- para OpenPLC, `simulation_status = SIMULATION_PASSED`
- reportes `openplc_compilation.json` y `openplc_simulation.json`
