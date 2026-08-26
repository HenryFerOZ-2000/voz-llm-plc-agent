# 09 Representacion Intermedia PLC

## Objetivo

La representacion intermedia PLC permite modelar un programa de automatizacion sin comprometerse de inmediato con la sintaxis de OpenPLC o CODESYS.

## Modelo principal

La IR se implementa en `src/plc_ir.py` y se organiza alrededor de `PLCProjectIR`.

### `PLCProjectIR`

Representa una generacion completa y contiene:

- `project_name`
- `target_platform`
- `case_id`
- `intent_id`
- `command_text`
- `pou`
- `task`
- `safety_rules`
- `test_cases`
- `metadata`

### `PLCPOU`

Describe la unidad logica principal del proyecto:

- `name`
- `pou_type`
- `language`
- `variables`
- `function_blocks`
- `implementation_code`
- `comments`

### `PLCVariable`

Modela cada variable declarada en la POU:

- nombre,
- tipo de dato,
- clase,
- ubicacion fisica opcional,
- valor inicial opcional,
- descripcion,
- origen,
- indicador de bloque estandar.

### `PLCTask`

Representa la tarea asociada a la POU:

- `name`
- `interval`
- `priority`
- `pou_name`

### `PLCFunctionBlockInstance`

Registra instancias auxiliares como:

- `TON`
- `TP`
- `CTU`
- `R_TRIG`
- `F_TRIG`

## Constructor de IR

`src/ir_builder.py` toma:

- el resultado semantico,
- el `io_map.json`,
- la plataforma objetivo.

Y construye:

- una lista validada de variables requeridas,
- la POU `PLC_PRG`,
- la tarea `MainTask`,
- los bloques estandar necesarios,
- reglas de seguridad serializadas,
- casos de prueba basicos.

## Beneficios de la IR

La capa intermedia aporta:

- independencia respecto a OpenPLC o CODESYS,
- verificacion antes de generar archivos finales,
- mejor trazabilidad para tesis,
- posibilidad futura de exportar a otras plataformas,
- separacion clara entre semantica, logica y adaptacion.

## Relacion con los adaptadores

Los adaptadores de `src/platforms/` reciben la misma `PLCProjectIR` y producen:

- declaraciones,
- implementacion,
- programa completo,
- manifiestos,
- configuracion de tarea,
- casos de prueba serializados.

## Manifiestos

La IR no guarda archivos directamente, pero si concentra la informacion necesaria para generar:

- `project_manifest.json`
- `pou_manifest.json`
- `task_config.json`

## Relacion con la validacion semantica

La IR solo se construye cuando el `SemanticOutput` ya paso:

- validacion de esquema,
- validacion Pydantic,
- validacion contra mapa I/O,
- validacion de reglas de seguridad.

Por esta razon la IR actua como una capa intermedia limpia, sin ambiguedades pendientes ni tags inventados.

## Conclusión

La representacion intermedia es el nucleo arquitectonico del proyecto porque transforma un comando industrial en una estructura formal, verificable y portable antes de producir artefactos PLC concretos.
