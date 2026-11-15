import hashlib
import json
import shutil
import sqlite3
from pathlib import Path
from uuid import uuid4

from rat.config.models import read_yaml
from rat.database.discovery_repository import DiscoveryRepository
from rat.exporters.safe_io import checked_path, project_directory
from rat.exporters.templates import TemplateCatalog
from rat.jobs.manager import ProjectJobLock
from rat.projects import ProjectManifest, ProjectService
from rat.security.safe_paths import is_link, read_source_bytes


class BackupManager:
    """Verified project checkpoints; restore only into a new independent directory."""

    def __init__(self, project_dir):
        self.project_dir = Path(project_dir).resolve()

    def create(self):
        with ProjectService().open(self.project_dir) as session, ProjectJobLock(self.project_dir):
            imported = DiscoveryRepository(session.database).load(session.project.project_id)
            # Persist templates before the source/staging directory can disappear.
            if imported and any(origin.template_path for origin in imported.origins):
                TemplateCatalog().load(session, imported)
            directory = project_directory(
                session.path,
                "backups",
                game_dir=(
                    imported.packed_source.original_game_dir
                    if imported.packed_source
                    else imported.inventory.game_dir
                )
                if imported
                else None,
            )
            target = checked_path(directory, f"backup-{uuid4().hex}")
            target.mkdir(exist_ok=False)
            source_db = sqlite3.connect(session.database.path.as_uri() + "?mode=ro", uri=True)
            backup_db = sqlite3.connect(str(target / "project.sqlite"))
            try:
                source_db.backup(backup_db)
            finally:
                backup_db.close()
                source_db.close()
            for name in ("project.yaml", "inventory.json"):
                source = checked_path(session.path, name)
                if source.is_file():
                    (target / name).write_bytes(read_source_bytes(source))
            options = session.settings.arabic.runtime
            for choice in (options.primary_font, *options.fallback_fonts):
                for name in (choice.path, choice.license_path):
                    if not name.startswith("runtime/fonts/"):
                        continue
                    data = read_source_bytes(
                        checked_path(session.path, name), max_bytes=16 * 1024 * 1024
                    )
                    destination = checked_path(target, name)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(data)
            hashes = {
                path.relative_to(target).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in target.rglob("*")
                if path.is_file()
            }
            (target / "backup.json").write_text(
                json.dumps(
                    {"format_version": 1, "kind": "rat_project_only", "files": hashes}, indent=2
                ),
                encoding="utf-8",
            )
            return target

    @staticmethod
    def verify(backup_dir):
        backup_dir = Path(backup_dir).absolute()
        manifest = json.loads(
            read_source_bytes(checked_path(backup_dir, "backup.json")).decode("utf-8")
        )
        if (
            manifest.get("format_version") != 1
            or manifest.get("kind") != "rat_project_only"
            or not isinstance(manifest.get("files"), dict)
            or not {"project.sqlite", "project.yaml"}.issubset(manifest["files"])
        ):
            raise ValueError("invalid_backup_manifest")
        for name, expected in manifest["files"].items():
            if name not in {"project.sqlite", "project.yaml", "inventory.json"} and not (
                name.startswith("runtime/fonts/") and Path(name).suffix in {".ttf", ".otf", ".txt"}
            ):
                raise ValueError("unexpected_backup_file")
            path = checked_path(backup_dir, name)
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest() != expected:
                raise ValueError("backup_hash_mismatch")
        return manifest

    @staticmethod
    def restore(backup_dir: Path, destination: Path) -> Path:
        backup_dir = Path(backup_dir).absolute()
        manifest = BackupManager.verify(backup_dir)
        metadata = ProjectManifest.model_validate(read_yaml(backup_dir / "project.yaml"))
        destination = checked_path(Path(destination).absolute().parent, Path(destination).name)
        for parent in (destination, *destination.parents):
            if parent.exists() and is_link(parent):
                raise ValueError("linked_restore_path")
        for forbidden in (backup_dir, Path(metadata.game_dir) if metadata.game_dir else None):
            if forbidden and (
                destination.resolve().is_relative_to(forbidden.resolve())
                or forbidden.resolve().is_relative_to(destination.resolve())
            ):
                raise ValueError("restore_overlaps_source")
        if destination.exists():
            raise ValueError("restore_requires_new_directory")
        # Check before copying; an incomplete/corrupt snapshot is never published.
        with sqlite3.connect(
            (backup_dir / "project.sqlite").resolve().as_uri() + "?mode=ro", uri=True
        ) as connection:
            if connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise ValueError("backup_database_corrupt")
        staging = checked_path(destination.parent, f".rat-restore-{uuid4().hex}")
        staging.mkdir()
        try:
            for name, expected in manifest["files"].items():
                target = checked_path(staging, name)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(checked_path(backup_dir, name), target)
                if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
                    raise ValueError("backup_changed_during_restore")
            for name in (
                "staging",
                "logs",
                "exports",
                "reports",
                "checkpoints",
                "glossaries",
                "prompts",
            ):
                (staging / name).mkdir(exist_ok=True)
            with ProjectService().open(staging):
                pass
            staging.rename(destination)
        except Exception:
            # Keep failed staging for diagnosis; no existing project is replaced.
            raise
        return destination
