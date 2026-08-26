(* Arranque y paro de motor con prioridad de Stop y Emergency *)
IF #I_Emergency THEN
    #M_RunLatch := FALSE;
    #M_FaultLatch := TRUE;
ELSIF #I_Stop THEN
    #M_RunLatch := FALSE;
ELSIF #I_Start AND NOT #M_FaultLatch THEN
    #M_RunLatch := TRUE;
END_IF;

(* Reset manual de falla sin autoarranque *)
IF #I_Reset AND NOT #I_Emergency THEN
    #M_FaultLatch := FALSE;
END_IF;

#Q_Motor_Enable := #M_RunLatch AND NOT #I_Stop AND NOT #I_Emergency AND NOT #M_FaultLatch;
#Q_Alarm := #M_FaultLatch;
#Q_Pilot_Run := #Q_Motor_Enable;
#Q_Pilot_Fault := #M_FaultLatch OR #I_Emergency;
