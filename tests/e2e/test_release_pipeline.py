"""Authored fixtures only; the default path never contacts translation services."""

import asyncio
import hashlib
import json
import shutil
from pathlib import Path

import pytest
from sqlalchemy import select

from rat.database.tables import job_items, units
from rat.domain.translation import ProviderConfig, TranslationOptions
from rat.exporters.backup import BackupManager
from rat.exporters.installation import InstallationService
from rat.exporters.manager import ExportManager
from rat.extraction.scanner import GameImportService
from rat.extraction.translation_parser import parse_template
from rat.jobs.manager import JobControl
from rat.projects import ProjectService
from rat.providers.mock import MockProvider
from rat.review import ReviewService
from rat.translation.orchestrator import TranslationManager


def snapshot(root):
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file()
    }


@pytest.fixture
def pipeline(project, tmp_path, monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("E2E fixtures must not use a network")

    monkeypatch.setattr("socket.create_connection", forbidden)
    game = tmp_path / "لعبة أصلية"
    shutil.copytree(Path(__file__).parents[1] / "fixtures/game_with_tl", game)
    (game / "renpy").mkdir()
    (game / "renpy/vc_version.json").write_text('{"version":"8.5.3"}')
    before = snapshot(game)
    imported = GameImportService().scan(project.path, game)
    assert imported.inventory.engine.version == "8.5.3"
    assert len(imported.units) == 8 and all(item.ready for item in imported.protection)
    assert any(item.result.protected.tokens for item in imported.protection)
    return game, before, imported


def options():
    return TranslationOptions(max_items=2, concurrency=1, requests_per_minute=100000)


def test_import_protect_pause_reopen_resume_approve_export_qa_backup_restore(
    project, pipeline, tmp_path
):
    game, before, imported = pipeline
    with project.database.transaction() as connection:
        source_rows = connection.execute(select(units)).mappings().all()
    control = JobControl()
    manager = TranslationManager(project.path)
    job = manager.create_job(ProviderConfig(), options())

    def pause(progress):
        if progress.simulated >= 2:
            control.pause()

    paused = asyncio.run(manager.run(job, control=control, on_progress=pause))
    assert paused.status == "paused" and paused.remaining > 0
    path = project.path
    project.close()
    with ProjectService().open(path) as reopened:
        assert reopened.project == project.project
    resumed = asyncio.run(TranslationManager(path).run(job))
    assert resumed.remaining == resumed.errors == resumed.translated == 0
    assert resumed.simulated == 8  # Mock remains explicitly simulated.
    review = ReviewService(path)
    assert all(row.qa.valid for row in review.list_units())
    review.action([row.unit_id for row in review.list_units()], "approve")
    approved = review.list_units()
    retry = manager.create_job(ProviderConfig(), options())
    assert asyncio.run(manager.run(retry, retry_failed=True)).skipped == 8
    assert review.list_units() == approved
    result = ExportManager(path).export()
    assert result.status == "completed" and result.exported_count == 8 and not result.errors
    entries, errors = parse_template(
        (Path(result.destination) / "game/tl/arabic/script.rpy").read_text(encoding="utf-8"),
        "game/tl/arabic/script.rpy",
    )
    assert not errors
    assert {entry.identifier for entry in entries} == {
        unit.renpy_identifier for unit in imported.units
    }
    assert all(row.qa.valid for row in review.list_units())
    backup = BackupManager(path).create()
    restored = BackupManager.restore(backup, tmp_path / "restored")
    assert ReviewService(restored).list_units() == approved
    assert ExportManager(restored).export().file_hashes == result.file_hashes
    installation = InstallationService(path).install_copy(result.export_id, tmp_path / "installed")
    assert snapshot(InstallationService.restore_copy(installation)) == before
    with ProjectService().open(path) as reopened, reopened.database.transaction() as connection:
        assert connection.execute(select(units)).mappings().all() == source_rows
        assert all(reopened.units.revision_count(unit.unit_id) == 1 for unit in imported.units)
    assert snapshot(game) == before


def test_interrupted_in_progress_checkpoint_resumes_without_losing_approval(project, pipeline):
    game, before, imported = pipeline
    manager = TranslationManager(project.path)
    first = imported.units[0]
    review = ReviewService(project.path)
    review.save(first.unit_id, first.source_text)
    review.action([first.unit_id], "approve")
    job = manager.create_job(ProviderConfig(), options())
    with project.database.transaction() as connection:
        connection.execute(
            job_items.update()
            .where(job_items.c.job_id == job, job_items.c.status == "pending")
            .values(status="in_progress")
        )
    project.close()
    result = asyncio.run(TranslationManager(project.path).run(job))
    assert result.simulated == 7 and result.skipped == 1 and result.remaining == 0
    assert (
        next(row for row in review.list_units() if row.unit_id == first.unit_id).state == "approved"
    )
    assert snapshot(game) == before


def test_lost_placeholders_block_approval_and_export_then_retry_recovers(project, pipeline):
    game, before, imported = pipeline
    source = next(unit for unit in imported.units if "[player_name]" in unit.source_text)

    class BrokenMock(MockProvider):
        async def translate_batch(self, items, **kwargs):
            result = await super().translate_batch(items, **kwargs)
            for item in result:
                item["translation_text"] = "فقدت جميع المتغيرات"
            return result

    manager = TranslationManager(project.path, provider_factory=lambda *_a, **_k: BrokenMock())
    job = manager.create_job(ProviderConfig(), options(), unit_ids=[source.unit_id])
    failed = asyncio.run(manager.run(job))
    assert failed.errors == 1 and failed.simulated == 0
    with pytest.raises(ValueError, match="qa_blocks_approval"):
        ReviewService(project.path).action([source.unit_id], "approve")
    exported = ExportManager(project.path).export(approved_only=False)
    assert source.unit_id not in exported.exported
    assert asyncio.run(TranslationManager(project.path).run(job, retry_failed=True)).simulated == 1
    assert snapshot(game) == before


def test_real_sdk_template_generation_export_compile_and_lint(project, tmp_path, renpy_sdk):
    from rat.extraction.renpy_sdk import run_sdk, sdk_command

    game = tmp_path / "authored-sdk-game"
    shutil.copytree(Path(__file__).parents[1] / "fixtures/sdk_project", game)
    before = snapshot(game)
    imported = GameImportService().scan(project.path, game, sdk_dir=renpy_sdk, generate=True)
    selected = [u.unit_id for u in imported.units if u.source_relpath == "game/script.rpy"]
    manager = TranslationManager(project.path)
    job = manager.create_job(ProviderConfig(), options(), unit_ids=selected)
    assert asyncio.run(manager.run(job)).simulated == len(selected)
    ReviewService(project.path).action(selected, "approve")
    result = ExportManager(project.path).export()
    assert result.status == "completed"
    copied = tmp_path / "runtime"
    shutil.copytree(game, copied)
    shutil.copytree(Path(result.destination) / "game", copied / "game", dirs_exist_ok=True)
    run_sdk([*sdk_command(renpy_sdk), str(copied), "compile"], copied)
    lint = run_sdk([*sdk_command(renpy_sdk), str(copied), "lint"], copied)
    assert "Statistics" in lint
    assert snapshot(game) == before
    assert json.loads((Path(result.destination) / "manifest.json").read_text())["sdk_version"]
