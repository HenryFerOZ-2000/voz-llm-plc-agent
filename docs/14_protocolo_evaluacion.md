# 14 Protocolo de Evaluacion

## Condiciones experimentales

- `C0_MANUAL`
- `C1_LLM_DIRECT`
- `C2_STRUCTURED_RULES`
- `C3_HYBRID`
- `C4_HYBRID_VOICE`
- `C5_HYBRID_VOICE_NOISE`

## Registro

`src/evaluation_runner.py` guarda resultados en:

- `experimental_results/trials.jsonl`
- `experimental_results/trials.csv`

## Metricas

- exactitud de intencion;
- exactitud de slots;
- tasa de exito por comando;
- tasa de validacion semantica;
- tasa de validacion de paquete;
- tasa de compilacion OpenPLC exitosa;
- tasa de simulacion funcional exitosa;
- tasa de validacion completa end-to-end;
- numero de casos funcionales aprobados y fallidos;
- tiempo medio de generacion;
- tasa de fallback;
- tasa de aclaracion;
- acuerdo reglas/LLM;
- tasa de violacion de seguridad.

La compilacion y la simulacion se registran por separado. Una POU solo se considera completamente validada en software cuando supera la verificacion estatica, la compilacion y todos los casos funcionales soportados.
