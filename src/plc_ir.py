from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class PLCVariable:
    name: str
    data_type: str
    var_class: str
    location: str | None
    initial_value: str | None
    description: str
    source: str
    is_standard_block: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PLCFunctionBlockInstance:
    instance_name: str
    block_type: str
    parameters: dict[str, Any]
    description: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PLCPOU:
    name: str
    pou_type: str
    language: str
    variables: list[PLCVariable] = field(default_factory=list)
    function_blocks: list[PLCFunctionBlockInstance] = field(default_factory=list)
    implementation_code: str = ""
    comments: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "pou_type": self.pou_type,
            "language": self.language,
            "variables": [variable.to_dict() for variable in self.variables],
            "function_blocks": [block.to_dict() for block in self.function_blocks],
            "implementation_code": self.implementation_code,
            "comments": list(self.comments)
        }


@dataclass
class PLCTask:
    name: str
    interval: str
    priority: int
    pou_name: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PLCPIDLoop:
    loop_id: str
    process_input: str | None
    control_output: str | None
    setpoint: float
    unit: str
    direction: str
    period_ms: int
    start_policy: str
    resources: dict[str, str]
    input_binding: dict
    output_binding: dict
    controller: dict
    overfill_limit: float | None
    symbols: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PLCProjectIR:
    project_name: str
    target_platform: str
    case_id: str
    intent_id: str
    command_text: str
    pou: PLCPOU
    task: PLCTask
    safety_rules: list[str] = field(default_factory=list)
    test_cases: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    pid_loops: list[PLCPIDLoop] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        result = {
            "project_name": self.project_name,
            "target_platform": self.target_platform,
            "case_id": self.case_id,
            "intent_id": self.intent_id,
            "command_text": self.command_text,
            "pou": self.pou.to_dict(),
            "task": self.task.to_dict(),
            "safety_rules": list(self.safety_rules),
            "test_cases": list(self.test_cases),
            "metadata": dict(self.metadata)
        }
        if self.pid_loops:
            result['pid_loops'] = [loop.to_dict() for loop in self.pid_loops]
        return result
