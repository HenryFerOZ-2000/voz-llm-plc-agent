"""
Fase 4A.0: diseno experimental formal v2, separacion DEVELOPMENT/FORMAL, taxonomia de fallos,
batch runner del baseline (reanudable, sin duplicados, solo PLCSIM) y guard anti-overfitting.

Nada de esto ejecuta TIA/PLCSIM reales: el batch se prueba con un driver simulado sobre una
COPIA temporal de data/ y config/ (los archivos reales se verifican intactos al final).
"""
from __future__ import annotations

import csv
import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest

from trial_experiments import batch_runner as B
from trial_experiments import benchmark_catalog as BC
from trial_experiments import experimental_design as ED
from trial_experiments import oracle_schema as S
from trial_experiments import trial_model

_ROOT = Path(__file__).resolve().parents[1]
_INTEGRITY_BEFORE = B.integrity_snapshot(_ROOT)


# ---------- diseno ----------

def test_design_has_three_input_modes_and_no_parser_factor():
    design = ED.load_design(_ROOT)
    assert ED.formal_input_modes(_ROOT) == ["TEXT", "VOICE_CLEAN", "VOICE_NOISE"]
    assert design["factors"] == ["DOMAIN", "COMPLEXITY", "VARIANT", "INPUT_MODE", "CASE"]
    assert not {"PARSER_MODE", "RULES", "LLM", "HYBRID"} & {factor.upper() for factor in design["factors"]}
    assert design["legacy_conditions"]["status"] == "DEPRECATED"
    assert design["manual_baseline"] == {**design["manual_baseline"], "enabled": True, "included_in_factorial": False}
    assert design["architecture"]["target_type"] == "PLCSIM_ADVANCED" and design["architecture"]["physical_download"] == "forbidden"


def test_formal_design_count_is_288_with_nine_trials_per_case():
    matrix = ED.formal_design_matrix(_ROOT)
    assert len(matrix) == ED.load_design(_ROOT)["formal_trial_count"] == 288
    assert ED.validate_formal_matrix(matrix) == []
    per_case: dict[str, int] = {}
    for cell in matrix:
        per_case[cell["case_id"]] = per_case.get(cell["case_id"], 0) + 1
        assert cell["trial_kind"] == "FORMAL_TRIAL" and "parser_mode" not in cell
    assert len(per_case) == 32 and set(per_case.values()) == {9}
    assert {c["domain"] for c in matrix} == {"DISCRETE", "PID_SUPERVISOR"}
    assert {c["complexity"] for c in matrix} <= {"LOW", "MEDIUM", "HIGH"}


def test_baseline_is_60_discrete_text_development_trials():
    matrix = ED.baseline_matrix(_ROOT)
    assert len(matrix) == 60
    assert {c["case_id"] for c in matrix} == {f"D{i:02d}" for i in range(1, 21)}
    assert {c["variant"] for c in matrix} == {"V1", "V2", "V3"}
    assert {c["input_mode"] for c in matrix} == {"TEXT"}
    assert {(c["trial_kind"], c["experiment_phase"]) for c in matrix} == {("DEVELOPMENT_TRIAL", "BASELINE")}
    assert not any(c["case_id"].startswith("P") for c in matrix)  # PID fuera del baseline


def test_trial_ids_never_include_parser_mode_and_mark_development():
    assert trial_model.build_trial_id("D01", "V1", "TEXT", 1, development=True) == "D01_V1_TEXT_DEV_001"
    assert trial_model.build_trial_id("D01", "V1", "TEXT", 1) == "D01_V1_TEXT_001"
    for bad in ("RULES", "HYBRID", "LLM"):
        with pytest.raises(ValueError):
            trial_model.build_trial_id("D01", "V1", bad, 1)
    record = trial_model.new_trial_record("D01", "V1", "TEXT", 1, phase=trial_model.PHASE_BASELINE)
    assert record["trial_id"] == "D01_V1_TEXT_DEV_001"
    assert record["trial_kind"] == "DEVELOPMENT_TRIAL" and record["experiment_phase"] == "BASELINE"
    assert not re.search(r"RULES|HYBRID|LLM", record["trial_id"])


def test_trial_record_has_v2_metadata_fields():
    record = trial_model.new_trial_record("D07", "V2", "VOICE_NOISE", 3, phase=trial_model.PHASE_DEVELOPMENT)
    for key in ("trial_kind", "experiment_phase", "domain", "complexity", "input_mode", "benchmark_version",
                "canonical_case_hash", "variant_hash", "oracle_reference", "command_text", "reference_command_text",
                "semantic", "generated_code_id", "functional", "safety", "final_verdict", "failure_category",
                "infrastructure_error", "model", "asr", "git_commit", "attempt", "retry_reason", "clarification_requested"):
        assert key in record, key
    assert set(record["timing"]) >= {"semantic_ms", "generation_ms", "compile_ms", "download_ms", "runtime_ms", "oracle_ms", "total_ms"}
    assert set(record["asr"]) == {"audio_reference", "asr_transcript", "wer", "noise_profile", "snr_db"}
    assert set(record["oracle_reference"]) == {"oracle_id", "oracle_version", "oracle_hash"}


def test_development_and_formal_results_never_share_a_directory(tmp_path):
    dev = trial_model.trial_directory(tmp_path, "D01", "V1", "D01_V1_TEXT_DEV_001", trial_model.PHASE_BASELINE)
    formal = trial_model.trial_directory(tmp_path, "D01", "V1", "D01_V1_TEXT_001", trial_model.PHASE_FORMAL)
    assert "development_baseline_v2" in dev.parts and "experiments" in formal.parts
    dev.mkdir(parents=True)
    assert trial_model.next_trial_number(tmp_path, "D01", "V1", "TEXT", trial_model.PHASE_BASELINE) == 2
    assert trial_model.next_trial_number(tmp_path, "D01", "V1", "TEXT", trial_model.PHASE_FORMAL) == 1


# ---------- separacion DEVELOPMENT / FORMAL ----------

def test_development_trials_are_excluded_from_formal_statistics():
    records = [
        {"trial_kind": "DEVELOPMENT_TRIAL", "experiment_phase": "BASELINE", "benchmark_version": 2},
        {"trial_kind": "DEVELOPMENT_TRIAL", "experiment_phase": "DEVELOPMENT_VALIDATION", "benchmark_version": 2},
        {"trial_kind": "FORMAL_TRIAL", "experiment_phase": "FORMAL", "benchmark_version": 1},
        {"trial_kind": "FORMAL_TRIAL", "experiment_phase": "FORMAL", "benchmark_version": 2},  # v2: historico DEVELOPMENT
        {"trial_kind": "FORMAL_TRIAL", "experiment_phase": "FORMAL", "benchmark_version": 3},
    ]
    assert ED.FORMAL_BENCHMARK_VERSION == 3
    assert ED.formal_statistics_records(records) == [records[4]]


def test_formal_trial_requires_software_freeze_manifest(tmp_path):
    root = _project_copy(tmp_path)
    allowed, reasons = ED.check_formal_trial_allowed(root)
    assert not allowed and "FORMAL_TRIAL_NOT_ALLOWED" in reasons[0]
    assert not (_ROOT / "data" / "software_freeze_manifest.json").exists()  # no se activa en esta fase
    manifest = {"status": "FROZEN", **ED.current_integrity_fingerprint(root)}
    (root / "data" / "software_freeze_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert ED.check_formal_trial_allowed(root) == (True, [])
    manifest["oracles"]["D05"]["hash"] = "0" * 64  # un hash que no coincide invalida la congelacion
    (root / "data" / "software_freeze_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    allowed, reasons = ED.check_formal_trial_allowed(root)
    assert not allowed and any("D05" in reason for reason in reasons)


def test_oracle_status_no_longer_decides_trial_kind():
    import inspect
    from trial_experiments import oracle_runner

    assert "trial_kind" not in oracle_runner.trial_patch({"functional": {}, "safety": {}})
    assert "TRIAL_KIND_FORMAL if" not in inspect.getsource(oracle_runner.run_oracle)


# ---------- taxonomia ----------

def _record(final_status: str, **stages: Any) -> dict[str, Any]:
    return {"final_status": final_status, "stages": stages, "errors": []}


def test_infrastructure_errors_are_never_functional_failures():
    for record in (
        _record("INFRASTRUCTURE_ERROR", compile_success=True, download_success=False),
        _record("INFRASTRUCTURE_ERROR", compile_success=True, download_success=True, runtime_connection_success=False),
        _record("INFRASTRUCTURE_ERROR"),
    ):
        result = ED.classify_trial(record)
        assert result["infrastructure_error"] is True and result["system_failure"] is False
        assert result["failure_category"] in ED.INFRASTRUCTURE_CATEGORIES
    assert ED.classify_trial(_record("INFRASTRUCTURE_ERROR", download_success=False))["failure_category"] == "DOWNLOAD_FAILURE"


def test_failure_taxonomy_categories():
    assert ED.classify_trial(_record("PASS"))["failure_category"] == "SUCCESS"
    assert ED.classify_trial(_record("REVIEW"))["failure_category"] == "REVIEW"
    assert ED.classify_trial(_record("FAIL", semantic_success=False))["failure_category"] == "SEMANTIC_FAILURE"
    assert ED.classify_trial(_record("FAIL", semantic_success=True, verification_success=False))["failure_category"] == "VERIFICATION_FAILURE"
    assert ED.classify_trial(_record("FAIL", semantic_success=True, verification_success=True, compile_success=False))["failure_category"] == "COMPILE_FAILURE"
    assert ED.classify_trial(_record("FAIL", compile_success=True, functional_success=False, safety_success=True))["failure_category"] == "FUNCTIONAL_FAILURE"
    assert ED.classify_trial(_record("FAIL", compile_success=True, functional_success=True, safety_success=False))["failure_category"] == "SAFETY_FAILURE"
    assert ED.classify_trial({**_record("FAIL"), "failure_stage": "generate"})["failure_category"] == "CODEGEN_FAILURE"
    assert ED.classify_trial({**_record("FAIL", semantic_success=True), "io_map": {"error": "EXPERIMENT_IO_X"}})["failure_category"] == "IO_ALLOCATION_FAILURE"
    taxonomy = set(ED.load_design(_ROOT)["failure_taxonomy"])
    assert taxonomy == {"SUCCESS", "SEMANTIC_FAILURE", "IO_ALLOCATION_FAILURE", "IR_FAILURE", "CODEGEN_FAILURE",
                        "VERIFICATION_FAILURE", "COMPILE_FAILURE", "DOWNLOAD_FAILURE", "RUNTIME_FAILURE",
                        "FUNCTIONAL_FAILURE", "SAFETY_FAILURE", "INFRASTRUCTURE_ERROR", "REVIEW", "ASR_FAILURE"}


# ---------- batch runner (driver simulado sobre copia temporal) ----------

def _project_copy(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    for relative in ("data/experiment_oracles", "data/experiment_cases", "data/plc_maps", "config"):
        shutil.copytree(_ROOT / relative, root / relative)
    for relative in ("data/experimental_design.json", "data/system_capability_gaps.json"):
        shutil.copyfile(_ROOT / relative, root / relative)
    (root / "config" / "tia_projects.json").unlink(missing_ok=True)  # sin la seleccion TIA real del usuario
    from test_phase4a_deferred_evaluation import _freeze_oracles_for_tests

    _freeze_oracles_for_tests(root)  # Oracles FROZEN solo en la copia (en el repositorio: aprobacion humana pendiente)
    return root


class _FakeDriver:
    """Sustituye al pipeline real: escribe trial.json con el resultado guionizado."""

    def __init__(self, root: Path, outcomes: dict[str, list[str]]) -> None:
        self.root = root
        self.outcomes = outcomes
        self.calls: list[str] = []

    def run(self, case_id: str, variant: str):
        key = f"{case_id}_{variant}"
        self.calls.append(key)
        status = (self.outcomes.get(key) or ["PASS"]).pop(0) if self.outcomes.get(key) else "PASS"
        phase = trial_model.PHASE_BASELINE
        number = trial_model.next_trial_number(self.root, case_id, variant, "TEXT", phase)
        record = trial_model.new_trial_record(case_id, variant, "TEXT", number, complexity="LOW", phase=phase)
        directory = trial_model.trial_directory(self.root, case_id, variant, record["trial_id"], phase)
        record["stages"].update({"semantic_success": True, "verification_success": True, "compile_success": True})
        if status == "INFRASTRUCTURE_ERROR":
            record["stages"]["download_success"] = False
        elif status == "FAIL":
            record["stages"].update({"download_success": True, "functional_success": False, "safety_success": True})
        else:
            record["stages"].update({"download_success": True, "functional_success": True, "safety_success": True})
        trial_model.save_trial(directory, record)
        trial_model.finalize_trial(directory, status, None if status == "PASS" else [status])
        return trial_model.load_trial(directory), directory


def test_batch_resumes_without_duplicates_and_continues_after_functional_fail(tmp_path):
    root = _project_copy(tmp_path)
    driver = _FakeDriver(root, {"D01_V1": ["FAIL"]})
    first = B.run_baseline(root, max_trials=5, driver=driver, skip_live_preflight=True, log=lambda _m: None)
    assert first["executed"] == 5 and first["stop_reason"] is None  # el FAIL funcional no detiene el batch
    second = B.run_baseline(root, driver=driver, skip_live_preflight=True, log=lambda _m: None)
    assert second["executed"] == 55 and second["remaining"] == 0
    assert len(driver.calls) == 60 and len(set(driver.calls)) == 60  # reanudable, sin duplicados
    third = B.run_baseline(root, driver=driver, skip_live_preflight=True, log=lambda _m: None)
    assert third["executed"] == 0 and len(driver.calls) == 60  # nada completado se repite
    queue = B.load_queue(root)
    d01 = next(e for e in queue["entries"] if e["entry_id"] == "D01_V1_TEXT")
    assert d01["status"] == B.ENTRY_COMPLETED and len(d01["attempts"]) == 1  # un FAIL funcional nunca se reintenta
    assert B.runnable_entries(queue, retry_infrastructure=True) == []

    out = B.baseline_dir(root)
    for name in (B.TRIALS_CSV, B.SUMMARY_JSON, B.SUMMARY_MD, B.FAILURES_JSON):
        assert (out / name).exists()
    rows = list(csv.DictReader((out / B.TRIALS_CSV).open(encoding="utf-8")))
    assert len(rows) == 60 and {row["trial_kind"] for row in rows} == {"DEVELOPMENT_TRIAL"}
    assert all("_DEV_" in row["trial_id"] for row in rows)
    summary = json.loads((out / B.SUMMARY_JSON).read_text(encoding="utf-8"))
    assert summary["overall"]["pass"] == 59 and set(summary["by_variant"]) == {"V1", "V2", "V3"}
    gaps = json.loads((root / B.GAP_VALIDATION_RELATIVE).read_text(encoding="utf-8"))
    d01_gap = next(c for c in gaps["cases"] if c["case_id"] == "D01")
    assert d01_gap["static_gap_predicted"] is True and d01_gap["status"] == "partially_confirmed"
    assert len(d01_gap["evidence_trial_ids"]) == 3


def test_infrastructure_retry_is_explicit_and_never_overwrites(tmp_path):
    root = _project_copy(tmp_path)
    driver = _FakeDriver(root, {"D02_V1": ["INFRASTRUCTURE_ERROR", "PASS"]})
    B.run_baseline(root, max_trials=4, driver=driver, skip_live_preflight=True, log=lambda _m: None)
    queue = B.load_queue(root)
    entry = next(e for e in queue["entries"] if e["entry_id"] == "D02_V1_TEXT")
    assert entry["status"] == B.ENTRY_INFRASTRUCTURE
    # Sin reintento tecnico explicito, la celda con infraestructura no se repite.
    B.run_baseline(root, max_trials=1, driver=driver, skip_live_preflight=True, log=lambda _m: None)
    assert driver.calls.count("D02_V1") == 1
    with pytest.raises(B.BatchAbort):
        B.run_baseline(root, retry_infrastructure=True, retry_reason=" ", driver=driver, skip_live_preflight=True)
    B.run_baseline(root, max_trials=1, retry_infrastructure=True, retry_reason="PLCSIM reiniciado", driver=driver,
                   skip_live_preflight=True, log=lambda _m: None)
    entry = next(e for e in B.load_queue(root)["entries"] if e["entry_id"] == "D02_V1_TEXT")
    assert [a["attempt"] for a in entry["attempts"]] == [1, 2]
    assert entry["attempts"][1]["retry_reason"] == "PLCSIM reiniciado" and entry["status"] == B.ENTRY_COMPLETED
    first_dir, second_dir = (Path(a["trial_dir"]) for a in entry["attempts"])
    assert first_dir != second_dir and trial_model.load_trial(first_dir)["final_status"] == "INFRASTRUCTURE_ERROR"
    assert trial_model.load_trial(second_dir)["attempt"] == 2


def test_consecutive_infrastructure_errors_stop_the_batch(tmp_path):
    root = _project_copy(tmp_path)
    driver = _FakeDriver(root, {"D01_V1": ["INFRASTRUCTURE_ERROR"], "D01_V2": ["INFRASTRUCTURE_ERROR"]})
    result = B.run_baseline(root, driver=driver, skip_live_preflight=True, log=lambda _m: None)
    assert result["executed"] == 2 and "INFRASTRUCTURE_ERROR" in result["stop_reason"]


# ---------- alcance y seguridad ----------

def test_physical_target_aborts_preflight_and_download(tmp_path):
    root = _project_copy(tmp_path)
    config_path = root / "config" / "tia_openness_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert B.preflight(root, live=False)["ready"] is True
    config["download_targets"]["experiment"]["target_type"] = "PHYSICAL_PLC"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    check = B.preflight(root, live=False)
    assert check["ready"] is False and "target_plcsim_only" in check["failed_checks"]
    with pytest.raises(B.BatchAbort):
        B.run_baseline(root, driver=_FakeDriver(root, {}), skip_live_preflight=True)

    calls: list[Any] = []
    guarded = B.guarded_download(lambda *args: calls.append(args) or {}, root)
    with pytest.raises(B.BatchAbort):
        guarded(tmp_path, root, "experiment")
    assert calls == [] and B.GUARD_VIOLATIONS
    B.GUARD_VIOLATIONS.clear()


def test_guarded_download_rejects_non_experiment_purpose(tmp_path):
    root = _project_copy(tmp_path)
    calls: list[Any] = []
    guarded = B.guarded_download(lambda *args: calls.append(args) or {"ok": True}, root)
    with pytest.raises(B.BatchAbort):
        guarded(tmp_path, root, "normal")
    assert guarded(tmp_path, root, "experiment") == {"ok": True} and len(calls) == 1
    B.GUARD_VIOLATIONS.clear()


def test_live_preflight_aborts_when_environment_is_missing(tmp_path):
    root = _project_copy(tmp_path)
    check = B.preflight(
        root, live=True,
        runtime_status_fn=lambda r: {"status": "PLCSIM_INSTANCE_NOT_FOUND", "connected": False},
        tia_diagnostic_fn=lambda r: {"is_ready": False, "warnings": ["sin TIA"], "project_path": ""},
        llm_health_fn=lambda: {"provider": "openai", "llm_configured": True, "model_configured": True},
        gui_running_fn=lambda: False,
    )
    assert check["ready"] is False
    assert {"tia_openness_ready", "plcsim_instance_connected"} <= set(check["failed_checks"])


def test_pid_cases_stay_out_of_the_baseline_and_require_runtime_extension():
    for case_id in (f"P{i:02d}" for i in range(1, 13)):
        assert S.runtime_support(S.load_oracle(_ROOT, case_id)) != S.RUNTIME_EXECUTABLE_NOW
    assert not any(e["case_id"].startswith("P") for e in B.build_queue(_ROOT)["entries"])


# ---------- anti-overfitting (Parte V) ----------

_CORE_MODULES = (
    "alias_resolver.py", "code_generator.py", "functional_requirements.py", "io_allocator.py", "ir_builder.py",
    "knowledge_retriever.py", "llm_client.py", "llm_context_builder.py", "llm_parser.py", "plc_ir.py",
    "project_packager.py", "schemas.py", "semantic_parser.py", "semantic_repair.py", "semantic_validator.py",
    "verifier.py",
)
_CASE_LITERAL = re.compile(r"""["'](?:D(?:0[1-9]|1\d|20)|P(?:0[1-9]|1[0-2]))(?:_V[1-3])?["']""")
_CASE_CONDITIONAL = re.compile(r"""\b(?:case_id|variant(?:_id)?)\s*(?:==|!=|\bin\b)""")


def _code_lines(path: Path) -> list[tuple[int, str]]:
    lines = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        code = line.split("#", 1)[0]
        if code.strip():
            lines.append((number, code))
    return lines


def test_core_has_no_case_or_variant_specific_logic():
    offenders = []
    modules = [_ROOT / "src" / name for name in _CORE_MODULES] + sorted((_ROOT / "src" / "platforms").rglob("*.py"))
    for path in modules:
        if not path.exists():
            continue
        for number, code in _code_lines(path):
            if _CASE_LITERAL.search(code) or _CASE_CONDITIONAL.search(code):
                offenders.append(f"{path.name}:{number}: {code.strip()}")
    assert offenders == [], "Logica dependiente del caso/variante en el core:\n" + "\n".join(offenders)


def test_llm_context_never_receives_benchmark_or_oracle_information():
    from llm_context_builder import build_llm_context
    from utils import load_json_file

    context = build_llm_context(
        BC.get_case(_ROOT, "D03")["variants"]["V1"],
        load_json_file(_ROOT / "data" / "plc_maps" / "mapa_banco_fisico_base.json"),
        load_json_file(_ROOT / "config" / "intents_catalog.json"),
        load_json_file(_ROOT / "config" / "safety_rules.json"),
    )
    text = json.dumps(context, ensure_ascii=False)
    for forbidden in ("related_cases", "oracle", "benchmark", "expected_output", "canonical_command", "case_id"):
        assert forbidden not in text.lower(), forbidden
    assert not _CASE_LITERAL.search(text)


# ---------- efectos secundarios ----------

def test_protected_files_and_oracles_unchanged_by_this_module():
    assert B.integrity_differences(_INTEGRITY_BEFORE, B.integrity_snapshot(_ROOT)) == []
    assert not (_ROOT / B.GAP_VALIDATION_RELATIVE).exists() or json.loads(
        (_ROOT / B.GAP_VALIDATION_RELATIVE).read_text(encoding="utf-8")).get("cases")


# ---------- GUI (Parte K) ----------

def test_gui_uses_input_mode_and_phase_instead_of_legacy_conditions(app):
    import gui

    assert not hasattr(app, "experiment_condition_selector") and not hasattr(gui, "CONDITIONS")
    assert list(gui.INPUT_MODE_LABELS) == ["TEXT", "VOICE_CLEAN", "VOICE_NOISE"]
    assert app.experiment_input_mode_selector.cget("values") == list(gui.INPUT_MODE_LABELS.values())
    assert app._selected_phase() == trial_model.PHASE_DEVELOPMENT  # por defecto nunca FORMAL
    condition = app._selected_condition()
    assert condition["input_mode"] == "TEXT" and condition["parser_mode"] == "llm" and condition["requires_voice"] is False
    app.experiment_input_mode_var.set(gui.INPUT_MODE_LABELS["VOICE_NOISE"])
    app._on_experiment_input_mode_changed()
    assert app._selected_noise_level() != "none"
    app.experiment_input_mode_var.set(gui.INPUT_MODE_LABELS["TEXT"])
    app._on_experiment_input_mode_changed()
    assert app._selected_noise_level() == "none"


def test_gui_blocks_formal_phase_without_freeze(app, monkeypatch, tmp_path):
    import gui

    warnings: list[str] = []
    monkeypatch.setattr(gui.messagebox, "showwarning", lambda title, message, **k: warnings.append(message))
    monkeypatch.setattr(trial_model, "get_results_experiments_dir", lambda root: tmp_path / "results" / "experiments")
    app.work_mode_var.set("Experimentacion")
    app._on_work_mode_changed()
    app.experiment_phase_var.set(gui.EXPERIMENT_PHASE_LABELS[trial_model.PHASE_FORMAL])
    try:
        assert app.start_trial() is False
        assert warnings and "FORMAL_TRIAL_NOT_ALLOWED" in warnings[-1]
        assert app.active_trial is None and not (tmp_path / "results").exists()
    finally:
        app.experiment_phase_var.set(gui.EXPERIMENT_PHASE_LABELS[trial_model.PHASE_DEVELOPMENT])
        app.work_mode_var.set("Normal")
        app._on_work_mode_changed()


def test_batch_driver_loads_the_exact_canonical_command_in_the_real_gui(app, monkeypatch):
    import gui

    # Los parches del driver se revierten al terminar (monkeypatch guarda los originales).
    for name in ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel"):
        monkeypatch.setattr(gui.messagebox, name, getattr(gui.messagebox, name))
    for name in ("ClarificationDialog", "download_program_to_plc", "append_test_record_to_docs"):
        monkeypatch.setattr(gui, name, getattr(gui, name))
    monkeypatch.setattr(app, "wait_window", app.wait_window, raising=False)
    driver = B.GuiTrialDriver(_ROOT, app=app, log=lambda _m: None)
    try:
        command = driver.configure("D05", "V2")
        assert command == BC.get_case(_ROOT, "D05")["variants"]["V2"]
        assert app._selected_input_mode() == "TEXT" and app._selected_phase() == trial_model.PHASE_BASELINE
        assert gui.messagebox.askyesno("x", "y") is False  # el batch nunca acepta confirmaciones
        assert gui.ClarificationDialog(app, "pregunta").result is None  # nadie responde aclaraciones
    finally:
        app.experiment_phase_var.set(gui.EXPERIMENT_PHASE_LABELS[trial_model.PHASE_DEVELOPMENT])
        app.work_mode_var.set("Normal")
        app._on_work_mode_changed()
