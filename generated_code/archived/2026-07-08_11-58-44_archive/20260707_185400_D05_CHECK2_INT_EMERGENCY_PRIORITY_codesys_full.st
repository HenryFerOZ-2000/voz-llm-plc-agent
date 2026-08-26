PROGRAM PLC_PRG
VAR
    I_Emergency : BOOL;

    Q_Motor_Enable : BOOL;
    Q_Aux_Output : BOOL;
    Q_Alarm : BOOL;
    Q_Pilot_Fault : BOOL;
    Q_Contactor_A : BOOL;
    Q_Contactor_B : BOOL;
END_VAR

(* Código generado *)
(* Paro de emergencia con apagado de salidas críticas *)
IF I_Emergency THEN
    Q_Motor_Enable := FALSE;
    Q_Aux_Output := FALSE;
    Q_Contactor_A := FALSE;
    Q_Contactor_B := FALSE;
    Q_Alarm := TRUE;
    Q_Pilot_Fault := TRUE;
ELSE
    Q_Alarm := FALSE;
    Q_Pilot_Fault := FALSE;
END_IF;
