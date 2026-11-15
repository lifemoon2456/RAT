"""Explicit patch installation on a newly created game copy, with recoverable journal."""

import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from uuid import uuid4

from rat.database.discovery_repository import DiscoveryRepository
from rat.exporters.backup import BackupManager
from rat.exporters.manager import ExportManager
from rat.exporters.safe_io import checked_path
from rat.jobs.manager import ProjectJobLock
from rat.projects import ProjectService
from rat.security.safe_paths import is_link, read_source_bytes


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_journal(root: Path, value: dict) -> None:
    target = checked_path(root, "installation.json")
    temporary = checked_path(root, f"journal-{uuid4().hex}.tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(target)


def patch_path(root: Path, name: str) -> Path:
    if not name.startswith("game/tl/arabic/"):
        raise ValueError("not_an_arabic_patch_path")
    return checked_path(root, name)


class InstallationService:
    def __init__(self, project_dir: Path):
        self.project_dir = Path(project_dir).resolve()

    def install_copy(self, export_id: str, destination: Path) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", export_id):
            raise ValueError("invalid_export_id")
        report = next(
            (
                item
                for item in ExportManager(self.project_dir).history()
                if item.export_id == export_id
            ),
            None,
        )
        if not report or report.status != "completed" or not report.exported:
            raise ValueError("completed_export_required")
        destination = Path(destination).absolute()
        # Reject linked ancestors as well as paths overlapping either source.
        for parent in (destination, *destination.parents):
            if parent.exists() and is_link(parent):
                raise ValueError("linked_install_path")
        with ProjectService().open(self.project_dir) as session:
            imported = DiscoveryRepository(session.database).load(session.project.project_id)
        if imported is None or imported.packed_source:
            raise ValueError("copy_install_requires_source_import")
        original = Path(
            imported.packed_source.original_game_dir
            if imported.packed_source
            else imported.inventory.game_dir
        ).resolve()
        for root in (original, self.project_dir):
            if destination.resolve().is_relative_to(root) or root.is_relative_to(
                destination.resolve()
            ):
                raise ValueError("install_overlaps_source")
        if destination.exists() or not destination.parent.is_dir():
            raise ValueError("install_requires_new_directory")
        release = checked_path(self.project_dir, f"exports/release-{export_id}")
        manifest = json.loads(read_source_bytes(checked_path(release, "manifest.json")))
        current_sources = [
            item.model_dump(mode="json") for item in imported.inventory.files if item.sha256
        ]
        if (
            manifest.get("export_id") != export_id
            or manifest.get("source_files") != current_sources
            or manifest.get("file_hashes") != report.file_hashes
        ):
            raise ValueError("export_source_mismatch")
        patches = {
            name: value
            for name, value in report.file_hashes.items()
            if name.startswith("game/tl/arabic/")
        }
        if not patches:
            raise ValueError("empty_patch")
        for name, expected in patches.items():
            if digest(patch_path(release, name)) != expected:
                raise ValueError("patch_hash_mismatch")
        # Check every imported source hash against the selected original before making a copy.
        if not imported.packed_source:
            for item in imported.inventory.files:
                if item.sha256 and digest(checked_path(original, item.relpath)) != item.sha256:
                    raise ValueError("source_changed_reimport_first")
        BackupManager(self.project_dir).create()
        with ProjectJobLock(self.project_dir):
            destination.mkdir()
            copied = destination / "game-copy"
            copied.mkdir()

            # Copy regular files only, streaming; never follow junctions/symlinks or execute code.
            def copy_error(error):
                raise error

            for folder, directories, files in os.walk(
                original, followlinks=False, onerror=copy_error
            ):
                for name in [*directories, *files]:
                    source = Path(folder) / name
                    if is_link(source):
                        raise ValueError("linked_game_file")
                relative = Path(folder).relative_to(original)
                target = copied / relative
                target.mkdir(exist_ok=True)
                for name in files:
                    source, output = Path(folder) / name, target / name
                    before = digest(source)
                    shutil.copyfile(source, output)
                    if digest(output) != before or digest(source) != before:
                        raise ValueError("game_changed_during_copy")
            backups = destination / "backup"
            backups.mkdir()
            previous = {}
            compiled = {name + "c": None for name in patches if name.endswith(".rpy")}
            for name in [*patches, *compiled]:
                target = patch_path(copied, name)
                hashes = compiled if name in compiled else previous
                hashes[name] = digest(target) if target.is_file() else None
                if target.exists():
                    saved = patch_path(backups, name)
                    saved.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(target, saved)
                    if digest(saved) != hashes[name]:
                        raise ValueError("backup_hash_mismatch")
            journal = {
                "format_version": 1,
                "kind": "rat_game_copy",
                "status": "prepared",
                "patches": patches,
                "previous": previous,
                "compiled": compiled,
            }
            # The journal and all overwritten bytes exist BEFORE the first patch write.
            write_journal(destination, journal)
            for name in compiled:
                patch_path(copied, name).unlink(missing_ok=True)
            for name, expected in patches.items():
                target = patch_path(copied, name)
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = checked_path(target.parent, f".rat-{uuid4().hex}.tmp")
                shutil.copyfile(patch_path(release, name), temporary)
                if digest(temporary) != expected:
                    raise ValueError("patch_changed_during_install")
                temporary.replace(target)
            journal["status"] = "installed"
            write_journal(destination, journal)
            return destination

    @staticmethod
    def restore_copy(directory: Path) -> Path:
        directory = Path(directory).absolute()
        for parent in (directory, *directory.parents):
            if parent.exists() and is_link(parent):
                raise ValueError("linked_install_path")
        journal = json.loads(read_source_bytes(checked_path(directory, "installation.json")))
        if (
            journal.get("format_version") != 1
            or journal.get("kind") != "rat_game_copy"
            or journal.get("status") not in {"prepared", "installed", "restored"}
            or not isinstance(journal.get("patches"), dict)
            or not isinstance(journal.get("previous"), dict)
            or set(journal["patches"]) != set(journal["previous"])
            or not isinstance(journal.get("compiled"), dict)
            or set(journal["compiled"])
            != {name + "c" for name in journal["patches"] if name.endswith(".rpy")}
        ):
            raise ValueError("invalid_installation_journal")
        copied = checked_path(directory, "game-copy")
        backups = checked_path(directory, "backup")
        for name, old in journal["compiled"].items():
            target = patch_path(copied, name)
            if target.exists() and (is_link(target) or target.stat().st_nlink > 1):
                raise ValueError("linked_install_file")
            if old is not None and digest(patch_path(backups, name)) != old:
                raise ValueError("backup_hash_mismatch")
        # Validate ALL bytes before any restoration, including restart after partial rollback.
        for name, expected in journal["patches"].items():
            old = journal["previous"][name]
            target = patch_path(copied, name)
            if target.exists() and (is_link(target) or target.stat().st_nlink > 1):
                raise ValueError("linked_install_file")
            current = digest(target) if target.is_file() else None
            if current not in {old, expected}:
                raise ValueError("installed_file_changed")
            if old is not None and digest(patch_path(backups, name)) != old:
                raise ValueError("backup_hash_mismatch")
        # Compiled siblings may have been regenerated by Ren'Py after installation.
        for name, old in {**journal["previous"], **journal["compiled"]}.items():
            target = patch_path(copied, name)
            if old is None:
                target.unlink(missing_ok=True)
            else:
                temporary = checked_path(target.parent, f".rat-restore-{uuid4().hex}.tmp")
                shutil.copyfile(patch_path(backups, name), temporary)
                temporary.replace(target)
        journal["status"] = "restored"
        write_journal(directory, journal)
        return copied
