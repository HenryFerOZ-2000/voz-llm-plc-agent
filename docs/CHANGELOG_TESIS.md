# CHANGELOG Tesis

## [2026-08-18]
### Integracion paralela con TIA Portal Openness V18

#### Agregado

- Adaptador `SiemensSCLAdapter` y plataforma `SIEMENS_SCL_V18`.
- Fuente externa `siemens_source.scl`, manifiesto de importacion y reporte de compilacion TIA.
- Servicio Python `src/tia_openness.py` y puente C# basado en la API publica V18.
- Controles GUI y consola para diagnosticar, importar y compilar paquetes Siemens.

#### Seguridad y trazabilidad

- La importacion requiere confirmacion humana y solo usa tags de `io_map.json`.
- El puente no implementa descarga fisica y registra expresamente que no fue ejecutada.
- El historial, los logs y las exportaciones TXT conservan la evidencia Siemens y Openness.

## [2026-07-14]
### Validacion automatica de POUs OpenPLC

#### Agregado

- `src/openplc_validator.py` con deteccion de compilador, compilacion ST y simulacion de casos funcionales.
- Evidencias `openplc_compilation.json` y `openplc_simulation.json` dentro de cada paquete OpenPLC.
- Metricas de tasa de compilacion, simulacion y validacion completa.

#### Modificado

- `OpenPLCAdapter` genera bloques `VAR` compatibles con MatIEC y `END_PROGRAM`.
- Los manifiestos, logs, GUI y evaluador registran estados reales de compilacion y simulacion.

#### Observacion

- No existe despliegue automatico a OpenPLC Runtime ni a hardware; esa barrera continua siendo manual.

### Integracion de LLM real, voz y generacion controlada de POUs

#### Agregado

- `src/llm_client.py`, `src/semantic_validator.py`, `src/speech_recognizer.py`, `src/evaluation_runner.py`, `src/metrics.py`.
- `schemas/semantic_output.schema.json` y `src/schemas.py`.
- `knowledge_base/` y `src/knowledge_retriever.py`.
- Documentos `11_integracion_llm.md`, `12_integracion_voz.md`, `13_arquitectura_hibrida.md`, `14_protocolo_evaluacion.md` y `15_guia_de_configuracion.md`.

#### Modificado

- `src/llm_parser.py` ahora soporta `rule_based`, `llm` y `hybrid`.
- `src/project_packager.py` ahora guarda artefactos semanticos y estados reales.
- `src/gui.py` ahora separa interpretar de generar y agrega soporte de voz y comparacion.

### Generacion de POU y paquetes de proyecto PLC

#### Agregado

- Nuevo archivo `src/plc_ir.py` con modelos `PLCVariable`, `PLCFunctionBlockInstance`, `PLCPOU`, `PLCTask` y `PLCProjectIR`.
- Nuevo archivo `src/ir_builder.py` para construir la representacion intermedia, variables requeridas y casos de prueba.
- Nueva carpeta `src/platforms/` con adaptadores `OpenPLCAdapter` y `CodesysAdapter`.
- Nuevo archivo `src/project_packager.py` para generar paquetes completos por plataforma.
- Nuevos documentos `docs/09_representacion_intermedia_plc.md` y `docs/10_generacion_de_pou_y_proyectos.md`.

#### Modificado

- `src/code_generator.py` ahora genera la implementacion ST desde la IR.
- `src/verifier.py` valida IR y paquetes, no solo ST.
- `src/logger.py` guarda carpetas de proyecto y logs por generacion.
- `src/main.py` y `src/gui.py` muestran POU, tarea, proyectos y casos de prueba.
- `src/main.py` y `src/gui.py` ahora consumen un router de parser preparado para `rule_based` o `llm`.
- `docs/06_mvp_funcional.md` y `docs/08_decisiones_tecnicas.md` fueron actualizados a la nueva arquitectura.

#### Observacion

- La carga fisica a PLC continua fuera del alcance automatico y requiere aprobacion humana.

## [2026-07-13]
### Creacion de interfaz grafica de escritorio

#### Agregado

- Nuevo archivo `src/gui.py` con interfaz de escritorio basada en `CustomTkinter`.
- Nuevo archivo `src/gui_helpers.py` para validacion del mapa I/O, carga de tablas y mensajes de consola.
- Panel de configuracion con edicion visual de `config/io_map.json`.
- Pestañas para intencion, parametros, variables, OpenPLC, CODESYS, verificacion, archivos e historial.
- Consola visual inferior para trazabilidad operativa durante las pruebas.

#### Modificado

- `requirements.txt` ahora incluye `customtkinter`.
- `README.md` documenta la ejecucion de `python src/gui.py`.
- `docs/06_mvp_funcional.md` y `docs/08_decisiones_tecnicas.md` incorporan la arquitectura y justificacion de la GUI.

#### Observacion

- El modo terminal se mantiene operativo y la interfaz grafica reutiliza la misma logica de negocio para evitar duplicacion.

## [2026-07-08]
### Correccion integral de generacion funcional ST

#### Agregado

- Rechazo explicito de fallbacks y de plantillas no implementadas.
- Soporte funcional para `INT_DELAYED_STOP`.
- Verificacion funcional minima por `intent_id`.
- Normalizacion del `io_map.json` como fuente unica de verdad.
- Generacion dual `OPENPLC_ST` y `CODESYS_ST`.
- Exportacion consistente de `full_program.st`, `declarations.st`, `implementation.st`, `variables.json` y `log.json`.

#### Modificado

- El parser ahora interpreta por significado y reconoce nuevas parafrasis.
- El generador ya no usa `Q_Aux_Output := FALSE;` como solucion valida.
- El verificador distingue entre codigo sintacticamente valido y codigo funcionalmente correcto.
- El registro de pruebas documenta la columna `plantilla implementada`.

#### Observacion

- Las intenciones reconocidas por el sistema deben corresponder a plantillas ST reales o marcarse como no validas para ejecucion.
