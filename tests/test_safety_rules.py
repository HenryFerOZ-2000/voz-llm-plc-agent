from __future__ import annotations

from verifier import verify_code


def test_verifier_rejects_motor_logic_without_emergency(io_map: dict, safety_rules: dict) -> None:
    st_code = """
PROGRAM PLC_PRG
VAR
    I_Start : BOOL;
    I_Stop : BOOL;
    Q_Motor_Enable : BOOL;
END_VAR

(* Invalid motor logic without emergency *)
IF I_Start AND NOT I_Stop THEN
    Q_Motor_Enable := TRUE;
END_IF;
"""
    result = verify_code(st_code, io_map, safety_rules, intent_id="INT_MOTOR_START_STOP")
    assert result["is_valid"] is False
    assert any("I_Emergency" in error for error in result["errors"])
