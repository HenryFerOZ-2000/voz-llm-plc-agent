PROGRAM PLC_PRG
VAR
    I_Reset : BOOL;

    C_PulseCount : CTU;
END_VAR

(* Código generado *)
(* Reinicio explícito del contador *)
C_PulseCount(CU := FALSE, RESET := I_Reset, PV := 0);
