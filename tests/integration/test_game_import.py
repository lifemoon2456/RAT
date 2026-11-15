import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from rat.database.tables import game_imports, schema_version, source_files, unit_discovery, units
from rat.domain.enums import UnitStatus
from rat.extraction.renpy_sdk import generate_templates
from rat.extraction.scanner import GameImportService
from rat.projects import ProjectService
from rat.security.safe_paths import ScanError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def fingerprints(directory):
    return {
        path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in directory.rglob("*")
        if path.is_file()
    }


@pytest.fixture
def game(tmp_path):
    destination = tmp_path / "original-game"
    shutil.copytree(FIXTURES / "game_with_tl", destination)
    return destination


def test_official_fixture_import_is_idempotent_and_preserves_approved(project, game):
    before = fingerprints(game)
    service = GameImportService()
    first = service.scan(project.path, game)
    assert len(first.units) == 8
    assert first.added == 8
    assert all(origin.source_verified for origin in first.origins)
    dialogue = next(unit for unit in first.units if unit.source_line == 3)
    assert dialogue.renpy_identifier == "start_1b4a9f2d"
    assert dialogue.source_text == "Hello, [player_name]! {i}Welcome{/i}."
    choices = [unit for unit in first.units if unit.kind.value == "menu_choice"]
    assert {unit.old for unit in choices} == {"Go left", "Go right"}
    assert all(unit.renpy_identifier is None for unit in choices)
    project.units.save_translation(
        dialogue.unit_id, dialogue.source_text, provider_id="manual", status=UnitStatus.APPROVED
    )
    second = service.scan(project.path, game)
    assert second.reused == 8 and second.added == 0
    assert {unit.unit_id for unit in second.units} == {unit.unit_id for unit in first.units}
    assert project.units.get(dialogue.unit_id).translation_text == dialogue.source_text
    assert project.units.revision_count(dialogue.unit_id) == 1
    reopened = service.load(project.path)
    assert reopened.units == second.units
    assert fingerprints(game) == before
    assert json.loads((project.path / "inventory.json").read_text())["game_dir"] == str(game)


def test_changed_source_creates_version_without_overwriting_approved(project, game):
    service = GameImportService()
    first = service.scan(project.path, game)
    old = next(unit for unit in first.units if unit.source_line == 3)
    project.units.save_translation(
        old.unit_id, old.source_text, provider_id="manual", status=UnitStatus.APPROVED
    )
    path = game / "game/script.rpy"
    path.write_text(path.read_text().replace("Hello,", "Changed hello,"), encoding="utf-8")
    before = fingerprints(game)
    second = service.scan(project.path, game)
    assert any(issue.code == "template_source_mismatch" for issue in second.issues)
    updated = next(unit for unit in second.units if unit.source_line == 3)
    assert updated.unit_id != old.unit_id
    assert updated.renpy_identifier is None
    assert updated.source_text.startswith("Changed hello")
    assert second.changed == 1
    assert project.units.get(old.unit_id).source_text == old.source_text
    assert project.units.get(old.unit_id).status == UnitStatus.APPROVED
    assert fingerprints(game) == before


def test_python_is_never_run_and_sdk_generation_is_refused(project, game, monkeypatch):
    path = game / "game/untrusted.rpy"
    path.write_text('init python:\n    open("MUST_NOT_EXIST", "w").write("bad")\n')
    before = fingerprints(game)
    report = GameImportService().scan(project.path, game)
    assert any(issue.code == "python_skipped" for issue in report.issues)
    monkeypatch.setattr("rat.extraction.renpy_sdk.sdk_command", lambda _path: ["not-run"])
    monkeypatch.setattr(
        "rat.extraction.renpy_sdk.run_sdk", lambda *_a, **_k: pytest.fail("must not call SDK")
    )
    with pytest.raises(ScanError, match="unsafe_or_unsupported"):
        generate_templates(report.inventory, Path("sdk"), project.path)
    assert fingerprints(game) == before
    assert not Path("MUST_NOT_EXIST").exists()


def test_other_language_templates_are_not_transplanted(project, game):
    (game / "game/tl/arabic").rename(game / "game/tl/french")
    path = game / "game/tl/french/script.rpy"
    path.write_text(
        path.read_text(encoding="utf-8-sig").replace("translate arabic", "translate french"),
        encoding="utf-8",
    )
    report = GameImportService().scan(project.path, game)
    assert report.inventory.translation_languages == ("french",)
    assert len(report.units) == 8
    assert all(unit.renpy_identifier is None for unit in report.units)
    assert all(unit.confidence == "unverified" for unit in report.units)


@pytest.mark.parametrize("filename", ["extra_ren.py", "scripts.rpa", "orphan.rpyc"])
def test_sdk_rejects_incomplete_or_python_module_inputs(project, game, monkeypatch, filename):
    (game / "game" / filename).write_text("must not load or execute")
    inventory = __import__("rat.discovery.inventory", fromlist=["inventory_game"]).inventory_game(
        game
    )
    monkeypatch.setattr("rat.extraction.renpy_sdk.sdk_command", lambda _path: ["not-run"])
    with pytest.raises(ScanError, match="requires_complete_declarative"):
        generate_templates(inventory, Path("sdk"), project.path)


def test_failure_keeps_previous_import_intact(project, game, monkeypatch):
    first = GameImportService().scan(project.path, game)

    def timeout(*_args):
        raise ScanError("sdk_timeout")

    monkeypatch.setattr("rat.extraction.scanner.generate_templates", timeout)
    with pytest.raises(ScanError, match="sdk_timeout"):
        GameImportService().scan(project.path, game, sdk_dir=Path("sdk"), generate=True)
    # Temporary protection markers are regenerated; the persisted snapshot must be identical.
    assert GameImportService().load(project.path).model_dump(
        exclude={"protection"}
    ) == first.model_dump(exclude={"protection"})


def test_import_rejects_workspace_inside_original_game(project):
    (project.path / "game").mkdir()
    with pytest.raises(ScanError, match="overlaps_game"):
        GameImportService().scan(project.path, project.path)


def test_better_confidence_reuses_units_and_approved_results(project, game, monkeypatch):
    service = GameImportService()
    first = service.scan(project.path, game)
    selected = first.units[0]
    project.units.save_translation(
        selected.unit_id, selected.source_text, provider_id="manual", status=UnitStatus.APPROVED
    )
    # Genuine fixture as the mocked runner output; the live runner is tested separately.
    monkeypatch.setattr("rat.extraction.scanner.generate_templates", lambda *_: (game, "8.5.3"))
    verified = service.scan(project.path, game, sdk_dir=Path("sdk"), generate=True)
    assert verified.added == 0 and verified.reused == 8
    assert all(unit.confidence == "official_template" for unit in verified.units)
    selected_again = next(unit for unit in verified.units if unit.unit_id == selected.unit_id)
    assert selected_again.status == UnitStatus.APPROVED
    assert selected_again.translation_text == selected.source_text
    assert service.scan(project.path, game).units == verified.units


def test_game_changing_during_scan_does_not_replace_saved_results(project, game, monkeypatch):
    service = GameImportService()
    first = service.scan(project.path, game)
    original_parser = __import__(
        "rat.extraction.scanner", fromlist=["parse_template"]
    ).parse_template
    changed = False

    def modify_after_reading(*args, **kwargs):
        nonlocal changed
        result = original_parser(*args, **kwargs)
        if not changed:
            path = game / "game/script.rpy"
            path.write_text(path.read_text() + "\n# user editing during scan\n", encoding="utf-8")
            changed = True
        return result

    monkeypatch.setattr("rat.extraction.scanner.parse_template", modify_after_reading)
    with pytest.raises(ScanError, match="game_changed_during_scan"):
        service.scan(project.path, game)
    assert service.load(project.path).model_dump(exclude={"protection"}) == first.model_dump(
        exclude={"protection"}
    )


def test_duplicate_strings_and_identifiers_are_not_counted_twice(project, game):
    path = game / "game/tl/arabic/script.rpy"
    path.write_text(
        path.read_text(encoding="utf-8-sig")
        + """
# game/script.rpy:3
translate arabic start_1b4a9f2d:
    # "Hello, [player_name]! {i}Welcome{/i}."
    ""
translate arabic strings:
    # game/script.rpy:9
    old "Go left"
    new ""
""",
        encoding="utf-8",
    )
    report = GameImportService().scan(project.path, game)
    assert len(report.units) == 8
    assert sum(issue.code == "duplicate_template_entry" for issue in report.issues) == 2


def test_phase0_database_migrates_with_backup_and_immutable_approved_data(project, source):
    # Store the exact old JSON contract: the new optional fields were absent in v1.
    with project.database.transaction() as connection:
        connection.execute(
            units.insert().values(
                unit_id=source.unit_id,
                project_id=source.project_id,
                location_key=source.location_key,
                source_data=source.model_dump(
                    mode="json", exclude={"source_location", "source_literal"}
                ),
            )
        )
    project.units.save_translation(
        source.unit_id, source.source_text, provider_id="manual", status=UnitStatus.APPROVED
    )
    with project.database.transaction() as connection:
        for table in (unit_discovery, source_files, game_imports):
            table.drop(connection)
        connection.execute(schema_version.update().values(version=1))
    project.close()
    with ProjectService().open(project.path) as reopened:
        stored = reopened.units.get(source.unit_id)
        assert stored.source_sha256 == source.source_sha256
        assert (
            stored.translation_text == source.source_text and stored.status == UnitStatus.APPROVED
        )
        with pytest.raises(ValueError, match="Approved"):
            reopened.units.save_translation(source.unit_id, "replace", provider_id="mock")
    backup = list(project.path.glob("project.sqlite.before-v4-*.bak"))
    assert len(backup) == 1
    with sqlite3.connect(backup[0]) as connection:
        assert connection.execute("SELECT version FROM schema_version").fetchone() == (1,)


def test_real_sdk_generates_literal_ids_and_originals_remain_unchanged(
    project, tmp_path, renpy_sdk
):
    original = tmp_path / "sdk-source"
    shutil.copytree(FIXTURES / "sdk_project", original)
    script = original / "game/script.rpy"
    script.write_bytes(script.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    before = fingerprints(original)
    service = GameImportService()
    report = service.scan(project.path, original, sdk_dir=renpy_sdk, generate=True)
    assert report.sdk_version.startswith("8.")
    assert (
        report.inventory.engine.version is None
    )  # SDK version is not evidence of the game's version.
    game_units = [unit for unit in report.units if unit.source_relpath == "game/script.rpy"]
    assert len(game_units) == 8
    assert all(unit.confidence == "official_template" for unit in game_units)
    assert (
        next(unit for unit in game_units if unit.source_line == 5).source_text
        == "This sentence spans two physical lines."
    )
    assert (
        next(unit for unit in game_units if unit.source_line == 3).renpy_identifier
        == "start_1b4a9f2d"
    )
    assert (Path(report.template_dir) / "game/tl/arabic/script.rpy").is_file()
    assert fingerprints(original) == before
    second = service.scan(project.path, original, sdk_dir=renpy_sdk, generate=True)
    assert second.added == 0 and second.reused == len(report.units)
    assert fingerprints(original) == before
