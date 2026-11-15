import asyncio
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from openai import AsyncOpenAI
from sqlalchemy import select

from rat.database.tables import job_items, schema_version, tm_entries, units
from rat.database.translation_repository import TranslationRepository
from rat.domain.enums import UnitStatus
from rat.domain.translation import GlossaryTerm, ProviderConfig, TranslationOptions
from rat.extraction.scanner import GameImportService
from rat.jobs.manager import JobControl, ProjectJobLock
from rat.projects import ProjectService
from rat.providers.base import ProviderError
from rat.providers.mock import MockProvider
from rat.providers.openai import OpenAIProvider
from rat.translation.glossary import GlossarySystem
from rat.translation.orchestrator import TranslationManager


def import_game(project, tmp_path, count=120, *, repeated=False, text=None):
    game = tmp_path / "original" / "game"
    game.mkdir(parents=True)
    lines = [
        text or ("Repeat [name]" if repeated else f"Line {index} [name] {{b}}hello{{/b}}")
        for index in range(count)
    ]
    script = game / "script.rpy"
    script.write_text(
        "label start:\n"
        + "\n".join("    " + json.dumps(line) for line in lines)
        + "\n    return\n",
        encoding="utf-8",
    )
    before = {p.relative_to(game): p.read_bytes() for p in game.rglob("*") if p.is_file()}
    report = GameImportService().scan(project.path, game.parent)
    return report, game, before


class CountingMock(MockProvider):
    def __init__(self):
        self.calls = []

    async def translate_batch(self, items, **kwargs):
        self.calls.append(items)
        return await super().translate_batch(items, **kwargs)


def manager_for(project, provider):
    return TranslationManager(project.path, provider_factory=lambda *_args, **_kwargs: provider)


def fast_options(**kwargs):
    return TranslationOptions(requests_per_minute=100000, max_items=8, concurrency=1, **kwargs)


def test_120_mock_units_checkpoint_pause_and_resume_in_another_process(project, tmp_path):
    imported, game, before = import_game(project, tmp_path)
    provider, control = CountingMock(), JobControl()
    manager = manager_for(project, provider)
    job_id = manager.create_job(ProviderConfig(), fast_options())

    def progress(snapshot):
        if snapshot.simulated >= 8:
            control.pause()

    paused = asyncio.run(manager.run(job_id, control=control, on_progress=progress))
    assert paused.status == "paused" and paused.simulated == 8 and paused.remaining == 112
    assert paused.translated == 0
    first_ids = {item["unit_id"] for item in provider.calls[0]}
    executable = Path(sys.executable).parent / ("rat.exe" if os.name == "nt" else "rat")
    resumed = subprocess.run(
        [
            str(executable),
            "--log-dir",
            str(tmp_path / "logs"),
            "translate",
            "--project",
            str(project.path),
            "--job",
            job_id,
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert resumed.returncode == 0, resumed.stderr
    result = json.loads(resumed.stdout)
    assert result["status"] == "completed" and result["remaining"] == 0
    assert result["simulated"] == 120 and result["translated"] == 0
    for source in imported.units:
        assert project.units.revision_count(source.unit_id) == 1
        assert project.units.get(source.unit_id).source_sha256 == source.source_sha256
    assert all(project.units.revision_count(unit_id) == 1 for unit_id in first_ids)
    assert {p.relative_to(game): p.read_bytes() for p in game.rglob("*") if p.is_file()} == before
    second_job = manager.create_job(ProviderConfig(), fast_options())
    assert asyncio.run(manager.run(second_job)).skipped == 120


def test_translation_memory_deduplicates_identical_units_in_the_same_batch(project, tmp_path):
    import_game(project, tmp_path, count=30, repeated=True)
    provider = CountingMock()
    manager = manager_for(project, provider)
    job = manager.create_job(ProviderConfig(), fast_options())
    result = asyncio.run(manager.run(job))
    # Five edge/neighbor contexts; the 26 interior copies share one exact memory key.
    assert result.simulated == 30 and result.errors == 0
    assert sum(len(batch) for batch in provider.calls) == 5
    with project.database.transaction() as connection:
        assert len(connection.execute(select(tm_entries)).all()) == 5


def test_invalid_protection_is_rejected_per_item_without_losing_good_results(project, tmp_path):
    report, _, _ = import_game(project, tmp_path, count=3)

    class DamagingMock(CountingMock):
        async def translate_batch(self, items, **kwargs):
            result = await super().translate_batch(items, **kwargs)
            result[0]["translation_text"] = "Lost all protected markers"
            return result

    manager = manager_for(project, DamagingMock())
    job = manager.create_job(ProviderConfig(), fast_options())
    result = asyncio.run(manager.run(job))
    assert result.errors == 1 and result.simulated == 2 and result.remaining == 0
    assert sum(project.units.revision_count(source.unit_id) for source in report.units) == 2
    failed = [
        source
        for source in report.units
        if project.units.get(source.unit_id).translation_text is None
    ]
    assert len(failed) == 1


def test_bad_json_ids_split_batch_and_recover_individual_items(project, tmp_path):
    import_game(project, tmp_path, count=4)

    class SplitMock(CountingMock):
        async def translate_batch(self, items, **kwargs):
            if len(items) > 1:
                self.calls.append(items)
                return []
            return await super().translate_batch(items, **kwargs)

    provider = SplitMock()
    manager = manager_for(project, provider)
    job = manager.create_job(ProviderConfig(), fast_options())
    result = asyncio.run(manager.run(job))
    assert result.simulated == 4 and result.errors == 0
    assert len(provider.calls) == 7


def test_stop_and_resume_and_crash_left_in_progress_are_recoverable(project, tmp_path):
    import_game(project, tmp_path, count=12)
    provider, control = CountingMock(), JobControl()
    manager = manager_for(project, provider)
    job = manager.create_job(ProviderConfig(), fast_options())
    control.stop()
    assert asyncio.run(manager.run(job, control=control)).status == "cancelled"
    assert not provider.calls
    with project.database.transaction() as connection:
        connection.execute(
            job_items.update().where(job_items.c.job_id == job).values(status="in_progress")
        )
    result = asyncio.run(manager.run(job))
    assert result.simulated == 12 and result.remaining == 0


def test_failed_requests_can_retry_after_reopen_without_overwriting_approved(project, tmp_path):
    report, _, _ = import_game(project, tmp_path, count=3)
    approved = report.units[0]
    project.units.save_translation(
        approved.unit_id, approved.source_text, provider_id="manual", status=UnitStatus.APPROVED
    )

    class FailingMock(CountingMock):
        async def translate_batch(self, items, **kwargs):
            raise ProviderError("authentication")

    manager = manager_for(project, FailingMock())
    job = manager.create_job(ProviderConfig(), fast_options(retry_attempts=1))
    failed = asyncio.run(manager.run(job))
    assert failed.errors == 2 and failed.skipped == 1
    resumed = asyncio.run(manager_for(project, CountingMock()).run(job, retry_failed=True))
    assert resumed.simulated == 2 and resumed.errors == 0 and resumed.skipped == 1
    assert project.units.get(approved.unit_id).status == UnitStatus.APPROVED
    assert project.units.revision_count(approved.unit_id) == 1


def test_locked_glossary_is_restored_but_source_and_old_are_immutable(project, tmp_path):
    report, _, _ = import_game(project, tmp_path, count=1, text="Eileen welcomes [name]")
    glossary = GlossarySystem([GlossaryTerm(source="Eileen", target="إيلين")])
    provider = CountingMock()
    manager = manager_for(project, provider)
    job = manager.create_job(ProviderConfig(), fast_options(), glossary)
    assert asyncio.run(manager.run(job)).simulated == 1
    stored = project.units.get(report.units[0].unit_id)
    assert stored.translation_text == "إيلين welcomes [name]"
    assert stored.source_text == "Eileen welcomes [name]" and stored.old == report.units[0].old
    assert "Eileen" not in provider.calls[0][0]["text"]


def test_api_log_redacts_remote_error_message_and_key(project, tmp_path):
    import_game(project, tmp_path, count=1)
    secret = "SYNTHETIC_PRIVATE_KEY_SHOULD_NEVER_BE_LOGGED"

    class LeakingMock(CountingMock):
        async def translate_batch(self, items, **kwargs):
            raise RuntimeError(secret)

    manager = manager_for(project, LeakingMock())
    job = manager.create_job(ProviderConfig(), fast_options())
    assert asyncio.run(manager.run(job)).errors == 1
    log = (project.path / "logs/api.log").read_text(encoding="utf-8")
    assert "provider_failure" in log and secret not in log and "[name]" not in log


def test_project_lock_prevents_two_simultaneous_managers(project):
    with ProjectJobLock(project.path):
        with pytest.raises(ValueError, match="translation_already_running"):
            with ProjectJobLock(project.path):
                pass


def test_v2_database_migration_has_backup_and_preserves_source(project, tmp_path):
    report, _, _ = import_game(project, tmp_path, count=1)
    with project.database.transaction() as connection:
        from rat.database.tables import jobs, providers

        for table in (job_items, jobs, tm_entries, providers):
            table.drop(connection)
        connection.execute(schema_version.update().values(version=2))
    with ProjectService().open(project.path) as reopened:
        assert (
            reopened.units.get(report.units[0].unit_id).source_sha256
            == report.units[0].source_sha256
        )
        assert TranslationRepository(reopened.database).list_jobs(reopened.project.project_id) == []
    backup = list(project.path.glob("project.sqlite.before-v4-*.bak"))
    assert len(backup) == 1
    with sqlite3.connect(backup[0]) as connection:
        assert connection.execute("select version from schema_version").fetchone()[0] == 2


def test_translation_batch_checkpoint_is_atomic_if_revision_insert_fails(project, tmp_path):
    report, _, _ = import_game(project, tmp_path, count=2)
    with project.database.transaction() as connection:
        connection.exec_driver_sql(
            "CREATE TRIGGER fail_revision BEFORE INSERT ON translation_revisions "
            "BEGIN SELECT RAISE(ABORT,'test'); END"
        )
    manager = manager_for(project, CountingMock())
    job = manager.create_job(ProviderConfig(), fast_options())
    with pytest.raises(ProviderError):
        asyncio.run(manager.run(job))
    assert all(
        project.units.get(source.unit_id).translation_text is None for source in report.units
    )
    with project.database.transaction() as connection:
        assert connection.execute(select(tm_entries)).all() == []
        assert connection.execute(select(units)).mappings().first()["source_data"]["source_text"]


def test_real_provider_job_can_replace_only_unapproved_mock_simulations(project, tmp_path):
    report, _, _ = import_game(project, tmp_path, count=2)
    mock_manager = manager_for(project, CountingMock())
    assert (
        asyncio.run(
            mock_manager.run(mock_manager.create_job(ProviderConfig(), fast_options()))
        ).simulated
        == 2
    )

    class FakeCloud(CountingMock):
        provider_id = "openai"

        async def translate_batch(self, items, **kwargs):
            results = await super().translate_batch(items, **kwargs)
            for result in results:
                result["simulated"] = False
                result["translation_text"] = result["translation_text"].replace("hello", "مرحبا")
            return results

    real = manager_for(project, FakeCloud())
    job = real.create_job(ProviderConfig(provider_id="openai", model="test-model"), fast_options())
    result = asyncio.run(real.run(job))
    assert result.translated == 2 and result.simulated == 0 and result.skipped == 0
    for source in report.units:
        assert "مرحبا" in project.units.get(source.unit_id).translation_text
        assert project.units.revision_count(source.unit_id) == 2


def test_authenticated_failure_stops_future_batches_without_retrying_every_item(project, tmp_path):
    import_game(project, tmp_path, count=20)

    class AuthFailure(CountingMock):
        async def translate_batch(self, items, **kwargs):
            self.calls.append(items)
            raise ProviderError("authentication")

    provider = AuthFailure()
    manager = manager_for(project, provider)
    job = manager.create_job(ProviderConfig(), fast_options())
    result = asyncio.run(manager.run(job))
    assert result.status == "failed" and len(provider.calls) == 1
    assert result.errors == 8 and result.remaining == 12


def test_openai_sdk_mock_transport_end_to_end_translates_ids_restores_and_commits(
    project, tmp_path
):
    report, _, _ = import_game(project, tmp_path, count=3)
    captured = []

    def respond(request):
        data = json.loads(request.content)
        captured.append(data)
        payload = json.loads(data["messages"][1]["content"])
        body = {
            "translations": [
                {"unit_id": item["unit_id"], "text": item["text"].replace("Line", "سطر")}
                for item in reversed(payload["items"])
            ]
        }
        return httpx.Response(
            200,
            json={
                "id": "test",
                "created": 0,
                "object": "chat.completion",
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": json.dumps(body)},
                    }
                ],
            },
        )

    def factory(_provider_id, profile, **_kwargs):
        client = AsyncOpenAI(
            api_key="SYNTHETIC",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        )
        return OpenAIProvider(profile, "SYNTHETIC", client=client)

    manager = TranslationManager(project.path, provider_factory=factory)
    job = manager.create_job(
        ProviderConfig(provider_id="openai", model="test-model"), fast_options()
    )
    result = asyncio.run(manager.run(job))
    assert result.translated == 3 and result.errors == 0 and result.simulated == 0
    assert "[name]" not in json.dumps(captured)
    for source in report.units:
        translation = project.units.get(source.unit_id).translation_text
        assert translation == source.source_text.replace("Line", "سطر")


def test_project_lock_cannot_write_through_a_hard_link_to_a_game_file(project, tmp_path):
    original = tmp_path / "original.rpy"
    original.write_bytes(b"")
    lock = project.path / ".translation.lock"
    os.link(original, lock)
    with pytest.raises(ValueError, match="unsafe_translation_lock"):
        with ProjectJobLock(project.path):
            pass
    assert original.read_bytes() == b""
