PROGRAM PLC_PRG
        VAR
    I_Sensor1 : BOOL;
    I_Emergency : BOOL;

    Q_Aux_Output : BOOL;
END_VAR

        (* Código generado *)
        (* Salida directa con inhibición por emergencia *)
Q_Aux_Output := I_Sensor1 AND NOT I_Emergency;
