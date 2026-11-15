from pathlib import Path

import pytest
from sqlalchemy import select

from rat.database.review_repository import ReviewConflict, ReviewRepository
from rat.database.tables import translations, units
from rat.domain.enums import UnitStatus
from rat.extraction.scanner import GameImportService
from rat.review import ReviewService


@pytest.fixture
def review(project):
    GameImportService().scan(project.path, Path(__file__).parents[1] / "fixtures/game_with_tl")
    return ReviewService(project.path)


def test_manual_edit_reopen_history_and_original_source_remain_immutable(project, review):
    record = review.list_units()[0]
    text = record.source.source_text.replace("Hello", "مرحبًا")
    before = record.source.model_dump()
    review.save(record.unit_id, text, expected_etag=ReviewRepository.etag(record))
    loaded = next(
        row for row in ReviewService(project.path).list_units() if row.unit_id == record.unit_id
    )
    assert loaded.translation_text == text and loaded.source.model_dump() == before
    assert loaded.revision == 1
    with project.database.transaction() as connection:
        stored = connection.execute(
            select(units.c.source_data).where(units.c.unit_id == record.unit_id)
        ).scalar_one()
    assert stored["source_sha256"] == record.source.source_sha256
    assert (
        len(ReviewRepository(project.database).history(project.project.project_id, record.unit_id))
        == 2
    )


def test_qa_blocks_approval_and_bulk_action_is_atomic(project, review):
    records = review.list_units()
    bad = next(row for row in records if "[player_name]" in row.source.source_text)
    good = next(row for row in records if row.unit_id != bad.unit_id)
    review.save(bad.unit_id, "فقد المتغيرات")
    review.save(good.unit_id, good.source.source_text)
    with pytest.raises(ValueError, match="qa_blocks_approval"):
        review.action([good.unit_id, bad.unit_id], "approve")
    assert all(row.state != "approved" for row in review.list_units())


def test_approve_reject_edit_lock_unlock_skip_preserve_approved_history(project, review):
    record = review.list_units()[0]
    review.save(record.unit_id, record.source.source_text)
    review.action([record.unit_id], "approve")
    with pytest.raises(ValueError, match="reject_approved"):
        review.save(record.unit_id, "changed")
    review.action([record.unit_id], "lock")
    row = next(row for row in review.list_units() if row.unit_id == record.unit_id)
    assert row.status == "locked" and row.state == "approved"
    with pytest.raises(ValueError, match="unit_locked"):
        review.action([record.unit_id], "reject")
    review.action([record.unit_id], "unlock")
    review.action([record.unit_id], "reject")
    review.save(record.unit_id, record.source.source_text.replace("Hello", "أهلًا"))
    review.action([record.unit_id], "skip")
    assert next(row for row in review.list_units() if row.unit_id == record.unit_id).skipped
    history = ReviewRepository(project.database).history(project.project.project_id, record.unit_id)
    assert any(row["payload"]["state"] == "approved" for row in history)


def test_stale_editor_cannot_overwrite_another_save(project, review):
    record = review.list_units()[0]
    token = ReviewRepository.etag(record)
    review.save(record.unit_id, record.source.source_text, expected_etag=token)
    with pytest.raises(ReviewConflict, match="reload"):
        review.save(record.unit_id, "stale", expected_etag=token)


def test_legacy_approved_row_is_never_replaced_by_explicit_review(project, review):
    source = review.list_units()[0].source
    project.units.save_translation(
        source.unit_id, source.source_text, provider_id="manual", status=UnitStatus.APPROVED
    )
    with project.database.transaction() as connection:
        original = dict(
            connection.execute(select(translations).where(translations.c.unit_id == source.unit_id))
            .mappings()
            .one()
        )
    review.action([source.unit_id], "reject")
    review.save(source.unit_id, source.source_text.replace("Hello", "مرحبًا"))
    with project.database.transaction() as connection:
        assert (
            dict(
                connection.execute(
                    select(translations).where(translations.c.unit_id == source.unit_id)
                )
                .mappings()
                .one()
            )
            == original
        )


def test_low_level_api_cannot_approve_invalid_or_bypass_review_lock(project, review):
    source = next(
        row.source for row in review.list_units() if "[player_name]" in row.source.source_text
    )
    with pytest.raises(ValueError, match="QA"):
        project.units.save_translation(
            source.unit_id, "missing placeholders", provider_id="manual", status=UnitStatus.APPROVED
        )
    review.action([source.unit_id], "lock")
    with pytest.raises(ValueError, match="ReviewService"):
        project.units.save_translation(source.unit_id, source.source_text, provider_id="mock")


def test_reimport_preserves_review_but_changed_source_never_reuses_approved_draft(
    project, tmp_path
):
    import shutil

    game = tmp_path / "original"
    shutil.copytree(Path(__file__).parents[1] / "fixtures/game_with_tl", game)
    service = GameImportService()
    service.scan(project.path, game)
    review = ReviewService(project.path)
    record = next(r for r in review.list_units() if "[player_name]" in r.source.source_text)
    review.save(record.unit_id, record.source.source_text)
    review.action([record.unit_id], "approve")
    expected = review.list_units()
    service.scan(project.path, game)
    assert review.list_units() == expected
    script = game / "game/script.rpy"
    script.write_text(
        script.read_text(encoding="utf-8").replace("Hello,", "Changed hello,"), encoding="utf-8"
    )
    service.scan(project.path, game)
    current = review.list_units()
    assert record.unit_id not in {r.unit_id for r in current}
    replacement = next(r for r in current if "[player_name]" in r.source.source_text)
    assert replacement.translation_text is None and replacement.state == "untranslated"
    assert any(
        item["payload"]["state"] == "approved"
        for item in ReviewRepository(project.database).history(
            project.project.project_id, record.unit_id
        )
    )
