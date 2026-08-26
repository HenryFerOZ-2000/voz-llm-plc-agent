PROGRAM PLC_PRG
VAR
    I_Mode_Manual : BOOL;
    I_Mode_Auto : BOOL;
    I_Start : BOOL;
    I_Emergency : BOOL;

    Q_Motor_Enable : BOOL;

    M_ManualMode : BOOL;
    M_AutoMode : BOOL;
END_VAR

(* Código generado *)
(* Selección de modos manual y automático *)
M_ManualMode := I_Mode_Manual AND NOT I_Mode_Auto;
M_AutoMode := I_Mode_Auto AND NOT I_Mode_Manual;

(* Habilitación simple de motor por modo *)
Q_Motor_Enable := (I_Start AND M_ManualMode) OR (I_Start AND M_AutoMode AND NOT I_Emergency);
