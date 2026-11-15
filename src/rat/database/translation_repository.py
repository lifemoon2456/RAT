from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select

from rat.database.tables import (
    job_items,
    jobs,
    providers,
    tm_entries,
    translation_alternatives,
    translation_revisions,
    translations,
    unit_discovery,
    unit_reviews,
)
from rat.domain.translation import JobProgress, ProviderConfig


def now():
    return datetime.now(UTC).isoformat()


class TranslationRepository:
    def __init__(self, database):
        self.database = database

    def profiles(self, project_id):
        with self.database.transaction() as connection:
            return [
                ProviderConfig.model_validate(row)
                for row in connection.execute(
                    select(providers.c.config).where(providers.c.project_id == project_id)
                ).scalars()
            ]

    def save_profile(self, project_id, config):
        config = ProviderConfig.model_validate(config.model_dump())
        with self.database.transaction() as connection:
            old = (
                connection.execute(
                    select(providers).where(providers.c.profile_id == config.profile_id)
                )
                .mappings()
                .one_or_none()
            )
            if old and (
                old["project_id"] != project_id
                or old["config"]["provider_id"] != config.provider_id
                or old["config"]["base_url"] != config.base_url
            ):
                raise ValueError("Use a new profile identity when changing an endpoint.")
            if old:
                connection.execute(
                    providers.update()
                    .where(providers.c.profile_id == config.profile_id)
                    .values(config=config.model_dump(mode="json"))
                )
            else:
                connection.execute(
                    providers.insert().values(
                        profile_id=config.profile_id,
                        project_id=project_id,
                        config=config.model_dump(mode="json"),
                    )
                )

    def create_job(self, project_id, profile, options, glossary, sources):
        job_id = uuid4().hex
        with self.database.transaction() as connection:
            connection.execute(
                jobs.insert().values(
                    job_id=job_id,
                    project_id=project_id,
                    profile=profile.model_dump(mode="json"),
                    options=options.model_dump(mode="json"),
                    glossary=[term.model_dump(mode="json") for term in glossary],
                    status="queued",
                    created_at=now(),
                    updated_at=now(),
                )
            )
            for source in sources:
                current = (
                    connection.execute(
                        select(translations).where(translations.c.unit_id == source.unit_id)
                    )
                    .mappings()
                    .one_or_none()
                )
                skip = self._guard(
                    connection,
                    source.unit_id,
                    current,
                    profile.provider_id,
                    options.alternatives_only,
                )
                connection.execute(
                    job_items.insert().values(
                        job_id=job_id,
                        unit_id=source.unit_id,
                        source_sha256=source.source_sha256,
                        status="skipped" if skip else "pending",
                    )
                )
        return job_id

    @staticmethod
    def preserved(current, provider_id):
        if not current:
            return False
        return current["status"] in {"approved", "excluded"} or (
            current["translation_text"] is not None
            and not (current["provider_id"] == "mock" and provider_id != "mock")
        )

    def _guard(self, connection, unit_id, current, provider_id, alternatives_only=False):
        review = connection.execute(
            select(unit_reviews.c.payload).where(unit_reviews.c.unit_id == unit_id)
        ).scalar_one_or_none()
        if review and (review["locked"] or review["skipped"]):
            return True
        if alternatives_only:
            return bool(current and current["status"] == "excluded")
        return review is not None or self.preserved(current, provider_id)

    def should_preserve(self, unit_id, provider_id, *, alternatives_only=False):
        with self.database.transaction() as connection:
            current = (
                connection.execute(select(translations).where(translations.c.unit_id == unit_id))
                .mappings()
                .one_or_none()
            )
            return self._guard(connection, unit_id, current, provider_id, alternatives_only)

    def job(self, project_id, job_id):
        with self.database.transaction() as connection:
            return dict(
                connection.execute(
                    select(jobs).where(jobs.c.project_id == project_id, jobs.c.job_id == job_id)
                )
                .mappings()
                .one()
            )

    def list_jobs(self, project_id):
        with self.database.transaction() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    select(jobs)
                    .where(jobs.c.project_id == project_id)
                    .order_by(jobs.c.created_at.desc())
                ).mappings()
            ]

    def items(self, job_id):
        with self.database.transaction() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    select(job_items)
                    .where(job_items.c.job_id == job_id)
                    .order_by(job_items.c.unit_id)
                ).mappings()
            ]

    def status(self, job_id, status):
        with self.database.transaction() as connection:
            connection.execute(
                jobs.update().where(jobs.c.job_id == job_id).values(status=status, updated_at=now())
            )

    def recover(self, job_id, *, retry_failed=False):
        statuses = ["in_progress"] + (["failed", "needs_review"] if retry_failed else [])
        with self.database.transaction() as connection:
            connection.execute(
                job_items.update()
                .where(job_items.c.job_id == job_id, job_items.c.status.in_(statuses))
                .values(status="pending", error_code=None)
            )

    def prepare(self, job_id, unit_id, request):
        with self.database.transaction() as connection:
            connection.execute(
                job_items.update()
                .where(job_items.c.job_id == job_id, job_items.c.unit_id == unit_id)
                .values(request=request, status="pending")
            )

    def start_batch(self, job_id, ids):
        with self.database.transaction() as connection:
            connection.execute(
                job_items.update()
                .where(job_items.c.job_id == job_id, job_items.c.unit_id.in_(ids))
                .values(status="in_progress")
            )

    def memory(self, project_id, key):
        with self.database.transaction() as connection:
            row = (
                connection.execute(
                    select(tm_entries).where(
                        tm_entries.c.project_id == project_id, tm_entries.c.cache_key == key
                    )
                )
                .mappings()
                .one_or_none()
            )
            return dict(row) if row else None

    def commit_batch(self, project_id, job_id, results):
        """Translation, revision, memory and checkpoint share one transaction."""
        with self.database.transaction() as connection:
            profile = connection.execute(
                select(jobs.c.profile).where(
                    jobs.c.job_id == job_id, jobs.c.project_id == project_id
                )
            ).scalar_one()
            options = connection.execute(
                select(jobs.c.options).where(jobs.c.job_id == job_id)
            ).scalar_one()
            for result in results:
                unit_id = result["unit_id"]
                current = (
                    connection.execute(
                        select(translations).where(translations.c.unit_id == unit_id)
                    )
                    .mappings()
                    .one_or_none()
                )
                active = connection.execute(
                    select(unit_discovery.c.active).where(unit_discovery.c.unit_id == unit_id)
                ).scalar_one_or_none()
                state, error = result["status"], result.get("error_code")
                if active == 0:
                    state, error = "needs_review", "source_changed"
                elif self._guard(
                    connection,
                    unit_id,
                    current,
                    profile["provider_id"],
                    options.get("alternatives_only", False),
                ):
                    state, error = "skipped", None
                if state in {"completed", "simulated"} and options.get("alternatives_only", False):
                    if (
                        connection.execute(
                            select(translation_alternatives.c.alternative_id).where(
                                translation_alternatives.c.job_id == job_id,
                                translation_alternatives.c.unit_id == unit_id,
                            )
                        ).scalar_one_or_none()
                        is None
                    ):
                        source_hash = connection.execute(
                            select(job_items.c.source_sha256).where(
                                job_items.c.job_id == job_id, job_items.c.unit_id == unit_id
                            )
                        ).scalar_one()
                        connection.execute(
                            translation_alternatives.insert().values(
                                alternative_id=uuid4().hex,
                                unit_id=unit_id,
                                source_sha256=source_hash,
                                text=result["text"],
                                provider_id=result["provider_id"],
                                simulated=int(state == "simulated"),
                                job_id=job_id,
                                created_at=now(),
                            )
                        )
                elif state in {"completed", "simulated"}:
                    values = dict(
                        translation_text=result["text"],
                        provider_id=result["provider_id"],
                        status="needs_review" if state == "simulated" else "translated",
                    )
                    if current:
                        connection.execute(
                            translations.update()
                            .where(translations.c.unit_id == unit_id)
                            .values(**values)
                        )
                    else:
                        connection.execute(translations.insert().values(unit_id=unit_id, **values))
                    connection.execute(
                        translation_revisions.insert().values(
                            unit_id=unit_id, **values, created_at=now()
                        )
                    )
                    key = result["cache_key"]
                    if (
                        options.get("use_translation_memory", True)
                        and connection.execute(
                            select(tm_entries.c.cache_key).where(tm_entries.c.cache_key == key)
                        ).scalar_one_or_none()
                        is None
                    ):
                        connection.execute(
                            tm_entries.insert().values(
                                cache_key=key,
                                project_id=project_id,
                                translation_text=result["text"],
                                provider_id=result["provider_id"],
                                simulated=int(state == "simulated"),
                            )
                        )
                connection.execute(
                    job_items.update()
                    .where(job_items.c.job_id == job_id, job_items.c.unit_id == unit_id)
                    .values(status=state, error_code=error)
                )
            connection.execute(
                jobs.update().where(jobs.c.job_id == job_id).values(updated_at=now())
            )

    def progress(self, job_id):
        items = self.items(job_id)
        with self.database.transaction() as connection:
            status = connection.execute(
                select(jobs.c.status).where(jobs.c.job_id == job_id)
            ).scalar_one()
        states = [item["status"] for item in items]
        return JobProgress(
            job_id=job_id,
            status=status,
            total=len(states),
            translated=states.count("completed"),
            simulated=states.count("simulated"),
            remaining=sum(state in {"pending", "in_progress"} for state in states),
            errors=sum(state in {"failed", "needs_review"} for state in states),
            skipped=states.count("skipped"),
        )
