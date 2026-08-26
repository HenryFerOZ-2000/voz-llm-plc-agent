VAR_INPUT
   I_Start : Bool := FALSE;
   I_Stop : Bool := FALSE;
   I_Emergency : Bool := FALSE;
   I_Reset : Bool := FALSE;
END_VAR
VAR_OUTPUT
   Q_Motor_Enable : Bool := FALSE;
   Q_Alarm : Bool := FALSE;
   Q_Pilot_Run : Bool := FALSE;
   Q_Pilot_Fault : Bool := FALSE;
END_VAR
VAR
   M_RunLatch : Bool := FALSE;
   M_FaultLatch : Bool := FALSE;
END_VAR
