import asyncio
import json
import shutil
from pathlib import Path

from sqlalchemy import select

from rat.cli.commands import main
from rat.database.tables import units
from rat.domain.enums import UnitStatus
from rat.domain.models import SourceUnit
from rat.extraction.scanner import GameImportService
from rat.protection import ProtectionService
from rat.providers.mock import MockProvider


def snapshot(root):
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_extracted_units_mask_mock_restore_reopen_and_preserve_every_source_byte(
    project, tmp_path, monkeypatch
):
    def no_network(*_args, **_kwargs):
        raise AssertionError("Protection must not call a network service")

    monkeypatch.setattr("socket.create_connection", no_network)
    monkeypatch.setattr("httpx.Client.request", no_network)
    monkeypatch.setattr("httpx.AsyncClient.request", no_network)
    fixture = Path(__file__).parents[1] / "fixtures/game_with_tl"
    game = tmp_path / "original-game"
    shutil.copytree(fixture, game)
    before = snapshot(game)
    imported = GameImportService().scan(project.path, game)
    assert len(imported.protection) == len(imported.units) == 8
    assert all(item.ready for item in imported.protection)
    original_records = [unit.model_dump() for unit in imported.units]
    with project.database.transaction() as connection:
        stored_before = connection.execute(select(units.c.source_data)).scalars().all()
    service = ProtectionService()
    prepared = {item.unit_id: item for item in imported.protection}
    results = asyncio.run(
        MockProvider().translate_batch(
            [
                {
                    "unit_id": unit.unit_id,
                    "text": prepared[unit.unit_id].result.protected.masked_text,
                }
                for unit in imported.units
            ],
            source_language="en",
            target_language="ar",
            context={},
            settings={},
        )
    )
    assert [item["unit_id"] for item in results] == [
        unit.unit_id for unit in reversed(imported.units)
    ]
    by_id = {unit.unit_id: unit for unit in imported.units}
    for result in results:
        source = by_id[result["unit_id"]]
        restored = service.restore_unit(
            source, prepared[source.unit_id], result["translation_text"]
        )
        assert restored.valid and restored.text == source.source_text
        assert result["simulated"]
    reloaded = GameImportService().load(project.path)
    assert [unit.model_dump() for unit in reloaded.units] == original_records
    assert all(item.ready for item in reloaded.protection)
    assert (
        reloaded.protection[0].result.protected.namespace
        != imported.protection[0].result.protected.namespace
    )
    repeated = GameImportService().scan(project.path, game)
    assert repeated.added == 0 and repeated.reused == 8
    with project.database.transaction() as connection:
        assert connection.execute(select(units.c.source_data)).scalars().all() == stored_before
    assert snapshot(game) == before


def test_invalid_candidate_cannot_destroy_saved_approved_translation(project):
    fixture = Path(__file__).parents[1] / "fixtures/game_with_tl"
    imported = GameImportService().scan(project.path, fixture)
    source = next(unit for unit in imported.units if "[player_name]" in unit.source_text)
    project.units.save_translation(
        source.unit_id, source.source_text, provider_id="manual", status=UnitStatus.APPROVED
    )
    before = project.units.get(source.unit_id)
    revisions = project.units.revision_count(source.unit_id)
    prepared = next(item for item in imported.protection if item.unit_id == source.unit_id)
    result = ProtectionService().restore_unit(source, prepared, "ترجمة فقدت الرموز")
    assert not result.valid and result.text is None
    assert project.units.get(source.unit_id) == before
    assert project.units.revision_count(source.unit_id) == revisions


def test_source_version_change_invalidates_old_unit_protection(source):
    service = ProtectionService()
    prepared = service.prepare_unit(source)
    changed = SourceUnit.model_validate(
        {
            **source.model_dump(exclude={"source_sha256"}),
            "source_text": source.source_text + " added",
        }
    )
    result = service.restore_unit(changed, prepared, prepared.result.protected.masked_text)
    assert not result.valid
    assert result.issues[0].code == "unit_protection_mismatch"


def test_broken_text_remains_visible_but_cannot_be_prepared(project, tmp_path):
    game = tmp_path / "broken" / "game"
    game.mkdir(parents=True)
    script = game / "script.rpy"
    script.write_text(
        'label start:\n    "{b}unclosed"\n    "[items[0)]"\n    return\n', encoding="utf-8"
    )
    before = script.read_bytes()
    imported = GameImportService().scan(project.path, game.parent)
    assert len(imported.units) == 2
    assert all(not item.ready and item.result.protected is None for item in imported.protection)
    assert {error.code for item in imported.protection for error in item.result.issues} >= {
        "unclosed_tag",
        "mismatched_bracket",
    }
    assert script.read_bytes() == before


def test_protect_cli_uses_persisted_extracted_units_without_network_or_writes(
    project, tmp_path, capsys
):
    fixture = Path(__file__).parents[1] / "fixtures/game_with_tl"
    GameImportService().scan(project.path, fixture)
    database_before = (project.path / "project.sqlite").read_bytes()
    assert (
        main(["--log-dir", str(tmp_path / "logs"), "protect", "--project", str(project.path)]) == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["network_used"] is False
    assert result["ready"] == 8 and result["blocked"] == 0
    assert len(result["units"]) == 8
    assert (project.path / "project.sqlite").read_bytes() == database_before
    assert "player_name" not in (tmp_path / "logs/application.log").read_text(encoding="utf-8")
