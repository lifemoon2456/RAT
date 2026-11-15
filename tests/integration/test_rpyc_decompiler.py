import json
from pathlib import Path

import pytest
from packed_support import fingerprints, write_rpa

from rat.arabic.runtime import ArabicRuntimeService
from rat.domain.discovery import EngineVersion
from rat.domain.packed import PackedOptions
from rat.extraction.packed_manager import PackedGameService
from rat.extraction.renpy_sdk import run_sdk, sdk_command
from rat.extraction.rpyc_adapter import SafeRpycDecompiler
from rat.extraction.scanner import GameImportService


@pytest.mark.parametrize(
    "version,confidence,expected",
    [
        (None, "unknown", "unknown_engine_version"),
        ("7.8.7", "static", "unverified_rpyc_engine_family"),
        ("8.5.3", "conflict", "conflicting_engine_version"),
        ("9.0.0", "static", "unverified_rpyc_engine_family"),
    ],
)
def test_decompiler_version_gate(version, confidence, expected):
    profile = SafeRpycDecompiler().compatibility(
        EngineVersion(version=version, confidence=confidence), b"RENPY RPC2 data"
    )
    assert not profile.supported and profile.code == expected


def compile_owned_fixture(tmp_path, sdk, *, with_python=False):
    root = tmp_path / "authored-sdk-input"
    (root / "game").mkdir(parents=True)
    source = Path(__file__).parents[1] / "fixtures/sdk_project/game/script.rpy"
    text = source.read_text(encoding="utf-8")
    marker = tmp_path / "GAME_PYTHON_MUST_NOT_RUN"
    if with_python:
        text = text.replace(
            "label start:",
            "label start:\n    python:\n        " + f"open({str(marker)!r}, 'w').write('bad')",
        )
    (root / "game/script.rpy").write_text(text, encoding="utf-8")
    run_sdk(sdk_command(sdk) + [str(root), "compile"], root)
    assert not marker.exists()
    return (root / "game/script.rpyc").read_bytes(), marker


def test_real_sdk_rpyc_decompiles_to_discovery_with_actual_ids_and_no_original_writes(
    project, tmp_path, renpy_sdk
):
    data, marker = compile_owned_fixture(tmp_path, renpy_sdk)
    root = tmp_path / "packed-original"
    (root / "game").mkdir(parents=True)
    (root / "renpy").mkdir()
    (root / "renpy/vc_version.py").write_text("version = '8.5.3.26051504'")
    write_rpa(root / "game/own.rpa", {"script.rpyc": data})
    before = fingerprints(root)
    report = PackedGameService(project.path).extract(root, PackedOptions(decompile=True))
    assert report.import_error is None
    assert report.imported_count == 8 and report.rpyc_count == 1
    decoded = [item for item in report.files if item.status == "decompiled"]
    assert len(decoded) == 1 and not decoded[0].partial
    imported = GameImportService().load(project.path)
    assert (
        next(unit for unit in imported.units if "Hello," in unit.source_text).renpy_identifier
        == "start_1b4a9f2d"
    )
    assert len({unit.renpy_identifier for unit in imported.units if unit.renpy_identifier}) == 6
    assert not marker.exists() and fingerprints(root) == before
    assert json.loads((project.path / report.manifest_relpath).read_text())["files"]


def test_python_in_rpyc_is_omitted_and_never_executed(project, tmp_path, renpy_sdk):
    data, marker = compile_owned_fixture(tmp_path, renpy_sdk, with_python=True)
    root = tmp_path / "original"
    (root / "game").mkdir(parents=True)
    (root / "game/script.rpyc").write_bytes(data)
    options = PackedOptions(decompile=True, engine_version="8.5.3", engine_version_confirmed=True)
    report = PackedGameService(project.path).extract(root, options)
    assert report.status == "partial" and report.imported_count == 8
    recovered = next(item for item in report.files if item.status == "decompiled")
    assert recovered.partial and "omitted_ast_node:Python" in recovered.warnings
    source = (project.path / recovered.published_path).read_text(encoding="utf-8")
    assert "open(" not in source and not marker.exists()


def test_recovered_declarative_source_can_generate_official_templates_in_separate_stage(
    project, tmp_path, renpy_sdk
):
    root = tmp_path / "original"
    write_rpa(
        root / "game/source.rpa",
        {"script.rpy": b'label start:\n    "Owned fixture [name]"\n    return\n'},
    )
    report = PackedGameService(project.path).extract(root)
    before = fingerprints(root)
    imported = GameImportService().scan(
        project.path,
        project.path / report.view_relpath,
        packed_manifest=project.path / report.manifest_relpath,
        sdk_dir=renpy_sdk,
        generate=True,
    )
    assert imported.units[0].renpy_identifier and imported.sdk_version == "8.5.3"
    demo = ArabicRuntimeService(project.path).create_demo(renpy_sdk)
    assert (demo / "game/script.rpy").is_file()
    assert fingerprints(root) == before
