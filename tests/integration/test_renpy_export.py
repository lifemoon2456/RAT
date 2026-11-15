import hashlib
import json
import shutil
import zipfile
from pathlib import Path

import pytest

from rat.exporters.backup import BackupManager
from rat.exporters.manager import ExportManager
from rat.exporters.renpy_writer import quote_renpy, replace_say_literal
from rat.extraction.rpy_parser import decode_literal
from rat.extraction.scanner import GameImportService
from rat.extraction.translation_parser import parse_template
from rat.review import ReviewService


def prepare(project, tmp_path):
    game = tmp_path / "original"
    shutil.copytree(Path(__file__).parents[1] / "fixtures/game_with_tl", game)
    imported = GameImportService().scan(project.path, game)
    review = ReviewService(project.path)
    for record in review.list_units():
        review.save(
            record.unit_id,
            record.source.source_text.replace("Hello", "مرحبًا").replace("Go left", "اذهب يسارًا"),
        )
    review.action([record.unit_id for record in review.list_units()], "approve")
    return game, imported, review


def snapshot(root):
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_export_import_roundtrip_ids_old_text_and_original_game_unchanged(project, tmp_path):
    game, imported, review = prepare(project, tmp_path)
    before = snapshot(game)
    result = ExportManager(project.path).export()
    assert result.status == "completed" and len(result.exported) == 8 and not result.errors
    directory = Path(result.destination)
    text = (directory / "game/tl/arabic/script.rpy").read_text(encoding="utf-8")
    entries, errors = parse_template(text, "game/tl/arabic/script.rpy")
    assert not errors and len(entries) == 8
    assert {entry.identifier for entry in entries if entry.identifier} == {
        unit.renpy_identifier for unit in imported.units if unit.renpy_identifier
    }
    with zipfile.ZipFile(directory / "translation_patch.zip") as archive:
        assert archive.testzip() is None
        assert "game/tl/arabic/script.rpy" in archive.namelist()
    exported_game = tmp_path / "roundtrip"
    shutil.copytree(game, exported_game)
    shutil.copy2(
        directory / "game/tl/arabic/script.rpy", exported_game / "game/tl/arabic/script.rpy"
    )
    from rat.projects import ProjectService

    with ProjectService().create("roundtrip", workspace=tmp_path / "other-projects") as other:
        reimported = GameImportService().scan(other.path, exported_game)
    original = {(unit.renpy_identifier, unit.old, unit.source_text) for unit in imported.units}
    assert {
        (unit.renpy_identifier, unit.old, unit.source_text) for unit in reimported.units
    } == original
    expected = {
        record.source.source_text: record.translation_text for record in review.list_units()
    }
    assert all(unit.translation_text == expected[unit.source_text] for unit in reimported.units)
    assert snapshot(game) == before
    assert json.loads((directory / "report.json").read_text(encoding="utf-8"))["exported"]
    assert result.exported_count == 8 and result.error_count == 0
    assert ExportManager(project.path).history()[0] == result


@pytest.mark.parametrize(
    "text",
    [
        '"quoted" \\ path\nnext',
        "  repeated   spaces  ",
        "tabs\tand\rcarriage",
        "[[name] {{b} 100%%",
        "عربي 😀 \u2028",
    ],
)
def test_renpy_literal_encoding_roundtrips_decoded_whitespace_and_escapes(text):
    assert decode_literal(quote_renpy(text)) == text


def test_writer_replaces_only_dialogue_literal_not_speaker_or_inline_comment():
    result = replace_say_literal('"Eileen" "old" # "old"', "جديد")
    assert result == '"Eileen" "جديد" # "old"'


def test_approved_only_and_skip_do_not_leak_nonapproved_or_bad_text(project, tmp_path):
    _game, _imported, review = prepare(project, tmp_path)
    records = review.list_units()
    rejected = records[0]
    review.action([rejected.unit_id], "reject")
    review.save(rejected.unit_id, "invalid [changed]")
    skipped = records[1]
    review.action([skipped.unit_id], "skip")
    result = ExportManager(project.path).export()
    assert len(result.exported) == 6
    assert rejected.unit_id not in result.exported and skipped.unit_id not in result.exported
    all_result = ExportManager(project.path).export(approved_only=False)
    assert rejected.unit_id not in all_result.exported
    assert any(item.code == "qa_failed" for item in all_result.skipped)


def test_snapshot_export_works_offline_after_original_is_moved(project, tmp_path):
    game, _imported, _review = prepare(project, tmp_path)
    first = ExportManager(project.path).export()
    game.rename(tmp_path / "moved-original")
    second = ExportManager(project.path).export()
    assert second.status == "completed" and second.file_hashes == first.file_hashes


def test_first_export_blocks_changed_templates_or_sources(project, tmp_path):
    game, _imported, _review = prepare(project, tmp_path)
    source = game / "game/script.rpy"
    source.write_text(source.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
    result = ExportManager(project.path).export()
    assert result.status == "failed" and not result.exported
    assert result.errors


@pytest.mark.parametrize("path", ["../outside.rpy", "game/CON.rpy", "game/bad./a.rpy"])
def test_export_paths_reject_traversal_and_windows_ambiguous_names(tmp_path, path):
    from rat.exporters.safe_io import checked_path

    with pytest.raises(ValueError):
        checked_path(tmp_path, path)


def test_corrupt_cached_template_is_blocked_and_counted(project, tmp_path):
    from rat.database.tables import template_snapshots

    prepare(project, tmp_path)
    ExportManager(project.path).export()
    with project.database.transaction() as connection:
        connection.execute(template_snapshots.update().values(content="corrupt"))
    result = ExportManager(project.path).export()
    assert result.status == "failed" and result.exported_count == 0
    assert result.skipped_count == 8 and result.error_count > 0
    assert "game/tl/arabic/script.rpy" not in result.created_files


def test_backup_is_verified_project_snapshot_and_does_not_touch_game(project, tmp_path):
    game, _imported, _review = prepare(project, tmp_path)
    before = snapshot(game)
    manager = BackupManager(project.path)
    backup = manager.create()
    assert manager.verify(backup)["kind"] == "rat_project_only"
    assert (backup / "project.sqlite").is_file() and (backup / "project.yaml").is_file()
    (backup / "project.yaml").write_text("corrupted", encoding="utf-8")
    with pytest.raises(ValueError, match="hash_mismatch"):
        manager.verify(backup)
    assert snapshot(game) == before


def test_real_sdk_loads_exported_dialogue_ids_strings_and_interpolates_variables(
    project, tmp_path, renpy_sdk
):
    # Only our own authored inert fixture is imported. The diagnostic command below
    # executes solely in a new disposable runtime copy, after the export is complete.
    game, imported, review = prepare(project, tmp_path)
    before = snapshot(game)
    result = ExportManager(project.path).export()
    runtime = tmp_path / "runtime-copy"
    shutil.copytree(game, runtime)
    shutil.copytree(Path(result.destination) / "game", runtime / "game", dirs_exist_ok=True)
    expected = {
        row.source.renpy_identifier: row.translation_text
        for row in review.list_units()
        if row.source.renpy_identifier
    }
    strings = {
        row.source.old: row.translation_text
        for row in review.list_units()
        if row.source.old is not None
    }
    # JSON becomes a Python literal only after json.dumps of our own trusted data.
    code = """
init python:
    import json
    import os
    def rat_verify_export():
        renpy.game.preferences.language = "arabic"
        expected = json.loads(EXPECTED_JSON)
        for identifier, text in expected.items():
            node, translated = renpy.game.script.translator.lookup_translate(identifier)
            assert translated and node.what == text, (identifier, node.what, text)
            actual, substituted = renpy.substitutions.substitute(
                node.what, scope={"player_name": "RAT_TESTER"}, translate=False)
            if "[player_name]" in text:
                assert substituted and "RAT_TESTER" in actual and "[player_name]" not in actual
        for original, text in json.loads(STRINGS_JSON).items():
            actual = renpy.translation.translate_string(original, "arabic")
            assert actual == text, (original, actual, text)
        with open(os.path.join(config.basedir, "runtime-verified.json"), "w") as stream:
            json.dump({"dialogue": len(expected), "strings": 2, "interpolation": True}, stream)
        return False
    renpy.arguments.register_command("rat-verify-export", rat_verify_export)
"""
    code = code.replace("EXPECTED_JSON", repr(json.dumps(expected, ensure_ascii=True)))
    code = code.replace("STRINGS_JSON", repr(json.dumps(strings, ensure_ascii=True)))
    (runtime / "game/rat_diagnostic.rpy").write_text(code, encoding="utf-8")
    from rat.extraction.renpy_sdk import run_sdk, sdk_command

    run_sdk(sdk_command(renpy_sdk) + [str(runtime), "compile"], runtime)
    run_sdk(sdk_command(renpy_sdk) + [str(runtime), "rat-verify-export"], runtime)
    verified = json.loads((runtime / "runtime-verified.json").read_text())
    assert verified == {"dialogue": 6, "strings": 2, "interpolation": True}
    assert snapshot(game) == before
    assert len(imported.units) == 8
