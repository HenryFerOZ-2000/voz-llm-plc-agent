# 10 Generacion de POU y Proyectos

## Panorama general

El flujo de generacion actual ya no termina al producir una cadena ST. Ahora el sistema construye una POU y la empaqueta como un proyecto portable por plataforma.

## Generacion de la POU

La POU principal se define con:

- `name = PLC_PRG`
- `pou_type = PROGRAM`
- `language = ST`

Su contenido se construye desde la IR con:

- variables autorizadas,
- bloques estandar auxiliares,
- implementacion ST segun la intencion,
- comentarios para trazabilidad.

## Generacion de declaraciones

Los adaptadores generan `declarations.st` a partir de la lista de `PLCVariable`.

### OpenPLC

- usa `AT` en entradas y salidas cuando existe ubicacion fisica,
- conserva temporizadores, contadores y detectores sin ubicacion.

### CODESYS

- omite `AT` por defecto para facilitar simulacion local,
- deja preparada la estructura para una futura exportacion automatizada.

### Siemens TIA Portal V18

- convierte direcciones IEC `%IX` y `%QX` a direcciones Siemens `%I` y `%Q`;
- genera una fuente externa SCL con `FUNCTION_BLOCK PLC_PRG`, DB de instancia y `ORGANIZATION_BLOCK Main`;
- conserva la logica deterministica de la IR y no permite que Openness cambie la intencion.

## Generacion de implementacion

`src/code_generator.py` produce `implementation.st` desde `PLCProjectIR` mediante plantillas controladas por `intent_id`.

Si una intencion no tiene plantilla:

- se lanza una excepcion controlada,
- la verificacion marca el proyecto como invalido,
- el resultado no se presenta como apto para simulacion.

## Generacion del programa completo

Cada adaptador construye `full_program.st` combinando:

1. cabecera documental,
2. declaraciones,
3. logica de implementacion.

Esto facilita:

- revision humana,
- respaldo documental,
- exportacion TXT desde la GUI.

## Generacion de tarea

La tarea actual del MVP es:

- `MainTask`
- `T#100ms`
- prioridad `1`
- asociada a `PLC_PRG`

Esta informacion se serializa en `task_config.json`.

## Manifiestos del proyecto

Cada paquete incluye:

- `project_manifest.json`
- `pou_manifest.json`
- `task_config.json`
- `semantic_input.json`
- `semantic_validation.json`
- `generation_metadata.json`
- `retrieved_context.json`

Estos archivos permiten documentar:

- plataforma,
- nombre del proyecto,
- POU,
- lenguaje,
- tarea,
- archivos generados,
- `case_id`,
- `intent_id`,
- modo de parser,
- estado semantico,
- estado de verificacion,
- estado real de compilacion y simulacion.

## Uso en OpenPLC

El paquete OpenPLC sirve para:

- revisar declaraciones con ubicaciones fisicas,
- inspeccionar `full_program.st`,
- compilar automaticamente con MatIEC o STruC++ cuando estan disponibles,
- ejecutar los casos funcionales basicos sobre el C generado por MatIEC.

La evidencia queda guardada en:

- `openplc_compilation.json`,
- `openplc_simulation.json`,
- `openplc_build/`.

Los estados esperados para una validacion completa de software son:

- `COMPILATION_PASSED`,
- `SIMULATION_PASSED`,
- `is_fully_validated = true`.

## Uso en CODESYS

El paquete CODESYS sirve para:

- documentar una variante portable,
- separar declaraciones e implementacion,
- dejar preparada una futura automatizacion por scripting.

## Uso en TIA Portal V18

El paquete Siemens incluye `siemens_source.scl` y `tia_import_manifest.json`. El puente Openness puede crear la tabla `PLC_Agent_IO`, importar la fuente, generar los bloques, compilar el software PLC y guardar el proyecto si no existen errores. El reporte queda en `tia_compile_report.json`.

## Partes que siguen siendo manuales

Todavia permanecen manuales:

- la carga del programa en OpenPLC Runtime,
- la descarga a hardware real,
- la validacion de campo,
- la aprobacion de seguridad industrial.

## Conclusion

La generacion de POU y de paquetes de proyecto convierte al MVP en una arquitectura mas cercana al flujo real de ingenieria PLC y mas solida como evidencia academica para la tesis.
