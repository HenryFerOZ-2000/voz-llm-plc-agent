PROGRAM PLC_PRG
        VAR
    I_Start : BOOL;
    I_Stop : BOOL;
    I_Emergency : BOOL;

    Q_Contactor_A : BOOL;
    Q_Contactor_B : BOOL;
END_VAR

        (* Código generado *)
        (* Enclavamiento mutuo entre contactores A y B *)
IF I_Emergency THEN
    Q_Contactor_A := FALSE;
    Q_Contactor_B := FALSE;
ELSE
    Q_Contactor_A := I_Start AND NOT Q_Contactor_B;
    Q_Contactor_B := I_Stop AND NOT Q_Contactor_A;
END_IF;
