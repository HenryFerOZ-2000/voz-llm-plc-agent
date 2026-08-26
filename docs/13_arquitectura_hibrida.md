# 13 Arquitectura Hibrida

## Modos

- `RULE_BASED`
- `LLM`
- `HYBRID`

## Logica de decision

`HYBRID` ejecuta primero reglas. Si la confianza es suficiente y no hay ambiguedad, acepta el resultado local. Si no, consulta al LLM.

## Ventajas

- conserva funcionamiento sin API;
- mejora cobertura semantica;
- mantiene explicabilidad;
- permite comparar reglas y LLM en experimentos.

## Regla de seguridad

Si reglas y LLM discrepan de forma critica, el sistema no genera la POU y solicita aclaracion.
