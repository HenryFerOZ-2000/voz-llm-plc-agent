# 16 Integracion TIA Portal Openness V18

## Objetivo

Integrar Siemens TIA Portal V18 en la misma arquitectura sin reemplazar OpenPLC ni CODESYS. La aplicacion puede generar un paquete Siemens, importar sus bloques mediante Openness y conservar la compilacion como evidencia experimental.

## Arquitectura

El flujo Siemens es:

`Comando -> parser reglas/LLM/hibrido -> JSON validado -> PLCProjectIR -> SiemensSCLAdapter -> siemens_source.scl -> confirmacion humana -> puente C# Openness -> TIA Portal V18 -> compilacion -> tia_compile_report.json`

Python mantiene la logica del agente y la trazabilidad. `tia_openness_bridge/Program.cs` es el adaptador local que referencia `Siemens.Engineering.dll` y ejecuta las operaciones de ingenieria.

## Operaciones implementadas

- detectar la API publica V18 y el compilador C# local;
- conectarse a una instancia abierta de TIA o abrir el proyecto configurado;
- localizar el software de la CPU;
- crear la tabla de tags `PLC_Agent_IO` con entradas y salidas autorizadas;
- importar `siemens_source.scl` como fuente externa;
- generar FB, DB de instancia y OB desde la fuente;
- compilar el software PLC y registrar mensajes, errores y advertencias;
- guardar el proyecto solo cuando la compilacion no reporta errores.

## Archivos Siemens

Los paquetes se guardan en `generated_code/SIEMENS/active/`. Cada ensayo conserva los artefactos comunes y:

- `siemens_source.scl`: fuente importable en TIA Portal;
- `tia_import_manifest.json`: contrato de importacion;
- `tia_openness_request.json`: operacion solicitada al puente;
- `tia_compile_report.json`: resultado real devuelto por TIA Portal.

El log correspondiente queda en `generated_code/SIEMENS/logs/` y el historial de la GUI restaura tanto la fuente como el reporte.

## Barreras de seguridad

- Openness solo recibe tags procedentes de `io_map.json`;
- el LLM no escribe SCL ni llama directamente a TIA Portal;
- generar un paquete no modifica un proyecto TIA;
- importar y compilar exige confirmacion del usuario;
- no existe operacion de descarga fisica en el puente;
- el reporte siempre registra `physical_download_executed = false`.

## Requisito local pendiente

El usuario de Windows debe pertenecer al grupo `Siemens TIA Openness` y volver a iniciar sesion. Tambien se debe seleccionar un proyecto `.ap18` que contenga una CPU. Sin esos requisitos, el diagnostico informa `is_ready = false` y no intenta modificar TIA Portal.
