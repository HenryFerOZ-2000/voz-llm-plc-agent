(* Apagado retardado del motor con prioridad de emergencia *)
IF #I_Emergency THEN
    #M_RunLatch := FALSE;
    #M_StopDelayActive := FALSE;
ELSIF #I_Start THEN
    #M_RunLatch := TRUE;
    #M_StopDelayActive := FALSE;
ELSIF #I_Stop AND #M_RunLatch THEN
    #M_StopDelayActive := TRUE;
END_IF;

#T_StopDelay(IN := #M_StopDelayActive AND NOT #I_Emergency, PT := T#10s);

IF #T_StopDelay.Q THEN
    #M_RunLatch := FALSE;
    #M_StopDelayActive := FALSE;
END_IF;

#Q_Motor_Enable := #M_RunLatch AND NOT #I_Emergency;
