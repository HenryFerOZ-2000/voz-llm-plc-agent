PROGRAM PLC_PRG
VAR
    I_Start : BOOL;
    I_Stop : BOOL;
    I_Emergency : BOOL;

    Q_Motor_Enable : BOOL;

    M_RunLatch : BOOL;
END_VAR

(* Código generado *)
(* Enclavamiento de motor con prioridad de stop y emergencia *)
IF I_Emergency OR I_Stop THEN
    M_RunLatch := FALSE;
ELSIF I_Start THEN
    M_RunLatch := TRUE;
END_IF;

Q_Motor_Enable := M_RunLatch AND NOT I_Emergency;
