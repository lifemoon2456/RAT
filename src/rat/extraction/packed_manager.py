import hashlib
import json
import re
import time
from pathlib import Path
from uuid import uuid4

from rat.database.discovery_repository import DiscoveryRepository
from rat.discovery.inventory import inventory_game
from rat.domain.discovery import EngineVersion
from rat.domain.packed import PackedFile, PackedOptions
from rat.exporters.safe_io import checked_path
from rat.exporters.templates import TemplateCatalog
from rat.extraction.packed_workspace import ConflictResolver, PackedWorkspace, stamp
from rat.extraction.rpa_adapter import RpaAdapter, member_path
from rat.extraction.rpyc_adapter import DecompilerAdapter, SafeRpycDecompiler
from rat.jobs.manager import ProjectJobLock
from rat.projects import ProjectService
from rat.security.safe_paths import read_source_bytes

SCRIPT_TYPES = {".rpy", ".rpym", ".rpyc", ".rpymc"}
COMPILED_TYPES = {".rpyc", ".rpymc"}


def error_code(error):
    value = str(error)
    return (
        value
        if re.fullmatch(r"[a-z][a-z0-9_]{1,90}(?::[A-Z0-9_]{1,30})?", value)
        else "invalid_packed_data"
    )


class PackedGameService:
    def __init__(self, project_dir, *, rpa=None, decompiler: DecompilerAdapter | None = None):
        self.project = Path(project_dir).resolve()
        self.workspace = PackedWorkspace(self.project)
        self.rpa, self.decompiler = rpa or RpaAdapter(), decompiler or SafeRpycDecompiler()

    def log(self, report, event, *, file_id=None, code=None, archive=None):
        path = checked_path(self.project, "logs/packed-recovery.jsonl")
        path.parent.mkdir(exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(
                    {
                        "at": stamp(),
                        "run_id": report.run_id,
                        "event": event,
                        "file_id": file_id,
                        "code": code,
                        "archive": archive,
                    },
                    ensure_ascii=True,
                )
                + "\n"
            )

    def history(self):
        with ProjectService().open(self.project):
            folder = checked_path(self.project, "reports/packed")
            if not folder.is_dir():
                return []
            paths = sorted(
                folder.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True
            )
            reports, size = [], 0
            for path in paths[:20]:
                size += path.stat().st_size
                if size > 64 * 1024 * 1024:
                    break
                reports.append(self.workspace.load(path.stem))
            return reports

    def load(self, run_id):
        with ProjectService().open(self.project):
            return self.workspace.load(run_id)

    def extract(self, game_dir, options: PackedOptions | None = None, *, progress=None):
        options = PackedOptions.model_validate((options or PackedOptions()).model_dump())
        notify = progress or (lambda _report: None)
        inventory = inventory_game(Path(game_dir))
        engine = inventory.engine
        if options.engine_version:
            if not options.engine_version_confirmed:
                raise ValueError("packed_version_confirmation_required")
            if engine.confidence == "conflict" or (
                engine.version and engine.version != options.engine_version
            ):
                raise ValueError("packed_version_conflict")
            engine = EngineVersion(
                version=options.engine_version,
                confidence="reported",
                evidence=("user_confirmed_packed_target",),
            )
        with ProjectService().open(self.project) as session, ProjectJobLock(self.project):
            report = self.workspace.create(
                session.project.project_id, inventory.game_dir, options, engine
            )
            report = report.model_copy(
                update={
                    "rpa_count": sum(item.extension == ".rpa" for item in inventory.files),
                    "warnings": tuple(
                        issue.code
                        for issue in inventory.issues
                        if issue.code
                        not in {"archives_not_extracted", "compiled_scripts_not_decompiled"}
                    ),
                }
            )
            self.workspace.save(report)
            self.log(report, "extraction_started")
            root, records = Path(inventory.game_dir), []
            deadline = time.monotonic() + options.limits.timeout_seconds
            used = 0

            def capture(name, archive, chunks, expected_size, expected_sha=None):
                nonlocal used
                file_id = uuid4().hex
                target = self.workspace.candidate(report, file_id)
                try:
                    member_path(name)
                    if expected_size > options.limits.max_file_bytes:
                        raise ValueError("packed_file_size_limit")
                    if len(records) >= options.limits.max_members:
                        raise ValueError("packed_member_limit")
                    digest, size = hashlib.sha256(), 0
                    with target.open("xb") as destination:
                        for block in chunks:
                            if time.monotonic() > deadline:
                                raise ValueError("packed_extraction_time_limit")
                            size += len(block)
                            if (
                                size > options.limits.max_file_bytes
                                or used + len(block) > options.limits.max_total_bytes
                            ):
                                raise ValueError("packed_extracted_size_limit")
                            used += len(block)
                            digest.update(block)
                            destination.write(block)
                    if size != expected_size or (
                        expected_sha and digest.hexdigest() != expected_sha
                    ):
                        raise ValueError("packed_source_changed")
                    item = PackedFile(
                        file_id=file_id,
                        archive=archive,
                        original_path=name,
                        workspace_path=target.relative_to(self.project).as_posix(),
                        sha256=digest.hexdigest(),
                        size=size,
                        extracted_at=stamp(),
                        status="extracted" if archive else "copied",
                    )
                    self.log(report, "file_captured", file_id=file_id)
                except (OSError, ValueError) as error:
                    if target.is_file():
                        target.unlink()
                    item = PackedFile(
                        file_id=file_id,
                        archive=archive,
                        original_path=name,
                        status="failed",
                        error_code=error_code(error),
                    )
                    self.log(report, "file_failed", file_id=file_id, code=item.error_code)
                records.append(item)
                if len(records) % 100 == 0:
                    notify(report.model_copy(update={"files": tuple(records)}))

            for entry in inventory.files:
                path = checked_path(root, entry.relpath)
                if entry.extension in SCRIPT_TYPES:

                    def loose_chunks(source=path):
                        stat = source.stat()
                        with source.open("rb") as stream:
                            yield from iter(lambda: stream.read(1024 * 1024), b"")
                        if (source.stat().st_size, source.stat().st_mtime_ns) != (
                            stat.st_size,
                            stat.st_mtime_ns,
                        ):
                            raise ValueError("packed_source_changed")

                    capture(
                        entry.relpath.removeprefix("game/"),
                        None,
                        loose_chunks(),
                        entry.size,
                        entry.sha256,
                    )
                elif entry.extension == ".rpa":
                    self.log(report, "archive_started", archive=entry.relpath)
                    try:
                        index = self.rpa.inspect(path, options.limits)
                        for member in index.members:
                            if len(records) >= options.limits.max_members:
                                report = report.model_copy(
                                    update={
                                        "warnings": (
                                            *report.warnings,
                                            "packed_member_limit_reached",
                                        )
                                    }
                                )
                                break
                            if (
                                not options.include_assets
                                and Path(member.original_path).suffix.lower() not in SCRIPT_TYPES
                            ):
                                records.append(
                                    PackedFile(
                                        file_id=uuid4().hex,
                                        archive=entry.relpath,
                                        original_path=member.original_path,
                                        status="skipped_asset",
                                        size=member.size,
                                    )
                                )
                                continue
                            capture(
                                member.original_path,
                                entry.relpath,
                                self.rpa.chunks(path, index, member, deadline=deadline),
                                member.size,
                            )
                        self.log(report, "archive_finished", archive=entry.relpath)
                    except (OSError, ValueError) as error:
                        records.append(
                            PackedFile(
                                file_id=uuid4().hex,
                                archive=entry.relpath,
                                original_path=entry.relpath,
                                status="failed",
                                error_code=error_code(error),
                            )
                        )
                        self.log(
                            report, "archive_failed", code=error_code(error), archive=entry.relpath
                        )
                report = report.model_copy(update={"files": tuple(records)})
                notify(report)
                if time.monotonic() > deadline or len(records) > options.limits.max_members:
                    report = report.model_copy(
                        update={"warnings": (*report.warnings, "packed_run_limit_reached")}
                    )
                    break
            return self._finish(report, session, notify)

    def _finish(self, report, session, notify):
        conflicts = ConflictResolver().detect(report.files, report.conflicts)
        report = report.model_copy(update={"conflicts": conflicts})
        selected = ConflictResolver().selected(report.files, conflicts)
        source_names = {
            member_path(item.original_path).casefold()
            for item in report.files
            if item.workspace_path and Path(item.original_path).suffix.lower() in {".rpy", ".rpym"}
        }
        files = list(report.files)
        selected_ids = {item.file_id for item in selected}
        deadline = time.monotonic() + report.options.limits.timeout_seconds
        total = sum(item.size for item in files if item.workspace_path)
        for index, item in enumerate(files[:]):
            if Path(item.original_path).suffix.lower() not in COMPILED_TYPES:
                continue
            original = Path(member_path(item.original_path)) if item.workspace_path else None
            if original is None:
                continue
            recovered_name = original.with_suffix(
                ".rpym" if original.suffix.lower() == ".rpymc" else ".rpy"
            ).as_posix()
            orphan = recovered_name.casefold() not in source_names
            item = item.model_copy(update={"orphan_rpyc": orphan})
            files[index] = item
            if not orphan or item.file_id not in selected_ids:
                continue
            if not report.options.decompile or item.decompile_status:
                continue
            try:
                if time.monotonic() > deadline:
                    raise ValueError("packed_decompile_time_limit")
                data = read_source_bytes(
                    checked_path(self.project, item.workspace_path),
                    max_bytes=report.options.limits.max_file_bytes,
                )
                profile = self.decompiler.compatibility(report.engine, data)
                if not profile.supported:
                    files[index] = item.model_copy(
                        update={
                            "decompile_status": "unsupported",
                            "error_code": profile.code,
                            "decompiler_id": self.decompiler.adapter_id,
                        }
                    )
                    self.log(
                        report, "decompile_unsupported", file_id=item.file_id, code=profile.code
                    )
                    continue
                output = self.decompiler.decompile(data)
                new_id = uuid4().hex
                target = self.workspace.candidate(report, new_id)
                encoded = output.text.encode("utf-8")
                if len(encoded) > 4 * 1024 * 1024:
                    raise ValueError("decompiled_source_size_limit")
                if total + len(encoded) > report.options.limits.max_total_bytes:
                    raise ValueError("packed_decompiled_total_size_limit")
                total += len(encoded)
                with target.open("xb") as stream:
                    stream.write(encoded)
                files[index] = item.model_copy(
                    update={
                        "decompile_status": "decompiled",
                        "decompiler_id": self.decompiler.adapter_id,
                    }
                )
                files.append(
                    PackedFile(
                        file_id=new_id,
                        archive=item.archive,
                        original_path=recovered_name,
                        workspace_path=target.relative_to(self.project).as_posix(),
                        sha256=hashlib.sha256(encoded).hexdigest(),
                        size=len(encoded),
                        extracted_at=stamp(),
                        status="decompiled",
                        source_file_id=item.file_id,
                        decompiler_id=self.decompiler.adapter_id,
                        partial=output.partial,
                        warnings=(
                            *output.warnings,
                            *(() if profile.tested else ("decompiler_version_not_live_tested",)),
                        ),
                    )
                )
                self.log(report, "file_decompiled", file_id=new_id)
            except (OSError, ValueError) as error:
                files[index] = item.model_copy(
                    update={
                        "decompile_status": "failed",
                        "error_code": error_code(error),
                        "decompiler_id": self.decompiler.adapter_id,
                    }
                )
                self.log(report, "decompile_failed", file_id=item.file_id, code=error_code(error))
        report = report.model_copy(
            update={
                "files": tuple(files),
                "rpyc_count": sum(
                    Path(item.original_path).suffix.lower() in COMPILED_TYPES for item in files
                ),
            }
        )
        conflicts = ConflictResolver().detect(files, conflicts)
        unresolved = any(not conflict.resolved for conflict in conflicts)
        partial = any(
            item.partial
            or item.status == "failed"
            or item.decompile_status in {"failed", "unsupported"}
            or (item.orphan_rpyc and not item.decompile_status)
            for item in files
        )
        status = "conflicts" if unresolved else "partial" if partial else "ready"
        if not any(item.workspace_path for item in files):
            status = "failed"
        report = report.model_copy(update={"conflicts": conflicts, "status": status})
        report = self.workspace.publish(report)
        self.workspace.save(report)
        notify(report)
        if report.options.import_texts and not unresolved and status != "failed":
            try:
                from rat.extraction.scanner import GameImportService

                imported = GameImportService().scan(
                    self.project,
                    self.project / report.view_relpath,
                    packed_manifest=self.project / report.manifest_relpath,
                )
                if imported.origins and any(origin.template_path for origin in imported.origins):
                    TemplateCatalog().load(session, imported)
                report = report.model_copy(update={"imported_count": len(imported.units)})
                self.log(report, "texts_imported")
            except (OSError, ValueError) as error:
                report = report.model_copy(
                    update={"import_error": error_code(error), "status": "partial"}
                )
                self.log(report, "text_import_failed", code=error_code(error))
        self.workspace.save(report)
        self.log(report, "extraction_finished", code=report.status)
        notify(report)
        return report

    def resolve(self, run_id, selections, *, progress=None):
        notify = progress or (lambda _report: None)
        with ProjectService().open(self.project) as session, ProjectJobLock(self.project):
            report = self.workspace.load(run_id)
            if report.status == "cleaned":
                raise ValueError("packed_workspace_cleaned")
            ids = {conflict.conflict_id for conflict in report.conflicts}
            if set(selections) - ids:
                raise ValueError("unknown_packed_conflict")
            conflicts = []
            for conflict in report.conflicts:
                if conflict.conflict_id in selections:
                    selected = selections[conflict.conflict_id]
                    if selected is not None and selected not in conflict.candidates:
                        raise ValueError("invalid_conflict_selection")
                    conflict = conflict.model_copy(update={"selected": selected, "resolved": True})
                conflicts.append(conflict)
            self.log(report, "conflicts_resolved")
            return self._finish(
                report.model_copy(update={"conflicts": tuple(conflicts)}), session, notify
            )

    def clean(self, run_id):
        with ProjectService().open(self.project) as session, ProjectJobLock(self.project):
            report = self.workspace.load(run_id)
            if report.status == "cleaned":
                return report
            imported = DiscoveryRepository(session.database).load(session.project.project_id)
            if imported and imported.packed_source and imported.packed_source.run_id == run_id:
                try:
                    if any(origin.template_path for origin in imported.origins):
                        TemplateCatalog().load(session, imported)
                except (OSError, ValueError):
                    report = report.model_copy(
                        update={
                            "warnings": (
                                *report.warnings,
                                "template_snapshot_unavailable_before_cleanup",
                            )
                        }
                    )
            report = self.workspace.clean(report)
            self.workspace.save(report)
            self.log(report, "workspace_cleaned")
            return report
