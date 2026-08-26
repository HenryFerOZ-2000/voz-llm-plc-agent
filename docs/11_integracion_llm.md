# 11 Integracion LLM

## Rol del LLM

El LLM interviene solo en la interpretacion semantica del requerimiento. No genera directamente el codigo final del PLC.

## Componentes

- `src/llm_client.py`
- `src/llm_parser.py`
- `src/llm_context_builder.py`
- `prompts/llm_semantic_parser_prompt.txt`
- `schemas/semantic_output.schema.json`
- `src/schemas.py`

## Flujo

1. Se recibe un comando.
2. Se construye contexto controlado con intenciones, mapa I/O y reglas.
3. Se solicita salida estructurada.
4. La respuesta pasa por validacion Pydantic.
5. Luego pasa por validacion semantica local.
6. Solo despues puede construirse la IR.

## Seguridad

- No se exponen claves en logs.
- No se permite inventar tags.
- No se permite saltar el mapa I/O.
- El LLM no escribe archivos ST validos por si mismo.
