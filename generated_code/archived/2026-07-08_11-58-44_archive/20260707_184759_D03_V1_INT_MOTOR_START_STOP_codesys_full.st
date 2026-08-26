PROGRAM PLC_PRG
        VAR
    I_Start : BOOL;
    I_Stop : BOOL;
    I_Emergency : BOOL;
    I_Reset : BOOL;

    Q_Motor_Enable : BOOL;
    Q_Alarm : BOOL;
    Q_Pilot_Run : BOOL;
    Q_Pilot_Fault : BOOL;

    M_RunLatch : BOOL;
    M_FaultLatch : BOOL;
END_VAR

        (* Código generado *)
        (* Control Start/Stop de motor con prioridad de emergencia *)
IF I_Emergency THEN
    M_RunLatch := FALSE;
    M_FaultLatch := TRUE;
ELSIF I_Stop THEN
    M_RunLatch := FALSE;
ELSIF I_Start AND NOT M_FaultLatch THEN
    M_RunLatch := TRUE;
END_IF;

(* Reset manual de falla *)
IF I_Reset AND NOT I_Emergency THEN
    M_FaultLatch := FALSE;
END_IF;

Q_Motor_Enable := M_RunLatch AND NOT I_Emergency AND NOT M_FaultLatch;
Q_Alarm := M_FaultLatch;
Q_Pilot_Run := Q_Motor_Enable;
Q_Pilot_Fault := M_FaultLatch;
