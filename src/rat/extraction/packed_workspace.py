import hashlib
import json
import os
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from rat.domain.packed import PackedConflict, PackedReport
from rat.exporters.safe_io import checked_path, project_directory
from rat.extraction.rpa_adapter import member_path
from rat.security.safe_paths import is_link, read_source_bytes


def stamp():
    return datetime.now(UTC).isoformat()


def hash_file(path, *, deadline=None):
    import time

    if is_link(path):
        raise ValueError("packed_link_rejected")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            if deadline and time.monotonic() > deadline:
                raise ValueError("packed_extraction_time_limit")
            digest.update(block)
    return digest.hexdigest()


class ConflictResolver:
    def detect(self, files, previous=()):
        groups = {}
        for item in files:
            if (
                item.workspace_path
                and item.sha256
                and item.status in {"copied", "extracted", "decompiled"}
            ):
                groups.setdefault(member_path(item.original_path).casefold(), []).append(item)
        old = {conflict.conflict_id: conflict for conflict in previous}
        result = []

        def add(path, candidates, kind):
            ids = tuple(sorted({item.file_id for item in candidates}))
            key = hashlib.sha256((kind + path + "|".join(ids)).encode()).hexdigest()[:24]
            conflict = PackedConflict(conflict_id=key, path=path, candidates=ids, kind=kind)
            result.append(old.get(key, conflict))

        for path, items in sorted(groups.items()):
            if len({item.sha256 for item in items}) > 1:
                add(path, items, "content")
        descendants, membership = {}, 0
        for path, items in groups.items():
            parts = path.split("/")
            for count in range(1, len(parts)):
                parent = "/".join(parts[:count])
                if parent in groups:
                    membership += len(items)
                    if membership > 200000:
                        raise ValueError("packed_conflict_complexity_limit")
                    descendants.setdefault(parent, []).extend(items)
        for path, children in sorted(descendants.items()):
            add(path, [*groups[path], *children], "file_directory")
        return tuple(result)

    def selected(self, files, conflicts):
        blocked = set()
        for conflict in conflicts:
            blocked.update(
                file_id
                for file_id in conflict.candidates
                if not conflict.resolved or file_id != conflict.selected
            )
        candidates = [
            item
            for item in files
            if item.workspace_path
            and item.sha256
            and item.status in {"copied", "extracted", "decompiled"}
        ]
        return [item for item in candidates if item.file_id not in blocked]


class PackedWorkspace:
    def __init__(self, project_dir):
        self.project = Path(project_dir).resolve()

    def create(self, project_id, original, options, engine):
        original = Path(original).resolve()
        if self.project.is_relative_to(original) or original.is_relative_to(self.project):
            raise ValueError("workspace_overlaps_game")
        game_key = hashlib.sha256(str(original).casefold().encode("utf-8")).hexdigest()[:16]
        run_id = uuid4().hex
        project_directory(self.project, "staging", game_dir=str(original))
        relative = f"staging/packed/{game_key}/{run_id}"
        root = checked_path(self.project, relative)
        root.mkdir(parents=True, exist_ok=False)
        (root / "candidates").mkdir()
        (root / "views").mkdir()
        marker = {"project_id": project_id, "run_id": run_id, "game_key": game_key}
        (root / ".rat-packed.json").write_text(json.dumps(marker), encoding="utf-8")
        return PackedReport(
            project_id=project_id,
            game_key=game_key,
            run_id=run_id,
            original_game_dir=str(original),
            workspace_relpath=relative,
            manifest_relpath=f"reports/packed/{run_id}.json",
            created_at=stamp(),
            engine=engine,
            options=options,
        )

    def save(self, report):
        self.validate(report, allow_cleaned=True)
        path = checked_path(self.project, report.manifest_relpath)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = checked_path(self.project, f"reports/packed/{uuid4().hex}.tmp")
        data = report.model_dump_json(exclude_none=True, exclude_defaults=True)
        if len(data.encode("utf-8")) > 32 * 1024 * 1024:
            raise ValueError("packed_manifest_size_limit")
        temporary.write_text(data, encoding="utf-8")
        temporary.replace(path)

    def load(self, run_id):
        if not re.fullmatch(r"[0-9a-f]{32}", run_id):
            raise ValueError("invalid_packed_run_id")
        path = checked_path(self.project, f"reports/packed/{run_id}.json")
        report = PackedReport.model_validate_json(
            read_source_bytes(path, max_bytes=32 * 1024 * 1024)
        )
        self.validate(report, allow_cleaned=True)
        return report

    def validate(self, report, *, allow_cleaned=False):
        from rat.config.models import read_yaml
        from rat.projects import ProjectManifest

        owner = ProjectManifest.model_validate(read_yaml(self.project / "project.yaml"))
        if report.project_id != owner.project.project_id:
            raise ValueError("packed_project_owner_mismatch")
        if not re.fullmatch(r"[0-9a-f]{32}", report.run_id) or not re.fullmatch(
            r"[0-9a-f]{16}", report.game_key
        ):
            raise ValueError("invalid_packed_manifest")
        expected = f"staging/packed/{report.game_key}/{report.run_id}"
        if (
            report.workspace_relpath != expected
            or report.manifest_relpath != f"reports/packed/{report.run_id}.json"
        ):
            raise ValueError("invalid_packed_workspace_path")
        root = checked_path(self.project, expected)
        if not root.resolve().is_relative_to(self.project / "staging/packed"):
            raise ValueError("unsafe_packed_workspace")
        original = Path(report.original_game_dir).resolve()
        if original.is_relative_to(self.project) or self.project.is_relative_to(original):
            raise ValueError("workspace_overlaps_game")
        if report.status == "cleaned" and allow_cleaned:
            return root
        marker = json.loads(read_source_bytes(checked_path(root, ".rat-packed.json")))
        if marker != {
            "project_id": report.project_id,
            "run_id": report.run_id,
            "game_key": report.game_key,
        }:
            raise ValueError("packed_workspace_owner_mismatch")
        for item in report.files:
            if item.workspace_path and (
                not item.workspace_path.startswith(expected + "/candidates/")
                or not re.fullmatch(r"[0-9a-f]{32}", item.workspace_path.rsplit("/", 1)[-1])
            ):
                raise ValueError("invalid_packed_candidate_path")
        if report.view_relpath:
            prefix = expected + "/views/"
            if not report.view_relpath.startswith(prefix) or not re.fullmatch(
                r"[0-9a-f]{32}", report.view_relpath[len(prefix) :]
            ):
                raise ValueError("invalid_packed_view_path")
        return root

    def candidate(self, report, file_id):
        return checked_path(self.project, f"{report.workspace_relpath}/candidates/{file_id}")

    def publish(self, report):
        self.validate(report)
        view = f"{report.workspace_relpath}/views/{uuid4().hex}"
        root = checked_path(self.project, view)
        (root / "game").mkdir(parents=True, exist_ok=False)
        selected = ConflictResolver().selected(report.files, report.conflicts)
        used, published = {}, {}
        for item in sorted(
            selected,
            key=lambda item: (
                member_path(item.original_path).casefold(),
                member_path(item.original_path),
                item.archive or "",
                item.file_id,
            ),
        ):
            path = member_path(item.original_path)
            if path.casefold() in used:
                if used[path.casefold()] != item.sha256:
                    raise ValueError("unresolved_packed_conflict")
                continue
            source = checked_path(self.project, item.workspace_path)
            if hash_file(source) != item.sha256:
                raise ValueError("packed_candidate_hash_mismatch")
            target = checked_path(root, "game/" + path)
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open("rb") as incoming, target.open("xb") as outgoing:
                shutil.copyfileobj(incoming, outgoing, length=1024 * 1024)
            used[path.casefold()] = item.sha256
            published[item.file_id] = view + "/game/" + path
        return report.model_copy(
            update={
                "view_relpath": view,
                "files": tuple(
                    item.model_copy(update={"published_path": published.get(item.file_id)})
                    for item in report.files
                ),
            }
        )

    def clean(self, report):
        root = self.validate(report)
        # Verify the resolved absolute target and every directory before recursive deletion.
        target = root.resolve()
        if not target.is_relative_to((self.project / "staging/packed").resolve()):
            raise ValueError("unsafe_packed_cleanup_target")
        for directory, folders, names in os.walk(target, followlinks=False):
            for name in [*folders, *names]:
                if is_link(Path(directory) / name):
                    raise ValueError("linked_packed_workspace_not_cleaned")
        shutil.rmtree(target)
        return report.model_copy(update={"status": "cleaned"})


def validate_packed_import(project, root, manifest_path):
    workspace = PackedWorkspace(project)
    manifest_path = Path(manifest_path).absolute()
    if manifest_path.parent != workspace.project / "reports/packed":
        raise ValueError("unowned_packed_manifest")
    report = workspace.load(manifest_path.stem)
    if (
        report.status == "cleaned"
        or (workspace.project / report.view_relpath).resolve() != root.resolve()
    ):
        raise ValueError("unowned_packed_import")
    expected = {
        Path(item.published_path).relative_to(report.view_relpath).as_posix(): item.sha256
        for item in report.files
        if item.published_path
    }
    seen = set()
    for directory, folders, names in os.walk(root, followlinks=False):
        for name in [*folders, *names]:
            if is_link(Path(directory) / name):
                raise ValueError("packed_import_link")
        for name in names:
            path = Path(directory) / name
            relpath = path.relative_to(root).as_posix()
            if relpath not in expected or hash_file(path) != expected[relpath]:
                raise ValueError("packed_view_changed")
            seen.add(relpath)
    if set(expected) != seen:
        raise ValueError("packed_view_missing_files")
    return report
