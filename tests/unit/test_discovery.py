import pytest

from rat.discovery.capabilities import capabilities
from rat.discovery.inventory import inventory_game
from rat.discovery.version_detector import detect_version
from rat.security.safe_paths import ScanError, safe_relative


def test_inventory_all_script_types_and_languages_without_running_python(tmp_path):
    game = tmp_path / "game"
    game.mkdir()
    for filename in ("a.RPY", "a.rpyc", "bundle.rpa", "module.rpym", "module.rpymc"):
        (game / filename).write_text('init python:\n    raise RuntimeError("never run")\n')
    (game / "tl" / "arabic").mkdir(parents=True)
    (game / "tl" / "french").mkdir()
    (game / "tl" / "arabic" / "strings.rpy").write_text(
        'translate arabic strings:\n    old "Start"\n    new ""\n'
    )
    report = inventory_game(tmp_path)
    assert {item.extension for item in report.files} == {".rpy", ".rpyc", ".rpa", ".rpym", ".rpymc"}
    assert report.translation_languages == ("arabic", "french")
    assert set(capabilities(report)) == {"source_scan", "existing_arabic_templates"}
    assert {issue.code for issue in report.issues} >= {
        "archives_not_extracted",
        "compiled_scripts_not_decompiled",
    }
    assert (game / "a.RPY").read_text().startswith("init python")


def test_compiled_only_is_reported_as_unsupported(tmp_path):
    (tmp_path / "game").mkdir()
    (tmp_path / "game" / "script.rpyc").write_bytes(b"not executed or unpickled")
    assert capabilities(inventory_game(tmp_path)) == ("no_supported_text_source",)


def test_inventory_bounds_and_link_skipping(tmp_path, monkeypatch):
    (tmp_path / "game").mkdir()
    linked = tmp_path / "game" / "outside.rpy"
    linked.write_text('"not read"')
    original = __import__("rat.discovery.inventory", fromlist=["is_link"]).is_link
    monkeypatch.setattr(
        "rat.discovery.inventory.is_link", lambda path: path == linked or original(path)
    )
    report = inventory_game(tmp_path)
    assert not report.files
    assert report.issues[0].code == "link_skipped"
    with pytest.raises(ScanError, match="entry_limit"):
        inventory_game(tmp_path, max_entries=0)


@pytest.mark.parametrize("value", ["../evil.rpy", "C:/evil.rpy", "//host/share/a.rpy", "/a.rpy"])
def test_reference_paths_cannot_escape(value):
    with pytest.raises(ScanError):
        safe_relative(value)


def test_version_uses_engine_evidence_and_reports_conflicts(tmp_path):
    (tmp_path / "game").mkdir()
    (tmp_path / "game" / "options.rpy").write_text('define config.version = "999.9.9"')
    assert detect_version(tmp_path).version is None
    (tmp_path / "log.txt").write_text("Ren'Py 8.5.3.26051504\n")
    assert detect_version(tmp_path).version == "8.5.3"
    assert detect_version(tmp_path).confidence == "reported"
    (tmp_path / "renpy").mkdir()
    (tmp_path / "renpy" / "vc_version.py").write_text("version = '8.3.7.25031702'\n")
    assert detect_version(tmp_path).version is None
    assert detect_version(tmp_path).confidence == "conflict"


def test_invalid_game_path_is_rejected(tmp_path):
    with pytest.raises(ScanError, match="missing_game"):
        inventory_game(tmp_path)
