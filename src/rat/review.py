from rat.database.review_repository import ReviewConflict, ReviewRepository
from rat.domain.review import ReviewStatus
from rat.domain.translation import TranslationOptions
from rat.projects import ProjectService
from rat.translation.context import ContextBuilder
from rat.translation.orchestrator import TranslationManager
from rat.translation.quality import QAEngine


class ReviewService:
    def __init__(self, project_dir):
        self.project_dir = project_dir
        self.qa = QAEngine()

    def list_units(self):
        with ProjectService().open(self.project_dir) as session:
            records = ReviewRepository(session.database).list(session.project.project_id)
        results = self.qa.audit(records)
        return tuple(
            record.model_copy(update={"qa": results[record.unit_id]}) for record in records
        )

    def save(self, unit_id, text, *, expected_etag=None, provider_id="manual"):
        return self._change(
            [unit_id],
            "save",
            text=text,
            expected={unit_id: expected_etag} if expected_etag else None,
            provider_id=provider_id,
        )

    def action(self, unit_ids, action, *, expected=None):
        return self._change(unit_ids, action, expected=expected)

    def _change(self, unit_ids, action, *, text=None, expected=None, provider_id="manual"):
        if not unit_ids or len(unit_ids) != len(set(unit_ids)):
            raise ValueError("select_unique_units")
        with ProjectService().open(self.project_dir) as session:
            repository = ReviewRepository(session.database)
            current = {
                record.unit_id: record for record in repository.list(session.project.project_id)
            }
            changes, signatures = [], {}
            for unit_id in unit_ids:
                if unit_id not in current:
                    raise ReviewConflict("source_not_active")
                record = current[unit_id]
                signature = repository.etag(record)
                if expected and expected.get(unit_id) != signature:
                    raise ReviewConflict("review_changed_reload_first")
                signatures[unit_id] = signature
                if record.locked and action != "unlock":
                    raise ValueError("unit_locked")
                if action == "save":
                    if record.state == ReviewStatus.APPROVED:
                        raise ValueError("reject_approved_before_editing")
                    qa = self.qa.check(record.source, text)
                    changes.append(
                        record.model_copy(
                            update={
                                "translation_text": text,
                                "provider_id": provider_id,
                                "state": ReviewStatus.NEEDS_REVIEW
                                if qa.issues
                                else ReviewStatus.TRANSLATED,
                                "skipped": False,
                            }
                        )
                    )
                elif action == "approve":
                    if (
                        record.skipped
                        or not self.qa.check(record.source, record.translation_text).valid
                    ):
                        raise ValueError("qa_blocks_approval")
                    changes.append(record.model_copy(update={"state": ReviewStatus.APPROVED}))
                elif action == "reject":
                    changes.append(
                        record.model_copy(
                            update={"state": ReviewStatus.NEEDS_REVIEW, "skipped": False}
                        )
                    )
                elif action == "skip":
                    changes.append(record.model_copy(update={"skipped": True}))
                elif action in {"lock", "unlock"}:
                    changes.append(record.model_copy(update={"locked": action == "lock"}))
                else:
                    raise ValueError("unknown_review_action")
            repository.commit(session.project.project_id, changes, signatures)
        return self.list_units()

    def context(self, unit_id, *, records=None):
        records = self.list_units() if records is None else records
        source = next(record.source for record in records if record.unit_id == unit_id)
        return ContextBuilder().build(source, [record.source for record in records])

    def alternatives(self, unit_id):
        with ProjectService().open(self.project_dir) as session:
            return ReviewRepository(session.database).alternatives(
                session.project.project_id, unit_id
            )

    def apply_alternative(self, alternative_id, *, expected_etag=None):
        with ProjectService().open(self.project_dir) as session:
            alternative = ReviewRepository(session.database).alternative(
                session.project.project_id, alternative_id
            )
        if alternative is None:
            raise ValueError("alternative_not_found")
        record = next((r for r in self.list_units() if r.unit_id == alternative.unit_id), None)
        if record is None or alternative.source_sha256 != record.source.source_sha256:
            raise ReviewConflict("alternative_source_changed")
        return self.save(
            record.unit_id,
            alternative.text,
            expected_etag=expected_etag,
            provider_id=alternative.provider_id,
        )

    async def retranslate(
        self,
        unit_ids,
        profile,
        *,
        count=1,
        manager_factory=TranslationManager,
        control=None,
        on_progress=None,
    ):
        if not 1 <= count <= 5:
            raise ValueError("alternative_count_limit")
        available = {record.unit_id: record for record in self.list_units()}
        if not unit_ids or any(
            unit_id not in available or available[unit_id].locked or available[unit_id].skipped
            for unit_id in unit_ids
        ):
            raise ValueError("selection_contains_locked_or_skipped_units")
        results = []
        for index in range(count):
            if control and control.requested_status:
                break
            manager = manager_factory(self.project_dir)
            options = TranslationOptions(
                alternatives_only=True, use_translation_memory=False, variant_index=index + 1
            )
            job_id = manager.create_job(profile, options, unit_ids=unit_ids)
            results.append(await manager.run(job_id, control=control, on_progress=on_progress))
        return results
