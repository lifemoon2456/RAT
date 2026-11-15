import asyncio
from pathlib import Path

from pydantic import ValidationError

from rat.database.discovery_repository import DiscoveryRepository
from rat.database.translation_repository import TranslationRepository
from rat.domain.models import ProviderResult
from rat.domain.protection import UnitProtection
from rat.domain.translation import ProviderConfig, TranslationOptions
from rat.jobs.manager import JobControl, ProjectJobLock
from rat.projects import ProjectService
from rat.protection import ProtectionService
from rat.protection.validator import ValidationEngine
from rat.providers.base import ProviderError
from rat.providers.registry import get_provider
from rat.translation.api_logging import ApiLogger
from rat.translation.batching import BatchManager
from rat.translation.context import ContextBuilder
from rat.translation.glossary import GlossarySystem
from rat.translation.quality import QAEngine
from rat.translation.rate_limits import RateLimitManager
from rat.translation.retries import RetryManager
from rat.translation.translation_memory import TranslationMemory


class JobInterrupted(Exception):
    pass


class TranslationManager:
    @staticmethod
    def _failure(unit_id, code, *, status="needs_review"):
        return {"unit_id": unit_id, "status": status, "error_code": code}

    def __init__(self, project_dir: Path, *, provider_factory=get_provider, secret_store=None):
        self.project_dir = Path(project_dir).resolve()
        self.provider_factory = provider_factory
        self.secret_store = secret_store
        self.protection = ProtectionService()

    def create_job(
        self,
        profile: ProviderConfig,
        options: TranslationOptions | None = None,
        glossary: GlossarySystem | None = None,
        *,
        unit_ids: list[str] | None = None,
    ):
        profile = ProviderConfig.model_validate(profile.model_dump())
        options, glossary = options or TranslationOptions(), glossary or GlossarySystem()
        options = TranslationOptions.model_validate(options.model_dump())
        with ProjectService().open(self.project_dir) as session:
            report = DiscoveryRepository(session.database).load(session.project.project_id)
            if report is None or not report.units:
                raise ValueError("import_text_first")
            sources = report.units
            if unit_ids is not None:
                if (
                    not unit_ids
                    or len(set(unit_ids)) != len(unit_ids)
                    or set(unit_ids) - {source.unit_id for source in sources}
                ):
                    raise ValueError("select_current_unique_units")
                sources = tuple(source for source in sources if source.unit_id in unit_ids)
            return TranslationRepository(session.database).create_job(
                session.project.project_id, profile, options, glossary.terms, sources
            )

    def list_jobs(self):
        with ProjectService().open(self.project_dir) as session:
            return TranslationRepository(session.database).list_jobs(session.project.project_id)

    def progress(self, job_id):
        with ProjectService().open(self.project_dir) as session:
            repository = TranslationRepository(session.database)
            repository.job(session.project.project_id, job_id)
            return repository.progress(job_id)

    async def run(self, job_id, *, control=None, on_progress=None, retry_failed=False):
        control, notify = control or JobControl(), on_progress or (lambda _progress: None)
        # Validate the project before creating its process lock.
        with ProjectService().open(self.project_dir) as session, ProjectJobLock(self.project_dir):
            repo = TranslationRepository(session.database)
            job = repo.job(session.project.project_id, job_id)
            profile = ProviderConfig.model_validate(job["profile"])
            options = TranslationOptions.model_validate(job["options"])
            glossary = GlossarySystem(job["glossary"])
            log = ApiLogger(self.project_dir)
            provider = None
            try:
                repo.recover(job_id, retry_failed=retry_failed)
                repo.status(job_id, "running")
                notify(repo.progress(job_id))
                sources = {
                    row["unit_id"]: session.units.get(row["unit_id"]) for row in repo.items(job_id)
                }
                report = DiscoveryRepository(session.database).load(session.project.project_id)
                active = {unit.unit_id for unit in report.units} if report else set()
                prepared = {}
                shared = {"glossary": glossary.payload()}
                context_builder = ContextBuilder()
                for row in repo.items(job_id):
                    if row["status"] != "pending":
                        continue
                    source = sources[row["unit_id"]]
                    if source.unit_id not in active or source.source_sha256 != row["source_sha256"]:
                        repo.commit_batch(
                            session.project.project_id,
                            job_id,
                            [self._failure(source.unit_id, "source_changed")],
                        )
                        continue
                    if repo.should_preserve(
                        source.unit_id,
                        profile.provider_id,
                        alternatives_only=options.alternatives_only,
                    ):
                        repo.commit_batch(
                            session.project.project_id,
                            job_id,
                            [{"unit_id": source.unit_id, "status": "skipped"}],
                        )
                        continue
                    request = row["request"]
                    if request is None:
                        protection = self.protection.prepare_unit(source)
                        if not protection.ready:
                            repo.commit_batch(
                                session.project.project_id,
                                job_id,
                                [self._failure(source.unit_id, "protection_failed")],
                            )
                            continue
                        raw_context = context_builder.build(source, list(report.units))
                        masked, terms = glossary.mask(protection.result.protected.masked_text)
                        key = TranslationMemory.key(
                            session.project.project_id,
                            source,
                            raw_context,
                            profile,
                            options,
                            glossary,
                        )
                        request = {
                            "protection": protection.model_dump(mode="json"),
                            "glossary_map": terms,
                            "cache_key": key,
                            "item": {
                                "unit_id": source.unit_id,
                                "text": masked,
                                "context": context_builder.protected(raw_context),
                            },
                        }
                        repo.prepare(job_id, source.unit_id, request)
                    prepared[source.unit_id] = request
                notify(repo.progress(job_id))
                if control.requested_status:
                    repo.status(job_id, control.requested_status)
                    return repo.progress(job_id)
                # Cache entries must pass the current source's protection checks.
                pending = []
                for unit_id, request in prepared.items():
                    memory = (
                        repo.memory(session.project.project_id, request["cache_key"])
                        if options.use_translation_memory
                        else None
                    )
                    if (
                        memory
                        and self.protection.validate_translation(
                            sources[unit_id], memory["translation_text"]
                        ).valid
                    ):
                        repo.commit_batch(
                            session.project.project_id,
                            job_id,
                            [
                                {
                                    "unit_id": unit_id,
                                    "status": "simulated" if memory["simulated"] else "completed",
                                    "text": memory["translation_text"],
                                    "provider_id": memory["provider_id"],
                                    "cache_key": request["cache_key"],
                                }
                            ],
                        )
                    else:
                        pending.append(request["item"])
                unique, aliases, representative = [], {}, {}
                for item in pending:
                    key = (
                        prepared[item["unit_id"]]["cache_key"]
                        if options.use_translation_memory
                        else item["unit_id"]
                    )
                    if key in representative:
                        aliases[item["unit_id"]] = representative[key]
                    else:
                        representative[key] = item["unit_id"]
                        unique.append(item)
                batches, oversized = BatchManager(options).split(unique, shared)

                def apply_aliases(final=False):
                    states = {item["unit_id"]: item["status"] for item in repo.items(job_id)}
                    results = []
                    for unit_id, parent in aliases.items():
                        if states[unit_id] != "pending":
                            continue
                        request = prepared[unit_id]
                        memory = (
                            repo.memory(session.project.project_id, request["cache_key"])
                            if options.use_translation_memory
                            else None
                        )
                        if (
                            memory
                            and self.protection.validate_translation(
                                sources[unit_id], memory["translation_text"]
                            ).valid
                        ):
                            results.append(
                                {
                                    "unit_id": unit_id,
                                    "status": "simulated" if memory["simulated"] else "completed",
                                    "text": memory["translation_text"],
                                    "provider_id": memory["provider_id"],
                                    "cache_key": request["cache_key"],
                                }
                            )
                        elif final and states[parent] in {"failed", "needs_review"}:
                            results.append(self._failure(unit_id, "representative_failed"))
                    if results:
                        repo.commit_batch(session.project.project_id, job_id, results)

                if oversized:
                    repo.commit_batch(
                        session.project.project_id,
                        job_id,
                        [self._failure(unit_id, "batch_size_limit") for unit_id in oversized],
                    )
                if not batches:
                    apply_aliases(final=True)
                    repo.status(job_id, "completed")
                    notify(repo.progress(job_id))
                    return repo.progress(job_id)
                provider = self.provider_factory(
                    profile.provider_id, profile, secret_store=self.secret_store
                )
                if provider.provider_id != profile.provider_id:
                    raise ValueError("provider_profile_mismatch")

                async def interruptible_sleep(seconds):
                    remaining = seconds
                    while remaining > 0:
                        if control.requested_status or fatal_error:
                            raise JobInterrupted()
                        delay = min(remaining, 0.1)
                        await asyncio.sleep(delay)
                        remaining -= delay

                limiter = RateLimitManager(
                    options.concurrency, options.requests_per_minute, sleep=interruptible_sleep
                )
                retry = RetryManager(options.retry_attempts, sleep=interruptible_sleep)
                fatal_error = False

                async def translate_batch(batch):
                    nonlocal fatal_error
                    ids = [item["unit_id"] for item in batch]
                    if control.requested_status or fatal_error:
                        return
                    # Earlier batches may already have populated this memory key.
                    cached, fresh = [], []
                    for item in batch:
                        request = prepared[item["unit_id"]]
                        memory = (
                            repo.memory(session.project.project_id, request["cache_key"])
                            if options.use_translation_memory
                            else None
                        )
                        if (
                            memory
                            and self.protection.validate_translation(
                                sources[item["unit_id"]], memory["translation_text"]
                            ).valid
                        ):
                            cached.append(
                                {
                                    "unit_id": item["unit_id"],
                                    "status": "simulated" if memory["simulated"] else "completed",
                                    "text": memory["translation_text"],
                                    "provider_id": memory["provider_id"],
                                    "cache_key": request["cache_key"],
                                }
                            )
                        else:
                            fresh.append(item)
                    if cached:
                        repo.commit_batch(session.project.project_id, job_id, cached)
                    if not fresh:
                        notify(repo.progress(job_id))
                        return
                    ids = [item["unit_id"] for item in fresh]
                    repo.start_batch(job_id, ids)

                    async def operation():
                        if control.requested_status or fatal_error:
                            raise JobInterrupted()
                        async with limiter.slot():
                            if control.requested_status or fatal_error:
                                raise JobInterrupted()
                            return await asyncio.wait_for(
                                provider.translate_batch(
                                    fresh,
                                    source_language=options.source_language,
                                    target_language=options.target_language,
                                    context=shared,
                                    settings={
                                        "style": options.style,
                                        "variant_index": options.variant_index,
                                        "output_reserve_tokens": options.output_reserve_tokens,
                                    },
                                ),
                                timeout=profile.timeout_seconds + 1,
                            )

                    try:

                        async def safe_operation():
                            try:
                                return await operation()
                            except TimeoutError:
                                raise ProviderError("timeout", retryable=True) from None
                            except (ProviderError, JobInterrupted):
                                raise
                            except Exception:
                                raise ProviderError("provider_failure") from None

                        results = await retry.run(
                            safe_operation,
                            on_error=lambda error: log.error(profile.provider_id, error),
                        )
                        if not isinstance(results, list):
                            raise ProviderError("invalid_response")
                        parsed = [ProviderResult.model_validate(result) for result in results]
                        actual = [result.unit_id for result in parsed]
                        if (
                            len(actual) != len(set(actual))
                            or set(actual) != set(ids)
                            or any(result.provider_id != profile.provider_id for result in parsed)
                        ):
                            raise ProviderError("invalid_response")
                    except JobInterrupted:
                        for unit_id in ids:
                            repo.prepare(job_id, unit_id, prepared[unit_id])
                        return
                    except (ProviderError, ValidationError) as error:
                        error = (
                            error
                            if isinstance(error, ProviderError)
                            else ProviderError("invalid_response")
                        )
                        log.error(profile.provider_id, error)
                        if error.code == "authentication":
                            fatal_error = True
                        if error.code == "invalid_response" and len(fresh) > 1:
                            middle = len(fresh) // 2
                            await translate_batch(fresh[:middle])
                            await translate_batch(fresh[middle:])
                        else:
                            repo.commit_batch(
                                session.project.project_id,
                                job_id,
                                [
                                    self._failure(unit_id, error.code, status="failed")
                                    for unit_id in ids
                                ],
                            )
                        notify(repo.progress(job_id))
                        return
                    accepted = []
                    for result in parsed:
                        request = prepared[result.unit_id]
                        try:
                            if result.status != "success":
                                raise ValueError("provider_result_error")
                            original_markers, _ = ValidationEngine._markers(request["item"]["text"])
                            returned_markers, errors = ValidationEngine._markers(
                                result.translation_text
                            )
                            if errors or [m for m, _, _ in original_markers] != [
                                m for m, _, _ in returned_markers
                            ]:
                                raise ValueError("validation_failed")
                            unlocked = glossary.restore(
                                result.translation_text, request["glossary_map"]
                            )
                            restored = self.protection.restore_unit(
                                sources[result.unit_id],
                                UnitProtection.model_validate(request["protection"]),
                                unlocked,
                            )
                            if not restored.valid:
                                raise ValueError("validation_failed")
                            if not QAEngine().check(sources[result.unit_id], restored.text).valid:
                                raise ValueError("validation_failed")
                            accepted.append(
                                {
                                    "unit_id": result.unit_id,
                                    "status": "simulated"
                                    if result.simulated or profile.provider_id == "mock"
                                    else "completed",
                                    "text": restored.text,
                                    "provider_id": profile.provider_id,
                                    "cache_key": request["cache_key"],
                                }
                            )
                        except (ValueError, TypeError):
                            accepted.append(self._failure(result.unit_id, "validation_failed"))
                    repo.commit_batch(session.project.project_id, job_id, accepted)
                    notify(repo.progress(job_id))

                # Serialize any batches with overlapping memory keys.
                waves, wave, keys = [], [], set()
                for batch in batches:
                    batch_keys = {prepared[item["unit_id"]]["cache_key"] for item in batch}
                    if wave and (len(wave) >= options.concurrency or keys & batch_keys):
                        waves.append(wave)
                        wave, keys = [], set()
                    wave.append(batch)
                    keys.update(batch_keys)
                if wave:
                    waves.append(wave)
                for wave in waves:
                    if control.requested_status or fatal_error:
                        break
                    tasks = [asyncio.create_task(translate_batch(batch)) for batch in wave]
                    try:
                        await asyncio.gather(*tasks)
                    except BaseException:
                        for task in tasks:
                            task.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)
                        raise
                    apply_aliases()
                apply_aliases(final=not control.requested_status and not fatal_error)
                repo.recover(job_id)
                repo.status(
                    job_id, "failed" if fatal_error else control.requested_status or "completed"
                )
                notify(repo.progress(job_id))
                return repo.progress(job_id)
            except asyncio.CancelledError:
                repo.recover(job_id)
                repo.status(job_id, "paused")
                raise
            except Exception as error:
                repo.status(job_id, "failed")
                log.error(profile.provider_id, error)
                raise ProviderError(getattr(error, "code", "provider_failure")) from None
            finally:
                if provider:
                    try:
                        await provider.aclose()
                    except Exception as error:
                        log.error(profile.provider_id, error)
                log.close()
