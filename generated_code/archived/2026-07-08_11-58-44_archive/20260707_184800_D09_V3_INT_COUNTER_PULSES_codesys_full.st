PROGRAM PLC_PRG
        VAR
    I_Sensor1 : BOOL;
    I_Reset : BOOL;
    I_Emergency : BOOL;

    Q_Aux_Output : BOOL;

    C_PulseCount : CTU;

    R_SensorPulse : R_TRIG;
END_VAR

        (* Código generado *)
        (* Conteo de pulsos con reinicio por reset o emergencia *)
R_SensorPulse(CLK := I_Sensor1);
C_PulseCount(CU := R_SensorPulse.Q, RESET := I_Reset OR I_Emergency, PV := 5);
Q_Aux_Output := C_PulseCount.Q AND NOT I_Emergency;
