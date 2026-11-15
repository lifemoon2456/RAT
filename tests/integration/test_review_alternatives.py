import asyncio
from pathlib import Path

import pytest
from sqlalchemy import select

from rat.database.review_repository import ReviewRepository
from rat.database.tables import tm_entries, translation_alternatives
from rat.domain.translation import ProviderConfig, TranslationOptions
from rat.extraction.scanner import GameImportService
from rat.providers.mock import MockProvider
from rat.review import ReviewService
from rat.translation.orchestrator import TranslationManager


class CountingMock(MockProvider):
    def __init__(self):
        self.calls = []

    async def translate_batch(self, items, **kwargs):
        self.calls.append((items, kwargs))
        return await super().translate_batch(items, **kwargs)


def setup(project):
    GameImportService().scan(project.path, Path(__file__).parents[1] / "fixtures/game_with_tl")
    review = ReviewService(project.path)
    return review, CountingMock()


def test_selected_retranslation_keeps_approval_and_saves_multiple_alternatives(project):
    review, provider = setup(project)
    record = review.list_units()[0]
    review.save(record.unit_id, record.source.source_text)
    review.action([record.unit_id], "approve")
    before = review.list_units()

    def factory(path):
        return TranslationManager(path, provider_factory=lambda *_a, **_kw: provider)

    results = asyncio.run(
        review.retranslate([record.unit_id], ProviderConfig(), count=2, manager_factory=factory)
    )
    assert all(result.simulated == 1 and result.errors == 0 for result in results)
    assert len(provider.calls) == 2 and review.list_units() == before
    assert {call[1]["settings"]["variant_index"] for call in provider.calls} == {1, 2}
    alternatives = review.alternatives(record.unit_id)
    assert len(alternatives) == 2 and all(item.simulated for item in alternatives)
    with project.database.transaction() as connection:
        assert len(connection.execute(select(translation_alternatives)).all()) == 2
        assert connection.execute(select(tm_entries)).all() == []
    with pytest.raises(ValueError, match="reject_approved"):
        review.apply_alternative(alternatives[0].alternative_id)
    review.action([record.unit_id], "reject")
    current = next(row for row in review.list_units() if row.unit_id == record.unit_id)
    review.apply_alternative(
        alternatives[0].alternative_id, expected_etag=ReviewRepository.etag(current)
    )
    chosen = next(row for row in review.list_units() if row.unit_id == record.unit_id)
    assert chosen.translation_text == alternatives[0].text and chosen.state != "approved"


def test_job_created_before_editor_lock_cannot_overwrite_it(project):
    review, provider = setup(project)
    manager = TranslationManager(project.path, provider_factory=lambda *_a, **_kw: provider)
    record = review.list_units()[0]
    job = manager.create_job(ProviderConfig(), TranslationOptions(), unit_ids=[record.unit_id])
    review.action([record.unit_id], "lock")
    result = asyncio.run(manager.run(job))
    assert result.skipped == 1 and not provider.calls
    with pytest.raises(ValueError, match="locked"):
        asyncio.run(review.retranslate([record.unit_id], ProviderConfig()))


def test_retranslation_uses_full_neighbor_context_and_manual_draft_is_preserved(project):
    review, provider = setup(project)
    record = review.list_units()[1]
    review.save(record.unit_id, record.source.source_text)
    manager = TranslationManager(project.path, provider_factory=lambda *_a, **_kw: provider)
    job = manager.create_job(ProviderConfig(), TranslationOptions(), unit_ids=[record.unit_id])
    assert asyncio.run(manager.run(job)).skipped == 1

    def factory(path):
        return TranslationManager(path, provider_factory=lambda *_a, **_kw: provider)

    asyncio.run(review.retranslate([record.unit_id], ProviderConfig(), manager_factory=factory))
    item = provider.calls[0][0][0]
    assert item["context"]["before"] or item["context"]["after"]


def test_editor_lock_during_provider_request_is_checked_again_at_commit(project):
    review, _provider = setup(project)
    record = review.list_units()[0]

    class LockDuringRequest(MockProvider):
        async def translate_batch(self, items, **kwargs):
            review.action([record.unit_id], "lock")
            return await super().translate_batch(items, **kwargs)

    manager = TranslationManager(
        project.path, provider_factory=lambda *_a, **_kw: LockDuringRequest()
    )
    job = manager.create_job(ProviderConfig(), TranslationOptions(), unit_ids=[record.unit_id])
    result = asyncio.run(manager.run(job))
    assert result.skipped == 1 and project.units.revision_count(record.unit_id) == 0
