VAR_INPUT
   I_Start : Bool := FALSE;
   I_Stop : Bool := FALSE;
   I_Emergency : Bool := FALSE;
END_VAR
VAR_OUTPUT
   Q_Motor_Enable : Bool := FALSE;
END_VAR
VAR
   M_RunLatch : Bool := FALSE;
   M_StopDelayActive : Bool := FALSE;
   T_StopDelay {InstructionName := 'TON_TIME'; LibVersion := '1.0'} : TON_TIME;
END_VAR
