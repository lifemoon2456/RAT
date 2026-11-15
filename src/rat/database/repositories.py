from datetime import UTC, datetime

from sqlalchemy import func, select

from rat.database.session import Database
from rat.database.tables import projects, translation_revisions, translations, unit_reviews, units
from rat.domain.enums import UnitStatus
from rat.domain.models import Project, SourceUnit, TranslationUnit


class ProjectRepository:
    def __init__(self, database: Database):
        self.database = database

    def add(self, project: Project) -> None:
        with self.database.transaction() as connection:
            connection.execute(projects.insert().values(**project.model_dump(mode="json")))

    def get(self, project_id: str) -> Project:
        with self.database.transaction() as connection:
            row = (
                connection.execute(select(projects).where(projects.c.project_id == project_id))
                .mappings()
                .one()
            )
            return Project.model_validate(dict(row))


class UnitRepository:
    """Persistence only. No extraction, automated approval, or export capability."""

    def __init__(self, database: Database):
        self.database = database

    def add_source(self, source: SourceUnit) -> None:
        # Revalidate to reject unvalidated Pydantic model_copy updates.
        source = SourceUnit.model_validate(source.model_dump())
        with self.database.transaction() as connection:
            connection.execute(
                units.insert().values(
                    unit_id=source.unit_id,
                    project_id=source.project_id,
                    location_key=source.location_key,
                    source_data=source.model_dump(mode="json"),
                )
            )

    def get(self, unit_id: str) -> TranslationUnit:
        with self.database.transaction() as connection:
            row = (
                connection.execute(
                    select(
                        units.c.source_data, translations.c.translation_text, translations.c.status
                    )
                    .outerjoin(translations)
                    .where(units.c.unit_id == unit_id)
                )
                .mappings()
                .one()
            )
            return TranslationUnit.model_validate(
                {
                    **row["source_data"],
                    "translation_text": row["translation_text"],
                    "status": row["status"] or UnitStatus.PENDING,
                }
            )

    def count(self, project_id: str) -> int:
        with self.database.transaction() as connection:
            return connection.execute(
                select(func.count()).select_from(units).where(units.c.project_id == project_id)
            ).scalar_one()

    def save_translation(
        self,
        unit_id: str,
        text: str | None,
        *,
        provider_id: str,
        status: UnitStatus = UnitStatus.NEEDS_REVIEW,
    ) -> None:
        status = UnitStatus(status)
        if status == UnitStatus.VALIDATED:
            raise ValueError(
                "Full Ren'Py export validation is unavailable; text protection is only one check."
            )
        if status in {UnitStatus.TRANSLATED, UnitStatus.APPROVED} and text is None:
            raise ValueError("This status requires a translation.")
        if status == UnitStatus.APPROVED:
            from rat.translation.quality import QAEngine

            if not QAEngine().check(self.get(unit_id), text).valid:
                raise ValueError("QA blocks approval of this translation.")
        with self.database.transaction() as connection:
            if connection.execute(
                select(unit_reviews.c.unit_id).where(unit_reviews.c.unit_id == unit_id)
            ).scalar_one_or_none():
                raise ValueError("Use ReviewService for reviewed or locked units.")
            current = (
                connection.execute(select(translations).where(translations.c.unit_id == unit_id))
                .mappings()
                .one_or_none()
            )
            if current and current["status"] == UnitStatus.APPROVED:
                raise ValueError("Approved translations cannot be overwritten.")
            values = {"translation_text": text, "provider_id": provider_id, "status": status.value}
            if current:
                connection.execute(
                    translations.update().where(translations.c.unit_id == unit_id).values(**values)
                )
            else:
                connection.execute(translations.insert().values(unit_id=unit_id, **values))
            # The new version is recorded in the same transaction as the current result.
            connection.execute(
                translation_revisions.insert().values(
                    unit_id=unit_id, **values, created_at=datetime.now(UTC).isoformat()
                )
            )

    def revision_count(self, unit_id: str) -> int:
        with self.database.transaction() as connection:
            return connection.execute(
                select(func.count())
                .select_from(translation_revisions)
                .where(translation_revisions.c.unit_id == unit_id)
            ).scalar_one()
