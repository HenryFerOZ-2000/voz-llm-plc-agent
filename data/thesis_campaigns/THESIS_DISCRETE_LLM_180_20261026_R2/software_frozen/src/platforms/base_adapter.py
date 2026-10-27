from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from plc_ir import PLCProjectIR, PLCVariable


class PLCPlatformAdapter(ABC):
    platform_name = "GENERIC"
    resource_name = "Res0"

    @abstractmethod
    def render_declarations(self, project_ir: PLCProjectIR) -> str:
        pass

    @abstractmethod
    def render_implementation(self, project_ir: PLCProjectIR) -> str:
        pass

    @abstractmethod
    def render_full_program(self, project_ir: PLCProjectIR) -> str:
        pass

    @abstractmethod
    def render_variables_table(self, project_ir: PLCProjectIR) -> list[dict[str, Any]]:
        pass

    @abstractmethod
    def render_project_manifest(self, project_ir: PLCProjectIR) -> dict[str, Any]:
        pass

    @abstractmethod
    def render_task_configuration(self, project_ir: PLCProjectIR) -> dict[str, Any]:
        pass

    @abstractmethod
    def render_test_cases(self, project_ir: PLCProjectIR) -> list[dict[str, Any]]:
        pass

    def render_extra_artifacts(self, project_ir: PLCProjectIR) -> dict[str, Any]:
        """Return optional platform-specific files for the generated package."""
        return {}

    def render_pou_manifest(self, project_ir: PLCProjectIR) -> dict[str, Any]:
        return {
            "name": project_ir.pou.name,
            "type": project_ir.pou.pou_type,
            "language": project_ir.pou.language,
            "variables": [variable.to_dict() for variable in project_ir.pou.variables],
            "function_blocks": [block.to_dict() for block in project_ir.pou.function_blocks],
            "implementation_file": "implementation.st",
            "declarations_file": "declarations.st",
            "full_program_file": "full_program.st",
            "task_binding": "MainTask",
            "generation_status": "GENERATED",
            "compilation_status": "COMPILATION_NOT_EXECUTED",
            "simulation_status": "SIMULATION_NOT_EXECUTED",
            "physical_deployment_status": "HARDWARE_DEPLOYMENT_NOT_EXECUTED"
        }

    def _variable_to_row(self, variable: PLCVariable) -> dict[str, Any]:
        return {
            "name": variable.name,
            "type": variable.data_type,
            "class": variable.var_class,
            "location": variable.location or "",
            "initial_value": variable.initial_value or "",
            "description": variable.description,
            "source": variable.source,
            "is_standard_block": variable.is_standard_block
        }

    def _project_manifest_base(self, project_ir: PLCProjectIR) -> dict[str, Any]:
        return {
            "platform": self.platform_name,
            "project_name": project_ir.project_name,
            "pou_name": project_ir.pou.name,
            "pou_type": project_ir.pou.pou_type,
            "language": project_ir.pou.language,
            "resource_name": self.resource_name,
            "task_name": project_ir.task.name,
            "task_interval": project_ir.task.interval,
            "task_priority": project_ir.task.priority,
            "generated_files": [
                "full_program.st",
                "declarations.st",
                "implementation.st",
                "variables.json",
                "project_manifest.json",
                "pou_manifest.json",
                "task_config.json",
                "test_cases.json",
                "semantic_input.json",
                "semantic_validation.json",
                "generation_metadata.json",
                "retrieved_context.json",
                "verification.json"
            ],
            "case_id": project_ir.case_id,
            "intent_id": project_ir.intent_id,
            "generation_status": "GENERATED",
            "semantic_status": "SEMANTIC_VALIDATED",
            "verification_status": "STATICALLY_VERIFIED",
            "compilation_status": "COMPILATION_NOT_EXECUTED",
            "simulation_status": "SIMULATION_NOT_EXECUTED",
            "physical_deployment_status": "HARDWARE_DEPLOYMENT_NOT_EXECUTED",
            "automatic_deployment_policy": "NOT_ALLOWED_AUTOMATICALLY"
        }
