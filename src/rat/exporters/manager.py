import hashlib
import html
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from rat.arabic.runtime import ArabicRuntimeService
from rat.database.discovery_repository import DiscoveryRepository
from rat.database.review_repository import ReviewRepository
from rat.database.tables import exports
from rat.domain.review import ExportProblem, ExportReport, ReviewStatus
from rat.exporters.renpy_writer import RenPyWriter
from rat.exporters.safe_io import checked_path, project_directory
from rat.exporters.templates import TemplateCatalog
from rat.jobs.manager import ProjectJobLock
from rat.projects import ProjectService
from rat.translation.quality import QAEngine


class ExportManager:
    def __init__(self, project_dir: Path):
        self.project_dir = Path(project_dir).resolve()

    def export(self, *, approved_only=True, zip_package=True) -> ExportReport:
        with ProjectService().open(self.project_dir) as session, ProjectJobLock(self.project_dir):
            imported = DiscoveryRepository(session.database).load(session.project.project_id)
            if imported is None:
                raise ValueError("import_text_first")
            directory = project_directory(
                session.path,
                "exports",
                game_dir=imported.packed_source.original_game_dir
                if imported.packed_source
                else imported.inventory.game_dir,
            )
            export_id = uuid4().hex
            staging = checked_path(directory, f".pending-{export_id}")
            staging.mkdir(exist_ok=False)
            destination = checked_path(directory, f"release-{export_id}")
            records = ReviewRepository(session.database).list(session.project.project_id)
            qa = QAEngine().audit(records)
            origins = {origin.unit_id: origin for origin in imported.origins}
            selected, skipped, errors = [], [], []
            for record in records:
                reason = (
                    "skipped_by_user"
                    if record.skipped
                    else "not_approved"
                    if approved_only and record.state != ReviewStatus.APPROVED
                    else "untranslated"
                    if record.translation_text is None
                    else None
                )
                if reason:
                    skipped.append(ExportProblem(code=reason, unit_id=record.unit_id))
                    continue
                if record.provider_id == "mock" and record.state != ReviewStatus.APPROVED:
                    skipped.append(
                        ExportProblem(code="unapproved_simulation", unit_id=record.unit_id)
                    )
                    continue
                if not qa[record.unit_id].valid:
                    errors.extend(
                        ExportProblem(code=issue.code, unit_id=record.unit_id)
                        for issue in qa[record.unit_id].issues
                        if issue.severity == "error"
                    )
                    skipped.append(ExportProblem(code="qa_failed", unit_id=record.unit_id))
                    continue
                origin = origins.get(record.unit_id)
                if (
                    origin is None
                    or not origin.template_path
                    or (
                        not origin.source_verified
                        and not (record.source.old is not None and imported.sdk_version)
                    )
                ):
                    errors.append(
                        ExportProblem(code="unverified_official_template", unit_id=record.unit_id)
                    )
                    skipped.append(
                        ExportProblem(code="unverified_official_template", unit_id=record.unit_id)
                    )
                    continue
                if record.source.renpy_identifier is None and record.source.old is None:
                    errors.append(
                        ExportProblem(code="missing_real_identifier", unit_id=record.unit_id)
                    )
                    skipped.append(
                        ExportProblem(code="missing_real_identifier", unit_id=record.unit_id)
                    )
                    continue
                selected.append(record)
            eligible_ids = {record.unit_id for record in selected}
            created, hashes, emitted = [], {}, []
            runtime_metadata = {
                "enabled": session.settings.arabic.runtime.enabled,
                "status": "blocked" if session.settings.arabic.runtime.enabled else "disabled",
            }
            try:
                runtime_files, runtime_metadata = ArabicRuntimeService(session.path).bundle(
                    session.settings.arabic,
                    imported=imported,
                    texts=[record.translation_text for record in selected],
                )
                templates = TemplateCatalog().load(session, imported) if selected else {}
                writer = RenPyWriter()
                seen_paths = set()
                old_keys = {}
                identifiers = {}
                conflicts = set()
                for record in selected:
                    key = (
                        ("old", record.source.old)
                        if record.source.old is not None
                        else ("id", record.source.renpy_identifier)
                    )
                    origin = origins[record.unit_id]
                    if key[0] == "old":
                        if key in old_keys:
                            conflicts.add(key)
                        old_keys[key] = record.translation_text
                    else:
                        # Multiple says within one real block share its ID.
                        block = (
                            record.source.source_location.rsplit(":", 1)[0]
                            if record.source.source_location
                            else None
                        )
                        place = (origin.template_path, block)
                        if key in identifiers and identifiers[key] != place:
                            conflicts.add(key)
                        identifiers[key] = place
                if conflicts:
                    remaining = []
                    for record in selected:
                        key = (
                            ("old", record.source.old)
                            if record.source.old is not None
                            else ("id", record.source.renpy_identifier)
                        )
                        if key in conflicts:
                            errors.append(
                                ExportProblem(
                                    code="conflicting_translation_key", unit_id=record.unit_id
                                )
                            )
                        else:
                            remaining.append(record)
                    selected = remaining
                for path, template in sorted(templates.items()):
                    text, exported_ids, problems = writer.render(path, template, selected, origins)
                    errors.extend(problems)
                    if not text:
                        continue
                    output_path = str(Path(path).with_suffix(".rpy")).replace("\\", "/")
                    if output_path.casefold() in seen_paths:
                        errors.append(ExportProblem(code="output_path_collision", path=output_path))
                        continue
                    seen_paths.add(output_path.casefold())
                    target = checked_path(staging, output_path)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    data = text.encode("utf-8")
                    target.write_bytes(data)
                    hashes[output_path] = hashlib.sha256(data).hexdigest()
                    created.append(output_path)
                    emitted.extend(exported_ids)
                for path, data in runtime_files.items():
                    if path.casefold() in seen_paths:
                        raise ValueError("arabic_runtime_path_collision")
                    target = checked_path(staging, path)
                    if target.exists():
                        raise ValueError("arabic_runtime_path_collision")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                    hashes[path] = hashlib.sha256(data).hexdigest()
                    created.append(path)
            except (OSError, ValueError, UnicodeError):
                errors.append(
                    ExportProblem(
                        code="arabic_runtime_validation_failed"
                        if runtime_metadata.get("status") == "blocked"
                        else "template_or_output_unavailable"
                    )
                )
            missing = eligible_ids - set(emitted)
            for unit_id in sorted(missing):
                skipped.append(ExportProblem(code="not_rendered", unit_id=unit_id))
                if not any(problem.unit_id == unit_id for problem in errors):
                    errors.append(ExportProblem(code="template_entry_missing", unit_id=unit_id))
            # All eligible failures are visible; no invalid translation is emitted.
            extra = ["manifest.json", "report.json", "report.html", "INSTALL_AR.txt"]
            if zip_package and emitted:
                extra.append("translation_patch.zip")
            report = ExportReport(
                export_id=export_id,
                status="failed" if not emitted else "partial" if errors else "completed",
                destination=str(destination),
                approved_only=approved_only,
                exported=tuple(emitted),
                skipped=tuple(skipped),
                errors=tuple(errors),
                created_files=tuple(created + extra),
                file_hashes=hashes,
                arabic_runtime=runtime_metadata,
            )
            manifest = {
                "format_version": 1,
                "language": "arabic",
                "project_id": session.project.project_id,
                "export_id": export_id,
                "file_hashes": hashes,
                "source_files": [
                    item.model_dump(mode="json") for item in imported.inventory.files if item.sha256
                ],
                "sdk_version": imported.sdk_version,
                "exported_unit_ids": emitted,
                "status": report.status,
                "requires_runtime_verification": True,
                "packed_source": imported.packed_source.model_dump(mode="json")
                if imported.packed_source
                else None,
                "arabic_runtime": runtime_metadata,
            }
            (staging / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (staging / "report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
            summary = (
                f"Status: {report.status} | Exported: {len(emitted)} | "
                f"Skipped: {len(skipped)} | Errors: {len(errors)}"
            )
            detail = "\n".join(
                f"{item.code}: {item.unit_id or item.path or ''}" for item in [*skipped, *errors]
            )
            (staging / "report.html").write_text(
                "<!doctype html><meta charset='utf-8'><title>RAT Export</title><h1>"
                + html.escape(summary)
                + "</h1><pre>"
                + html.escape(detail)
                + "</pre>",
                encoding="utf-8",
            )
            (staging / "INSTALL_AR.txt").write_text(
                "هذه حزمة ترجمة مستقلة؛ لم يغير RAT اللعبة الأصلية.\n"
                "راجع report.json وmanifest.json. partial تعني حزمة جزئية "
                "وfailed تعني لا نصوص مصدرة.\n"
                "اختبر على نسخة منفصلة مطابقة لمصادر manifest فقط؛ "
                "لا تكتب فوق النسخة الأصلية.\n"
                "لا يتضمن هذا الإصدار مثبتًا. راجع arabic_runtime في manifest "
                "لمعرفة تضمين الخطوط وRTL؛ يلزم فحص اللعبة وإصدار محركها.\n"
                "لتعطيل طبقة RAT في نسخة الاختبار: أنشئ ملفًا فارغًا باسم "
                "game/tl/arabic/rat_runtime.disabled ثم أعد تشغيل اللعبة.\n"
                "لا تقلب النص أو تحذف المتغيرات والوسوم؛ التشكيل داخل المحرك.\n",
                encoding="utf-8",
            )
            if zip_package and emitted:
                members = sorted(path for path in staging.rglob("*") if path.is_file())
                with zipfile.ZipFile(
                    staging / "translation_patch.zip", "w", zipfile.ZIP_DEFLATED
                ) as archive:
                    for path in members:
                        archive.write(path, path.relative_to(staging).as_posix())
            staging.rename(destination)
            with session.database.transaction() as connection:
                connection.execute(
                    exports.insert().values(
                        export_id=export_id,
                        project_id=session.project.project_id,
                        report=report.model_dump(mode="json"),
                        created_at=datetime.now(UTC).isoformat(),
                    )
                )
            return report

    def history(self):
        with (
            ProjectService().open(self.project_dir) as session,
            session.database.transaction() as connection,
        ):
            return [
                ExportReport.model_validate(value)
                for value in connection.execute(
                    select(exports.c.report)
                    .where(exports.c.project_id == session.project.project_id)
                    .order_by(exports.c.created_at.desc())
                ).scalars()
            ]
