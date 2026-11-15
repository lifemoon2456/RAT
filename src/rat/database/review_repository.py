import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import or_, select

from rat.database.tables import (
    job_items,
    jobs,
    review_revisions,
    translation_alternatives,
    translations,
    unit_discovery,
    unit_reviews,
    units,
)
from rat.domain.models import TranslationUnit
from rat.domain.review import EditorUnit, TranslationAlternative


class ReviewConflict(ValueError):
    pass


def stamp():
    return datetime.now(UTC).isoformat()


class ReviewRepository:
    def __init__(self, database):
        self.database = database

    def list(self, project_id, *, connection=None):
        if connection is None:
            with self.database.transaction() as opened:
                return self.list(project_id, connection=opened)
        query = (
            select(
                units.c.source_data,
                translations.c.translation_text,
                translations.c.provider_id,
                translations.c.status,
                unit_reviews.c.payload,
            )
            .select_from(
                units.outerjoin(translations).outerjoin(unit_reviews).outerjoin(unit_discovery)
            )
            .where(
                units.c.project_id == project_id,
                or_(unit_discovery.c.active == 1, unit_discovery.c.active.is_(None)),
            )
        )
        failed = {}
        for item in connection.execute(
            select(job_items.c.unit_id, job_items.c.status)
            .join(jobs)
            .where(jobs.c.project_id == project_id)
            .order_by(jobs.c.updated_at)
        ).mappings():
            failed[item["unit_id"]] = item["status"]
        records = []
        mapping = {
            "pending": "untranslated",
            "in_progress": "untranslated",
            "translated": "translated",
            "validated": "translated",
            "needs_review": "needs_review",
            "approved": "approved",
            "failed": "error",
            "excluded": "needs_review",
        }
        for row in connection.execute(query).mappings():
            source = TranslationUnit.model_validate(
                {
                    **row["source_data"],
                    "translation_text": row["translation_text"],
                    "status": row["status"] or "pending",
                }
            )
            payload = row["payload"]
            if payload and payload["source_sha256"] != source.source_sha256:
                raise ReviewConflict("review_source_mismatch")
            data = payload or {
                "translation_text": row["translation_text"],
                "provider_id": row["provider_id"] or "",
                "state": mapping[row["status"] or "pending"],
                "locked": False,
                "skipped": row["status"] == "excluded",
                "revision": 0,
            }
            if (
                not payload
                and row["translation_text"] is None
                and failed.get(source.unit_id) in {"failed", "needs_review"}
            ):
                data = {**data, "state": "error"}
            records.append(
                EditorUnit(
                    source=source,
                    **{key: value for key, value in data.items() if key != "source_sha256"},
                )
            )
        return sorted(
            records,
            key=lambda record: (
                record.source.source_relpath,
                record.source.source_line or 0,
                record.unit_id,
            ),
        )

    @staticmethod
    def etag(record: EditorUnit):
        data = record.model_dump(mode="json", exclude={"qa"})
        return hashlib.sha256(
            json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

    def commit(self, project_id, changes, expected):
        with self.database.transaction() as connection:
            current = {
                record.unit_id: record for record in self.list(project_id, connection=connection)
            }
            for record in changes:
                old = current.get(record.unit_id)
                if old is None or self.etag(old) != expected[record.unit_id]:
                    raise ReviewConflict("review_changed_reload_first")
            for record in changes:
                payload = record.model_dump(mode="json", exclude={"source", "qa"})
                payload["source_sha256"] = record.source.source_sha256
                payload["revision"] = current[record.unit_id].revision + 1
                # Every transition is append-only history, including the first legacy approval.
                if current[record.unit_id].revision == 0:
                    previous = current[record.unit_id].model_dump(
                        mode="json", exclude={"source", "qa"}
                    )
                    previous["source_sha256"] = record.source.source_sha256
                    connection.execute(
                        review_revisions.insert().values(
                            unit_id=record.unit_id, payload=previous, created_at=stamp()
                        )
                    )
                exists = connection.execute(
                    select(unit_reviews.c.unit_id).where(unit_reviews.c.unit_id == record.unit_id)
                ).scalar_one_or_none()
                if exists:
                    connection.execute(
                        unit_reviews.update()
                        .where(unit_reviews.c.unit_id == record.unit_id)
                        .values(payload=payload)
                    )
                else:
                    connection.execute(
                        unit_reviews.insert().values(unit_id=record.unit_id, payload=payload)
                    )
                connection.execute(
                    review_revisions.insert().values(
                        unit_id=record.unit_id, payload=payload, created_at=stamp()
                    )
                )

    def alternatives(self, project_id, unit_id):
        with self.database.transaction() as connection:
            query = (
                select(translation_alternatives)
                .join(units)
                .where(
                    units.c.project_id == project_id, translation_alternatives.c.unit_id == unit_id
                )
                .order_by(translation_alternatives.c.created_at)
            )
            return [
                TranslationAlternative.model_validate(
                    {key: value for key, value in row.items() if key != "job_id"}
                )
                for row in connection.execute(query).mappings()
            ]

    def alternative(self, project_id, alternative_id):
        with self.database.transaction() as connection:
            row = (
                connection.execute(
                    select(translation_alternatives)
                    .join(units)
                    .where(
                        units.c.project_id == project_id,
                        translation_alternatives.c.alternative_id == alternative_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            return (
                TranslationAlternative.model_validate(
                    {key: value for key, value in row.items() if key != "job_id"}
                )
                if row
                else None
            )

    def history(self, project_id, unit_id):
        with self.database.transaction() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    select(review_revisions)
                    .join(units)
                    .where(units.c.project_id == project_id, review_revisions.c.unit_id == unit_id)
                    .order_by(review_revisions.c.revision_id)
                ).mappings()
            ]
