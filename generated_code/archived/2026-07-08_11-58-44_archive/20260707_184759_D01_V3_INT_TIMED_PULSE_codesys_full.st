PROGRAM PLC_PRG
        VAR
    I_Start : BOOL;
    I_Emergency : BOOL;

    Q_Aux_Output : BOOL;

    T_Pulse5s : TP;
END_VAR

        (* Código generado *)
        (* Pulso temporizado con protección por emergencia *)
T_Pulse5s(IN := I_Start AND NOT I_Emergency, PT := T#10s);
Q_Aux_Output := T_Pulse5s.Q AND NOT I_Emergency;
