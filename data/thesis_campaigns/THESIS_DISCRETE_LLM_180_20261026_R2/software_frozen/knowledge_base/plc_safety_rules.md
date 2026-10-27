# Reglas de seguridad PLC

- `I_Emergency` tiene prioridad absoluta sobre salidas críticas.
- `I_Stop` tiene prioridad sobre `I_Start`.
- Al liberar emergencia no debe existir autoarranque.
- No deben activarse `Q_Contactor_A` y `Q_Contactor_B` al mismo tiempo.
- Ningún tag fuera del mapa I/O puede entrar al flujo válido.
