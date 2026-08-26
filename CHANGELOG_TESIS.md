# CHANGELOG Tesis

## [2026-08-18]
### Integracion paralela con TIA Portal Openness V18

- Se agrego `SIEMENS_SCL_V18` sin retirar OpenPLC ni CODESYS.
- Se incorporo un adaptador SCL que genera FB, DB de instancia, OB principal y tags autorizados.
- Se creo un puente C# compilado contra la API real `Siemens.Engineering.dll` V18.
- La GUI permite configurar un proyecto `.ap18`, diagnosticar Openness e importar y compilar con confirmacion explicita.
- Los paquetes y logs Siemens se guardan en `generated_code/SIEMENS/` y reaparecen en el historial.
- Se conserva `tia_compile_report.json` como evidencia y se mantiene bloqueada la descarga fisica automatica.

## [2026-07-14]
### Comandos de voz operativos y validados

- Se reforzo la captura local con deteccion del microfono y analisis basico del WAV.
- La transcripcion usa espanol y un contexto de vocabulario de automatizacion industrial.
- La GUI transcribe en segundo plano, mantiene la interfaz responsiva y permite editar el texto antes de procesarlo.
- Los controles de voz bloquean acciones incompatibles durante grabacion o transcripcion.
- Se valido el flujo real ASR hasta `INT_MOTOR_START_STOP` y se agregaron pruebas automatizadas del modulo.

### Soporte para motor ciclico temporizado

- Se agrego `INT_CYCLIC_MOTOR` para ordenes de encendido y apagado repetitivo hasta Stop.
- El parser reconoce `pulsante de encendido`, bucles y dos tiempos IEC independientes.
- La plantilla usa flanco de Start, prioridad de Stop/emergencia y evita autoarranque tras liberar emergencia.
- Se incorporaron pruebas funcionales de ambas fases y compilacion/simulacion OpenPLC.

### Validacion automatica de POUs OpenPLC

- Se agrego `src/openplc_validator.py` para detectar MatIEC/STruC++, compilar `full_program.st` y guardar evidencia.
- Los paquetes OpenPLC ejecutan casos funcionales sobre el C generado por MatIEC cuando GCC esta disponible.
- Se agregaron `openplc_compilation.json`, `openplc_simulation.json` y estados de validacion completa.
- El adaptador OpenPLC separa variables ubicadas e internas en bloques `VAR` compatibles con MatIEC y cierra con `END_PROGRAM`.
- La plantilla `CTU` usa la entrada IEC estandar `R` para compatibilidad OpenPLC.

### Activacion operativa de API LLM en GUI y diagnostico

- Se agrego `src/env_manager.py` para crear, leer y actualizar `.env` local sin editarlo manualmente.
- Se agrego `.env` inicial del proyecto y `src/check_llm_connection.py` para diagnostico rapido y prueba real con `--live`.
- `src/gui.py` ahora comparte un `PLCInterpretationLLMClient`, muestra estado LLM en la interfaz y permite `Configurar API LLM` y `Probar conexion`.
- El parser GUI ahora informa con claridad cuando `llm` o `hybrid` siguen en modo demo local por falta de credenciales.

### Integracion de LLM real, voz y generacion controlada de POUs

- Se agregaron `src/llm_client.py`, `config/llm_config.json`, `.env.example` y `prompts/llm_semantic_parser_prompt.txt`.
- Se introdujo `schemas/semantic_output.schema.json` y `src/schemas.py` para salida estructurada.
- `src/llm_parser.py` ahora soporta `rule_based`, `llm` y `hybrid`.
- Se agrego `src/semantic_validator.py` para bloquear salidas semanticas invalidas antes de construir la IR.
- Se agrego `src/speech_recognizer.py` para captura y transcripcion opcional de voz.
- Se incorporo `knowledge_base/` y `src/knowledge_retriever.py` para apoyo local al parser LLM.
- Los paquetes PLC ahora incluyen `semantic_input.json`, `semantic_validation.json`, `generation_metadata.json` y `retrieved_context.json`.
- La GUI separa `Procesar comando` y `Generar paquete PLC`, muestra comparacion reglas/LLM y permite revisar voz antes de confirmar.
- Se agregaron `src/evaluation_runner.py` y `src/metrics.py` para el protocolo experimental.
- Se agregaron pruebas unitarias para esquema, parser, validador, IR, adaptadores, paquete y voz.

### Generacion de POU y paquetes de proyecto PLC

- Incorporacion de `src/plc_ir.py` y `src/ir_builder.py` para modelar `PLCProjectIR`, POU, tarea, variables y bloques estandar.
- Refactorizacion de `src/code_generator.py` para generar implementacion ST desde la representacion intermedia.
- Creacion de adaptadores `OpenPLCAdapter` y `CodesysAdapter` en `src/platforms/`.
- Nuevo `src/project_packager.py` para construir, verificar y guardar paquetes completos por plataforma.
- Verificacion dual de IR y de paquete mediante `verify_project_ir(...)` y `verify_generated_package(...)`.
- Nuevo esquema de salida por carpeta con `full_program.st`, `declarations.st`, `implementation.st`, `variables.json`, `project_manifest.json`, `pou_manifest.json`, `task_config.json`, `test_cases.json` y `verification.json`.
- Actualizacion del modo terminal y de la GUI para mostrar representacion intermedia, POU, tarea, proyectos y casos de prueba.

### Capa de parser LLM preparada

- Nuevo archivo `src/llm_parser.py` como router de interpretacion semantica.
- Nuevo archivo `config/parser_settings.json` para seleccionar `rule_based` o `llm`.
- Integracion de fallback seguro a reglas cuando no existe proveedor LLM real configurado.

## [2026-07-13]
### Creacion de interfaz grafica de escritorio

- Incorporacion de `src/gui.py` con interfaz `CustomTkinter`.
- Edicion visual del mapa I/O con validacion y guardado sobre `config/io_map.json`.
- Visualizacion por pestañas de intencion, parametros, variables, codigo OpenPLC/CODESYS, verificacion, archivos e historial.
- Consola visual del sistema y gestion de archivado o limpieza desde la GUI.
- Conservacion del modo terminal con `python src/main.py`.

## [2026-07-08]
### Correccion integral de generacion funcional ST

- Rechazo de fallbacks y plantillas no implementadas como codigo funcional valido.
- Incorporacion de `INT_DELAYED_STOP`.
- Verificacion funcional por intencion detectada.
- Generacion dual `OPENPLC_ST` y `CODESYS_ST`.
- Uso estricto del mapa I/O como fuente de verdad.

Documento ampliado: `docs/CHANGELOG_TESIS.md`.
