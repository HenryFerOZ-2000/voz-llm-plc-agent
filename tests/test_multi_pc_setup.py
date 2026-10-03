"""
Repositorio preparado para dos PCs (docs/multi_pc_setup.md):
  * mapa BASE versionado (Experimentacion) vs mapa WORKING local (Modo Normal);
  * registro de ejecuciones local (runtime/) en vez de docs/07;
  * configuracion local por PC fuera de Git, con .example versionados.
Todo sobre proyectos temporales: nunca toca los mapas reales.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

import logger  # noqa: E402
from plc_maps.registry import experiment_reference_map_path, resolve_active_map_path, save_active_map_id  # noqa: E402
from plc_maps.store import ensure_working_maps, list_plc_maps, save_plc_map  # noqa: E402
from trial_experiments import batch_runner  # noqa: E402
from trial_experiments import trial_io_map  # noqa: E402

_ROOT = Path(__file__).resolve().parents[1]
_REAL_BASE = _ROOT / "data" / "plc_maps" / "mapa_banco_fisico_base.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    maps = tmp_path / "data" / "plc_maps"
    maps.mkdir(parents=True)
    shutil.copyfile(_REAL_BASE, maps / "mapa_banco_fisico_base.json")
    shutil.copyfile(_ROOT / "data" / "plc_maps" / "mapa_simulacion_completo.json", maps / "mapa_simulacion_completo.json")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "host_local.json").write_text(json.dumps({"host_id": "TEST_PC"}), encoding="utf-8")
    return tmp_path


def _maps(project: Path) -> Path:
    return project / "data" / "plc_maps"


def test_new_pc_initializes_working_from_base_with_traceability(project):
    base = _maps(project) / "mapa_banco_fisico_base.json"
    base_hash = _sha(base)
    [created] = ensure_working_maps(project)
    working = _maps(project) / "mapa_banco_fisico_working.json"
    assert created["working"] == working and created["initialized_from_kind"] == "base_map"
    payload, original = json.loads(working.read_text(encoding="utf-8")), json.loads(base.read_text(encoding="utf-8"))
    assert payload["variables"] == original["variables"] and payload["history"] == original["history"]
    record = payload["metadata"].pop("working_copy")
    assert payload["metadata"] == original["metadata"]  # mismo map_id: el puntero activo sigue valido
    assert record["base_sha256"] == base_hash and record["host_id"] == "TEST_PC" and record["initialized_at"]
    assert _sha(base) == base_hash  # el base nunca se modifica
    assert ensure_working_maps(project) == []  # idempotente: nunca sobrescribe un working existente


def test_listing_hides_the_base_and_exposes_the_working_with_the_same_map_id(project):
    names = {s["path"].name: s["map_id"] for s in list_plc_maps(project)}
    assert "mapa_banco_fisico_base.json" not in names
    assert names["mapa_banco_fisico_working.json"] == "mapa_banco_fisico"
    save_active_map_id(project, "mapa_banco_fisico")
    assert resolve_active_map_path(project).name == "mapa_banco_fisico_working.json"


def test_fresh_clone_without_pointer_selects_the_bench_working_map(project):
    for auxiliary in ("profiles.json", "experiment_variants.json"):  # archivos sin variables, primeros por orden
        shutil.copyfile(_ROOT / "data" / "plc_maps" / auxiliary, _maps(project) / auxiliary)
    assert resolve_active_map_path(project).name == "mapa_banco_fisico_working.json"
    assert json.loads((_maps(project) / "_active_map.json").read_text(encoding="utf-8"))["active_map_id"] == "mapa_banco_fisico"


def test_legacy_local_map_is_migrated_without_losing_assignments(project):
    legacy = _maps(project) / "mapa_banco_fisico.json"
    payload = json.loads((_maps(project) / "mapa_banco_fisico_base.json").read_text(encoding="utf-8"))
    payload["variables"][0]["name"] = "I_Local_Assignment"  # asignacion real de Modo Normal de esa PC
    legacy.write_text(json.dumps(payload), encoding="utf-8")
    [created] = ensure_working_maps(project)
    working = json.loads((_maps(project) / "mapa_banco_fisico_working.json").read_text(encoding="utf-8"))
    assert created["initialized_from_kind"] == "legacy_local_map"
    assert working["variables"][0]["name"] == "I_Local_Assignment"
    assert not legacy.exists() and (_maps(project) / "mapa_banco_fisico.json.pre_working.bak").exists()
    assert [s["map_id"] for s in list_plc_maps(project)].count("mapa_banco_fisico") == 1  # sin duplicados


def test_normal_mode_writes_only_the_working_map(project):
    base = _maps(project) / "mapa_banco_fisico_base.json"
    base_hash = _sha(base)
    ensure_working_maps(project)
    save_active_map_id(project, "mapa_banco_fisico")
    active = resolve_active_map_path(project)
    variables = json.loads(active.read_text(encoding="utf-8"))["variables"]
    variables[8]["name"] = "Q_Contactor_Star"
    save_plc_map(active, variables, history_entries=[{"source": "TEST", "old_name": "Q_x", "new_name": "Q_Contactor_Star"}])
    assert _sha(base) == base_hash
    saved = json.loads(active.read_text(encoding="utf-8"))
    assert saved["variables"][8]["name"] == "Q_Contactor_Star" and saved["history"][-1]["source"] == "TEST"
    assert saved["metadata"]["working_copy"]["host_id"] == "TEST_PC"  # la trazabilidad se conserva


def test_experimentation_uses_the_versioned_base_never_the_local_working(project, tmp_path):
    ensure_working_maps(project)
    working = _maps(project) / "mapa_banco_fisico_working.json"
    payload = json.loads(working.read_text(encoding="utf-8"))
    payload["variables"][8]["name"] = "Q_Only_On_This_PC"
    working.write_text(json.dumps(payload), encoding="utf-8")
    source = experiment_reference_map_path(working)
    assert source.name == "mapa_banco_fisico_base.json"
    reference = trial_io_map.create_working_map(tmp_path / "trial", source)
    trial_map = json.loads(Path(reference["working_map_path"]).read_text(encoding="utf-8"))
    assert reference["base_map_id"] == "mapa_banco_fisico" and reference["base_map_path"].endswith("_base.json")
    assert "Q_Only_On_This_PC" not in {v["name"] for v in trial_map["variables"]}
    simulation = _maps(project) / "mapa_simulacion_completo.json"
    assert experiment_reference_map_path(simulation) == simulation  # mapas sin base se usan tal cual


def test_integrity_protects_the_base_map():
    assert "data/plc_maps/mapa_banco_fisico_base.json" in batch_runner.MAP_FILES
    assert not any(name.endswith("_working.json") for name in batch_runner.PROTECTED_FILES)


def test_runtime_records_go_to_the_local_log_not_to_docs_07(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    curated = docs / "07_registro_pruebas.md"
    curated.write_text("# 07 Registro de Pruebas\n\ncurado\n", encoding="utf-8")
    path = logger.append_test_record_to_docs(docs_dir=docs, command_text="enciende", semantic_output={"intent_id": "INT_X"},
                                             verification_result={"is_valid": True}, saved_paths=None)
    logger.append_robustness_record_to_docs(docs, "enciende", "INT_X", "INT_X", True, None, "-")
    assert path == tmp_path / "runtime" / "development_log.md"
    assert "enciende" in path.read_text(encoding="utf-8") and "robustez" in path.read_text(encoding="utf-8")
    assert curated.read_text(encoding="utf-8") == "# 07 Registro de Pruebas\n\ncurado\n"


def _ignored(relative: str) -> bool:
    return subprocess.run(["git", "check-ignore", "-q", "--no-index", relative], cwd=_ROOT).returncode == 0


@pytest.mark.parametrize("relative", [
    "config/tia_openness_config.json", "config/tia_projects.json", "config/normal_voice.json",
    "config/voice_protocol_dev.json", "config/host_local.json", ".env", "local.env",
    "data/plc_maps/mapa_banco_fisico_working.json", "data/plc_maps/_active_map.json",
    "tiaw/T0001/s.scl", "results/x.json", "experiments/.trial_counter.json", "runtime/development_log.md",
    "audio/a.wav", "tia_projects/P/P.ap18", "snap.zap18", "generated_code/SIEMENS/active/PKG/x.st",
    "generated_code/archived/a/x.st", "generated_code/logs/x.json",
])
def test_local_files_are_ignored(relative):
    assert _ignored(relative), relative


@pytest.mark.parametrize("relative", [
    "src/gui.py", "tests/fixtures/normal_incident_manual_auto_sequence.json", "schemas/semantic_output.schema.json",
    "docs/07_registro_pruebas.md", "data/experiment_cases/canonical_cases.json", "data/experiment_oracles/D01.json",
    "data/experimental_design.json", "data/plc_maps/mapa_banco_fisico_base.json", "data/plc_maps/mapa_simulacion_completo.json",
    "data/plc_maps/profiles.json", "tia_openness_bridge/Program.cs", ".env.example",
    "config/tia_projects.example.json", "config/tia_openness_config.example.json", "config/intents_catalog.json",
    "generated_code/SIEMENS/active/.gitkeep", "requirements-transfer.txt", "scripts/check_environment.py",
])
def test_versioned_files_are_not_ignored(relative):
    assert not _ignored(relative), relative


def test_example_configs_have_no_machine_paths_or_secrets():
    for path in (_ROOT / "config").glob("*.example.json"):
        text = path.read_text(encoding="utf-8")
        json.loads(text)
        assert ":\\" not in text and ":/" not in text, path.name
        assert "sk-" not in text, path.name
