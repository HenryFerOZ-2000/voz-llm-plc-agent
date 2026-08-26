PROGRAM PLC_PRG
VAR
    I_Start : BOOL;
    I_Stop : BOOL;
    I_Emergency : BOOL;

    Q_Motor_Enable : BOOL;
    Q_Pilot_Run : BOOL;
    Q_Pilot_Fault : BOOL;

    T_DelayStart : TON;
END_VAR

(* Código generado *)
(* Arranque retardado de motor *)
T_DelayStart(IN := I_Start AND NOT I_Stop AND NOT I_Emergency, PT := T#10s);
Q_Motor_Enable := T_DelayStart.Q AND NOT I_Stop AND NOT I_Emergency;
Q_Pilot_Run := Q_Motor_Enable;
Q_Pilot_Fault := I_Emergency;
