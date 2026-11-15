from datetime import UTC, datetime

from sqlalchemy import select

from rat.database.session import Database
from rat.database.tables import (
    game_imports,
    source_files,
    translation_revisions,
    translations,
    unit_discovery,
    units,
)
from rat.domain.discovery import ImportReport, UnitOrigin
from rat.domain.models import SourceUnit, TranslationUnit


class DiscoveryRepository:
    def __init__(self, database: Database):
        self.database = database

    def load(self, project_id: str) -> ImportReport | None:
        with self.database.transaction() as connection:
            payload = connection.execute(
                select(game_imports.c.payload).where(game_imports.c.project_id == project_id)
            ).scalar_one_or_none()
            if payload is None:
                return None
            rows = (
                connection.execute(
                    select(
                        units.c.source_data,
                        translations.c.translation_text,
                        translations.c.status,
                        unit_discovery.c.origin,
                    )
                    .select_from(units.join(unit_discovery).outerjoin(translations))
                    .where(units.c.project_id == project_id, unit_discovery.c.active == 1)
                    .order_by(units.c.unit_id)
                )
                .mappings()
                .all()
            )
        collected = [
            TranslationUnit.model_validate(
                {
                    **row["source_data"],
                    "confidence": row["origin"].get("confidence")
                    or row["source_data"]["confidence"],
                    "translation_text": row["translation_text"],
                    "status": row["status"] or "pending",
                }
            )
            for row in rows
        ]
        collected.sort(key=lambda item: (item.source_relpath, item.source_line or 0, item.unit_id))
        return ImportReport.model_validate(
            {
                **payload,
                "units": collected,
                "origins": [row["origin"] for row in rows],
            }
        )

    def save(
        self,
        project_id: str,
        report: ImportReport,
        candidates: list[tuple[SourceUnit, UnitOrigin, str | None]],
    ) -> ImportReport:
        added = reused = changed = 0
        with self.database.transaction() as connection:
            existing_rows = (
                connection.execute(select(units).where(units.c.project_id == project_id))
                .mappings()
                .all()
            )
            existing = {row["location_key"]: row for row in existing_rows}
            previous = [row["source_data"] for row in existing_rows]
            connection.execute(
                unit_discovery.update()
                .where(
                    unit_discovery.c.unit_id.in_(
                        select(units.c.unit_id).where(units.c.project_id == project_id)
                    )
                )
                .values(active=0)
            )
            for source, origin, translated in candidates:
                source = SourceUnit.model_validate(source.model_dump())
                if source.project_id != project_id:
                    raise ValueError("Source belongs to a different project.")
                row = existing.get(source.location_key)
                if row:
                    unit_id = row["unit_id"]
                    reused += 1
                else:
                    unit_id = source.unit_id
                    changed += int(
                        any(
                            (
                                item.get("source_location") == source.source_location
                                or (
                                    item["source_relpath"] == source.source_relpath
                                    and item["source_line"] == source.source_line
                                    and item["kind"] == source.kind.value
                                )
                            )
                            and item["source_text"] != source.source_text
                            for item in previous
                        )
                    )
                    connection.execute(
                        units.insert().values(
                            unit_id=unit_id,
                            project_id=project_id,
                            location_key=source.location_key,
                            source_data=source.model_dump(mode="json"),
                        )
                    )
                    added += 1
                origin = origin.model_copy(update={"unit_id": unit_id})
                discovered = connection.execute(
                    select(unit_discovery.c.origin).where(unit_discovery.c.unit_id == unit_id)
                ).scalar_one_or_none()
                if discovered:
                    if discovered.get("confidence") == "official_template":
                        origin = origin.model_copy(update={"confidence": "official_template"})
                    connection.execute(
                        unit_discovery.update()
                        .where(unit_discovery.c.unit_id == unit_id)
                        .values(active=1, origin=origin.model_dump(mode="json"))
                    )
                else:
                    connection.execute(
                        unit_discovery.insert().values(
                            unit_id=unit_id, active=1, origin=origin.model_dump(mode="json")
                        )
                    )
                if translated:
                    current = connection.execute(
                        select(translations.c.unit_id).where(translations.c.unit_id == unit_id)
                    ).scalar_one_or_none()
                    if current is None:
                        values = dict(
                            unit_id=unit_id,
                            translation_text=translated,
                            provider_id="existing_arabic_template",
                            status="needs_review",
                        )
                        connection.execute(translations.insert().values(**values))
                        connection.execute(
                            translation_revisions.insert().values(
                                **values, created_at=datetime.now(UTC).isoformat()
                            )
                        )
            connection.execute(source_files.delete().where(source_files.c.project_id == project_id))
            for item in report.inventory.files:
                connection.execute(
                    source_files.insert().values(
                        project_id=project_id,
                        relpath=item.relpath,
                        payload=item.model_dump(mode="json"),
                    )
                )
            payload = report.model_copy(
                update={
                    "added": added,
                    "reused": reused,
                    "changed": changed,
                }
            ).model_dump(mode="json", exclude={"units", "origins", "protection"})
            connection.execute(game_imports.delete().where(game_imports.c.project_id == project_id))
            connection.execute(game_imports.insert().values(project_id=project_id, payload=payload))
        result = self.load(project_id)
        assert result is not None
        return result
