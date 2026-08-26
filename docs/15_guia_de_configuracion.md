# 15 Guia de Configuracion

## Variables de entorno

Definir en `.env`:

- `OPENAI_API_KEY`
- `PLC_LLM_MODEL`
- `PLC_TRANSCRIPTION_MODEL`
- `PARSER_MODE`
- `LLM_CONFIDENCE_THRESHOLD`
- `ENABLE_LLM`
- `ENABLE_VOICE`

## Archivo de configuracion

`config/llm_config.json` controla:

- proveedor;
- parser por defecto;
- variables de entorno para modelos;
- umbral de confianza;
- timeout;
- reintentos;
- fallback a reglas.

## Recomendacion de uso

- sin API: `PARSER_MODE=rule_based` o `hybrid`
- con API: `PARSER_MODE=hybrid`
- para voz: activar `ENABLE_VOICE=true` y definir `PLC_TRANSCRIPTION_MODEL`

## Privacidad

- la API key no se guarda en logs;
- la evidencia de voz solo se conserva si el usuario la activa;
- la generacion final sigue siendo local y deterministica.

## TIA Portal Openness V18

La integracion usa `config/tia_openness_config.json` y la API instalada en `C:/Program Files/Siemens/Automation/Portal V18/PublicAPI/V18/Siemens.Engineering.dll`.

Antes del primer uso, abrir PowerShell como administrador y ejecutar:

```powershell
net localgroup "Siemens TIA Openness" "$env:USERDOMAIN\$env:USERNAME" /add
```

Luego se debe cerrar la sesion de Windows e iniciarla nuevamente. Desde la GUI:

1. seleccionar `Configurar TIA V18` y elegir un proyecto `.ap18` que contenga una CPU;
2. seleccionar `Diagnosticar Openness`;
3. generar un paquete con `Siemens TIA V18` o `Siemens + OpenPLC`;
4. seleccionar `Importar y compilar ultimo paquete Siemens` y confirmar.

La integracion no ejecuta descarga fisica al PLC.
