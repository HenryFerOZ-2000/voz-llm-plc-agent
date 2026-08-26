# 08 Decisiones Tecnicas

## El mapa I/O es la fuente de verdad

Se mantiene `config/io_map.json` como fuente unica de verdad para las variables PLC. Esto evita que el parser, la IR, el generador o el verificador inventen tags fuera del dominio autorizado.

## Se genera una POU y un paquete de proyecto, no solo fragmentos ST

Se decidio evolucionar el MVP desde artefactos ST sueltos hacia paquetes de proyecto PLC. La razon principal es que OpenPLC y CODESYS trabajan con:

- declaraciones,
- implementacion,
- tarea,
- recursos,
- manifiestos,
- pruebas y metadata.

Por lo tanto, para una tesis de arquitectura, era mas defendible generar una unidad de proyecto coherente que solo un bloque de codigo aislado.

## Se usa una representacion intermedia independiente de la plataforma

La capa `PLCProjectIR` desacopla:

- la interpretacion semantica del usuario,
- la logica de automatizacion,
- la sintaxis concreta de OpenPLC y CODESYS.

Esta decision mejora:

- portabilidad,
- trazabilidad,
- reutilizacion de reglas de seguridad,
- posibilidad futura de integrar mas plataformas IEC 61131-3.

## El LLM se limita a la interpretacion semantica

Se decide que el LLM futuro intervenga unicamente en la fase:

- comando natural -> JSON semantico estructurado

No se permite que el LLM genere directamente el codigo PLC final sin validacion posterior. Esta decision mantiene:

- seguridad,
- trazabilidad,
- control sobre variables autorizadas,
- verificabilidad academica del sistema.

## Se adopta salida estructurada y validacion estricta

La integracion final usa:

- esquema JSON versionado en `schemas/semantic_output.schema.json`,
- validacion Pydantic en `src/schemas.py`,
- validacion semantica de negocio en `src/semantic_validator.py`.

Esto evita aceptar silenciosamente respuestas incompletas o inventadas por el modelo.

## Se adopta un parser hibrido en lugar de depender solo del LLM

La arquitectura final distingue:

- `RULE_BASED`
- `LLM`
- `HYBRID`

`HYBRID` permite:

- resolver localmente los casos claros,
- consultar LLM cuando la confianza es baja,
- comparar ambas interpretaciones,
- pedir aclaracion cuando existe conflicto critico.

La ventaja academica es que el LLM se usa como apoyo interpretable y no como caja negra unica.

## La voz es una entrada auxiliar, no una orden ciega

Se decide que la voz nunca dispare generacion directa. El flujo correcto es:

1. capturar audio,
2. transcribir,
3. mostrar el texto,
4. permitir edicion,
5. procesar,
6. confirmar generacion.

Esto conserva control humano y trazabilidad.

## Se usa una base de conocimiento local simple

Se incorpora `knowledge_base/` y `src/knowledge_retriever.py` con recuperacion por palabras clave.

No se entrena un modelo propio ni se introduce una base vectorial compleja en esta etapa. La razon es mantener:

- transparencia,
- facilidad de defensa en tesis,
- bajo acoplamiento,
- reproducibilidad local.

## OpenPLC es la plataforma principal de simulacion inicial

Se prioriza OpenPLC para la fase temprana de validacion porque:

- facilita pruebas practicas,
- acepta Structured Text legible,
- permite mapear entradas y salidas con `AT`,
- es apropiado para demostracion experimental del MVP.

La validacion OpenPLC se automatiza en dos etapas:

1. MatIEC o STruC++ comprueba la sintaxis y genera los artefactos de compilacion.
2. Cuando se usa MatIEC y existe GCC, un arnes ejecuta `test_cases.json` sobre el C generado.

Esta segunda etapa es una simulacion funcional de software. No se presenta como despliegue en OpenPLC Runtime ni como validacion de hardware.

## CODESYS se mantiene como plataforma de portabilidad

CODESYS se conserva como segunda plataforma porque:

- es ampliamente conocida en formacion y simulacion IEC 61131-3,
- permite preparar una futura automatizacion con CODESYS Scripting,
- ayuda a demostrar que la arquitectura no depende de un solo entorno.

## Siemens Openness se integra en paralelo

Se adopta `SIEMENS_SCL_V18` como salida principal junto con OpenPLC, sin eliminar los adaptadores existentes. La interpretacion y la IR siguen siendo independientes de la plataforma; un adaptador deterministico genera SCL y un puente C# usa la API oficial instalada de TIA Portal Openness V18.

La importacion y compilacion son acciones separadas de la generacion. Requieren confirmacion explicita, conservan un reporte JSON y no incluyen descarga fisica al PLC. Esta separacion reduce riesgo y permite comparar compilabilidad entre plataformas dentro del protocolo experimental.

## La carga fisica a PLC requiere aprobacion humana

Se ratifica que el sistema:

- no carga automaticamente a un PLC fisico,
- no ejecuta control de campo sin validacion humana,
- no reemplaza la ingenieria de seguridad industrial.

La aprobacion humana se mantiene como barrera obligatoria antes de una puesta en servicio real.

## Un fallback seguro no es una solucion funcional

Se mantiene la decision de rechazar fallbacks como:

```iecst
Q_Aux_Output := FALSE;
```

Aunque sean seguros, no representan la intencion solicitada. Por eso:

- `generate_implementation_from_ir(...)` debe lanzar error controlado si no hay plantilla,
- `verify_project_ir(...)` debe marcar el resultado como no valido,
- el paquete se conserva solo como evidencia de fallo o cobertura incompleta.

## Verificacion en dos niveles

Se decidió validar dos cosas distintas:

1. La coherencia de la representacion intermedia.
2. La integridad del paquete generado.

Esto permite separar:

- errores conceptuales de modelado,
- errores de generacion de archivos,
- errores de trazabilidad documental.

## Separacion entre codigos activos, logs y archivos archivados

Se decidio separar:

- paquetes activos,
- logs JSON,
- ensayos archivados.

Motivo:

- mantener trazabilidad experimental,
- evitar mezcla entre pruebas nuevas y antiguas,
- simplificar la recuperacion de evidencias durante la tesis.

## Se prioriza archivar en lugar de borrar

Se prioriza archivar antes que borrar para conservar evidencia de pruebas y decisiones experimentales. La limpieza sigue existiendo, pero solo con confirmacion explicita y sin afectar `archived/`.

## OpenPLC y CODESYS se aislan temporalmente de la GUI

Se decide concentrar la fase actual del proyecto en `SIEMENS_SCL_V18` mediante TIA Portal Openness V18, que es la integracion mas avanzada y la que mejor demuestra el flujo completo (importacion, generacion de bloques, compilacion con confirmacion humana).

El aislamiento es exclusivamente de interfaz:

- el selector de plataforma en `src/gui.py` queda fijo en "Siemens TIA V18" (`CTkOptionMenu` con un solo valor y `state="disabled"`);
- las pestanas "Proyecto OpenPLC" y "Proyecto CODESYS" de la ventana de resultados se quitan de `self.result_tab_names`, por lo que no se agregan al `CTkTabview` ni aparecen en la navegacion paginada; sus textboxes (`self.openplc_textbox`, `self.codesys_textbox`) se siguen creando, pero sobre un contenedor `CTkFrame` oculto (nunca empaquetado) para no romper el codigo existente que escribe en ellos (snapshots, historial, exportacion);
- `PLATFORM_UI_TO_TARGETS` en `src/gui_helpers.py` conserva intactas las entradas de OpenPLC y CODESYS;
- los adaptadores (`src/platforms/openplc_adapter.py`, `src/platforms/codesys_adapter.py`), el validador (`src/openplc_validator.py`) y sus pruebas (`tests/test_openplc_*.py`, `tests/test_codesys_adapter.py`, `tests/test_cyclic_motor.py`) no se modifican y siguen ejecutandose en la suite;
- `generate_project_package(...)` sigue aceptando `OPENPLC_ST` y `CODESYS_ST` si se invoca directamente (consola o pruebas).

Para reintegrar cualquiera de las dos plataformas a la GUI basta con restaurar la lista de valores del selector en `src/gui.py`, el estado `"normal"`, y devolver "Proyecto OpenPLC"/"Proyecto CODESYS" a `self.result_tab_names`; no hay codigo que reconstruir.
