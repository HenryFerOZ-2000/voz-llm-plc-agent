# voz_llm_plc_agent

`voz_llm_plc_agent` es un proyecto de tesis en Python para programacion automatica de PLC a partir de texto o voz, con interpretacion controlada por reglas y LLM, validacion semantica estricta y generacion deterministica de paquetes PLC.

## Datos de la campaña final de tesis

La evaluación final empleó interpretación LLM exclusiva, un mapa I/O común y 180 comandos: 165 PASS, siete FAIL y ocho REVIEW. El [archivo de la campaña final](data/thesis_campaigns/THESIS_DISCRETE_LLM_180_20261026_R2/README.md) incluye los veinte Oracles, el prompt, los mapas y la configuración, los registros originales disponibles por etapa, el código conservado de la campaña y los scripts para recalcular las estadísticas. La comparación preliminar se conserva por separado.

El [corpus pareado de voz](data/thesis_campaigns/THESIS_DISCRETE_LLM_180_20261026_R2/corpus/README.md) contiene las 60 grabaciones limpias y sus 60 versiones con ruido, autorizadas para compartir por el primer autor y locutor. Los proyectos binarios TIA y el ruido maestro permanecen locales. Los modos y las tareas históricas descritos en otras secciones de este README no implican que se utilizaran en los resultados de la campaña final.

## Objetivo

Demostrar una arquitectura segura donde el modelo de lenguaje solo interpreta el requerimiento y nunca genera ni despliega directamente el codigo final del PLC.

## Enfoque actual: Siemens TIA Portal Openness V18

La fase actual del proyecto se concentra en `SIEMENS_SCL_V18` mediante TIA Portal Openness V18. OpenPLC y CODESYS quedan **aislados de la GUI** (no eliminados): el selector de plataforma se fija en "Siemens TIA V18" mientras el backend, los adaptadores y las pruebas de ambas plataformas se conservan intactos para una reintegracion futura. Detalle de la decision en `docs/08_decisiones_tecnicas.md`.

## Flujo final

`Texto o voz -> ASR opcional -> parser RULE_BASED / LLM / HYBRID -> JSON semantico -> validacion -> PLCProjectIR -> generacion deterministica IEC 61131-3 -> adaptador Siemens/OpenPLC/CODESYS -> verificacion -> paquete PLC -> compilacion OpenPLC o TIA Openness -> trazabilidad`

## Que hace hoy el proyecto

- interpreta comandos industriales con `rule_based`, `llm` o `hybrid`;
- valida la salida semantica con esquema, Pydantic y reglas de negocio;
- construye `PLCProjectIR`;
- genera `implementation.st`, `declarations.st`, `full_program.st`, manifiestos y pruebas;
- empaqueta resultados para `SIEMENS_SCL_V18`, `OPENPLC_ST` y `CODESYS_ST` (la GUI solo expone `SIEMENS_SCL_V18` por ahora; ver "Enfoque actual");
- genera una fuente externa SCL V18 con FB, DB de instancia y OB principal para Siemens;
- integra TIA Portal Openness V18 para importar tags, generar bloques y compilar con confirmacion humana;
- compila automaticamente los paquetes OpenPLC cuando detecta MatIEC o STruC++;
- ejecuta casos funcionales sobre el C generado por MatIEC cuando GCC esta disponible;
- registra semantica, validacion, contexto recuperado y metadata experimental;
- ofrece modo consola y GUI de escritorio;
- admite captura de voz y transcripcion cuando hay microfono y API configurada;
- mantiene un modo demo local sin API.

## Paquetes generados

Cada paquete valido incluye:

- `full_program.st`
- `declarations.st`
- `implementation.st`
- `variables.json`
- `project_manifest.json`
- `pou_manifest.json`
- `task_config.json`
- `test_cases.json`
- `semantic_input.json`
- `semantic_validation.json`
- `generation_metadata.json`
- `retrieved_context.json`
- `verification.json`

Los paquetes Siemens agregan `siemens_source.scl` y `tia_import_manifest.json`. Despues de ejecutar Openness tambien conservan `tia_openness_request.json` y `tia_compile_report.json`.

Los paquetes OpenPLC validados tambien incluyen:

- `openplc_compilation.json`
- `openplc_simulation.json`
- `openplc_build/` con la salida del compilador y el arnes de pruebas

## Modo sin API

Sin `OPENAI_API_KEY` el proyecto sigue funcionando con:

- parser por reglas;
- modo hibrido con fallback seguro a reglas;
- GUI y consola;
- generacion de POU y paquetes;
- OpenPLC y CODESYS;
- verificacion y guardado.

Los botones LLM y voz no cierran la aplicacion: muestran que requieren configuracion.

## Modo con API

Con API y modelos configurados:

- el parser `llm` usa `client.responses.parse(...)` con salida estructurada;
- el modo `hybrid` consulta al LLM cuando las reglas son ambiguas o insuficientes;
- la voz usa transcripcion con el modelo configurado;
- el resultado vuelve a pasar por validacion local antes de construir la IR.
- la GUI permite guardar `.env`, mostrar el estado LLM y probar la conexion.

## Configuracion

1. Crear entorno virtual:

```powershell
python -m venv .venv
```

2. Activar en Windows:

```powershell
.\.venv\Scripts\Activate.ps1
```

3. Instalar dependencias:

```powershell
pip install -r requirements.txt
```

4. Copiar `.env.example` a `.env` y definir, si aplica:

```env
OPENAI_API_KEY=
PLC_LLM_MODEL=
PLC_TRANSCRIPTION_MODEL=
PARSER_MODE=hybrid
LLM_CONFIDENCE_THRESHOLD=0.85
ENABLE_LLM=true
ENABLE_VOICE=true
OPENPLC_AUTO_VALIDATE=true
OPENPLC_RUN_SIMULATION=true
OPENPLC_COMPILER_PATH=
OPENPLC_GCC_PATH=
```

Tambien puede configurar estos valores desde la GUI usando `Configurar API LLM`.

5. Para usar la integracion TIA Portal Openness V18, copiar manualmente `Siemens.Engineering.dll` y `Siemens.Engineering.Hmi.dll` desde la instalacion local de TIA Portal (`C:/Program Files/Siemens/Automation/Portal V18/PublicAPI/V18/`) a `tia_openness_bridge/bin/`. Estas DLL son propiedad de Siemens y no se incluyen en el repositorio por licencia; ver `docs/15_guia_de_configuracion.md`.

## Ejecucion

Modo consola:

```powershell
python src/main.py
```

Modo grafico:

```powershell
python src/gui.py
```

Lanzador grafico sin consola:

```text
Abrir_Voz_LLM_PLC_Agent.pyw
```

Diagnostico de configuracion LLM:

```powershell
python src/check_llm_connection.py
```

Prueba real de conexion OpenAI:

```powershell
python src/check_llm_connection.py --live
```

Pruebas:

```powershell
python -m pytest
```

## Estructura

```text
voz_llm_plc_agent/
|-- config/
|-- data/
|   `-- plc_maps/
|-- docs/
|-- experimental_results/
|-- generated_code/
|-- knowledge_base/
|-- prompts/
|-- schemas/
|-- src/
|   |-- platforms/
|   |-- plc_maps/
|   |-- alias_resolver.py
|   |-- llm_client.py
|   |-- llm_parser.py
|   |-- semantic_validator.py
|   |-- speech_recognizer.py
|   `-- ...
|-- tests/
|-- CHANGELOG_TESIS.md
`-- README.md
```

## Mapa Maestro PLC

El antiguo `config/io_map.json` evoluciono a una biblioteca de mapas PLC versionados en `data/plc_maps/` (no se versiona en git; se regenera automaticamente desde `config/io_map.json` en el primer arranque). Cada mapa puede tener metadata (nombre, version, plataforma, estado de sincronizacion) y cada variable puede llevar aliases en lenguaje natural, rol semantico, permiso de uso por LLM y nivel de seguridad. La GUI permite crear, cargar, guardar como, eliminar y cambiar de mapa activo, validar el mapa, y sincronizar/importar tags con TIA Portal. Detalle completo en `docs/18_mapa_maestro_plc.md`.

## Donde se guardan los paquetes PLC

- `generated_code/CODESYS/active/<timestamp>_<CASE>_<INTENT>/`
- `generated_code/OPENPLC/active/<timestamp>_<CASE>_<INTENT>/`
- `generated_code/SIEMENS/active/<timestamp>_<CASE>_<INTENT>/`

Dentro de cada paquete se guardan:

- `implementation.st`: POU principal generado
- `declarations.st`: declaraciones del POU
- `full_program.st`: programa ST completo
- `pou_manifest.json`: metadata del POU
- `project_manifest.json`: metadata del paquete

## Limites actuales

- la GUI solo permite generar paquetes `SIEMENS_SCL_V18`; OpenPLC y CODESYS estan aislados de la interfaz (ver "Enfoque actual" arriba) pero siguen disponibles por codigo/consola;
- la compilacion y simulacion automaticas de OpenPLC (MatIEC/GCC) siguen funcionando cuando se invocan directamente, pero no se disparan desde la GUI;
- no despliega a OpenPLC Runtime ni a hardware sin aprobacion humana;
- TIA Openness importa, genera y compila bloques, pero no descarga automaticamente a una CPU fisica;
- la ejecucion real de Openness requiere un proyecto `.ap18` con CPU y pertenecer al grupo local `Siemens TIA Openness`;
- la evidencia de voz y la transcripcion dependen de configuracion local;
- el conocimiento RAG es local y simple por palabras clave.

## Proximos pasos

- ampliar pruebas experimentales C4 y C5 con audio real y ruido;
- ampliar catalogo de intenciones y plantillas aprobadas;
- validar el banco formal tambien mediante compilacion TIA Portal V18;
- evaluar como trabajo adicional una descarga controlada a hardware con una barrera de aprobacion independiente;
- comparar condiciones experimentales manual, reglas, LLM e hibrido;
- reintegrar OpenPLC (incluyendo carga controlada a OpenPLC Runtime) y compilacion automatizada de CODESYS a la GUI cuando el enfoque de tesis lo requiera.
