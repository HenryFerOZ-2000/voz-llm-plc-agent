PROGRAM PLC_PRG
        VAR
    I_Emergency : BOOL;

    Q_Motor_Enable : BOOL;
    Q_Alarm : BOOL;
    Q_Pilot_Run : BOOL;
    Q_Pilot_Fault : BOOL;
END_VAR

        (* Código generado *)
        (* Señalización de pilotos de marcha y falla *)
Q_Pilot_Run := Q_Motor_Enable AND NOT I_Emergency;
Q_Pilot_Fault := Q_Alarm OR I_Emergency;
