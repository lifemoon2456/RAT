import hashlib
import json
import shutil
from pathlib import Path

import pytest

from rat.cli.commands import main
from rat.diagnostics import diagnostic_report, write_diagnostics
from rat.exporters.backup import BackupManager
from rat.exporters.installation import InstallationService
from rat.exporters.manager import ExportManager
from rat.extraction.scanner import GameImportService
from rat.projects import ProjectService
from rat.review import ReviewService


def snapshot(root):
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file()
    }


@pytest.fixture
def ready(project, tmp_path):
    game = tmp_path / "original"
    shutil.copytree(Path(__file__).parents[1] / "fixtures/game_with_tl", game)
    GameImportService().scan(project.path, game)
    review = ReviewService(project.path)
    for row in review.list_units():
        review.save(row.unit_id, row.source.source_text.replace("Hello", "مرحبا"))
    review.action([row.unit_id for row in review.list_units()], "approve")
    return game, ExportManager(project.path).export()


def test_backup_restore_is_exportable_without_original_or_old_workspace(project, ready, tmp_path):
    game, exported = ready
    before = snapshot(game)
    expected = ReviewService(project.path).list_units()
    backup = BackupManager(project.path).create()
    detached = tmp_path / "detached-backup"
    shutil.copytree(backup, detached)
    game.rename(tmp_path / "moved-game")
    restored = BackupManager.restore(detached, tmp_path / "مشروع مستعاد")
    with ProjectService().open(restored) as session:
        assert session.project == project.project
    assert ReviewService(restored).list_units() == expected
    assert ExportManager(restored).export().file_hashes == exported.file_hashes
    assert snapshot(tmp_path / "moved-game") == before


def test_restore_rejects_existing_destination_corruption_and_game_overlap(project, ready, tmp_path):
    game, _ = ready
    backup = BackupManager(project.path).create()
    with pytest.raises(ValueError, match="overlaps"):
        BackupManager.restore(backup, project.path)
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(ValueError, match="new_directory"):
        BackupManager.restore(backup, existing)
    with pytest.raises(ValueError, match="overlaps"):
        BackupManager.restore(backup, game / "new-project")
    (backup / "project.yaml").write_text("damaged", encoding="utf-8")
    with pytest.raises(ValueError, match="hash_mismatch"):
        BackupManager.restore(backup, tmp_path / "must-not-exist")
    assert not (tmp_path / "must-not-exist").exists()


def test_install_copy_backups_restore_and_original_hashes(project, ready, tmp_path):
    game, exported = ready
    before = snapshot(game)
    installation = InstallationService(project.path).install_copy(
        exported.export_id, tmp_path / "installation"
    )
    assert snapshot(game) == before
    assert list((project.path / "backups").glob("*/backup.json"))
    journal = json.loads((installation / "installation.json").read_text())
    assert journal["status"] == "installed"
    assert snapshot(installation / "game-copy") != before
    restored = InstallationService.restore_copy(installation)
    assert snapshot(restored) == before == snapshot(game)
    assert InstallationService.restore_copy(installation) == restored


def test_install_refuses_overlap_existing_destination_and_tampered_export(project, ready, tmp_path):
    game, exported = ready
    service = InstallationService(project.path)
    for path in (game / "copy", project.path / "copy", game):
        with pytest.raises(ValueError, match="overlaps"):
            service.install_copy(exported.export_id, path)
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(ValueError, match="new_directory"):
        service.install_copy(exported.export_id, existing)
    (Path(exported.destination) / "game/tl/arabic/script.rpy").write_text("tampered")
    with pytest.raises(ValueError, match="hash_mismatch"):
        service.install_copy(exported.export_id, tmp_path / "must-not-exist")
    assert not (tmp_path / "must-not-exist").exists()


def test_restore_blocks_modified_copy_and_corrupt_backup_before_any_writes(
    project, ready, tmp_path
):
    _, exported = ready
    root = InstallationService(project.path).install_copy(exported.export_id, tmp_path / "install")
    patched = root / "game-copy/game/tl/arabic/script.rpy"
    patched.write_text("user-edited-copy")
    before = snapshot(root)
    with pytest.raises(ValueError, match="installed_file_changed"):
        InstallationService.restore_copy(root)
    assert snapshot(root) == before


def test_interrupted_patch_application_can_restore_prepared_journal(
    project, ready, tmp_path, monkeypatch
):
    game, exported = ready
    before = snapshot(game)
    import rat.exporters.installation as module

    real_write = module.write_journal

    def interrupt(root, value):
        if value["status"] == "installed":
            raise OSError("synthetic crash after patch writes")
        real_write(root, value)

    monkeypatch.setattr(module, "write_journal", interrupt)
    root = tmp_path / "interrupted"
    with pytest.raises(OSError):
        InstallationService(project.path).install_copy(exported.export_id, root)
    assert json.loads((root / "installation.json").read_text())["status"] == "prepared"
    assert snapshot(InstallationService.restore_copy(root)) == before
    assert snapshot(game) == before


def test_diagnostics_omit_logs_keys_paths_and_game_text(project, ready, tmp_path, monkeypatch):
    game, _ = ready
    secret = "SYNTHETIC_DO_NOT_DISCLOSE"
    (project.path / "logs/api.log").write_text("Authorization: Bearer " + secret)
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    report = diagnostic_report(project.path)
    serialized = json.dumps(report)
    assert secret not in serialized and str(project.path) not in serialized
    assert "player_name" not in serialized and project.project.name not in serialized
    assert report["project"]["units"] == 8
    with pytest.raises(ValueError, match="overlap"):
        write_diagnostics(game / "diagnostic.json", project.path)
    target = tmp_path / "diagnostic.json"
    assert (
        main(
            [
                "--log-dir",
                str(tmp_path / "logs"),
                "diagnostics",
                "--project",
                str(project.path),
                "--output",
                str(target),
            ]
        )
        == 0
    )
    with pytest.raises(FileExistsError):
        write_diagnostics(target, project.path)


def test_backup_manifest_rejects_traversal_and_incomplete_files(project, tmp_path):
    backup = BackupManager(project.path).create()
    manifest = json.loads((backup / "backup.json").read_text())
    manifest["files"]["runtime/fonts/../../outside.txt"] = "0" * 64
    (backup / "backup.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        BackupManager.restore(backup, tmp_path / "blocked")
    assert not (tmp_path / "blocked").exists()


@pytest.mark.parametrize("existing", [False, True])
def test_restore_invalidates_regenerated_rpyc_and_preserves_old_compiled_files(
    project, ready, tmp_path, existing
):
    game, exported = ready
    compiled = game / "game/tl/arabic/script.rpyc"
    if existing:
        compiled.write_bytes(b"synthetic previous compiled data")
    before = snapshot(game)
    root = InstallationService(project.path).install_copy(exported.export_id, tmp_path / "install")
    generated = root / "game-copy/game/tl/arabic/script.rpyc"
    assert not generated.exists()
    generated.write_bytes(b"synthetic newly compiled translation")
    assert snapshot(InstallationService.restore_copy(root)) == before
    assert snapshot(game) == before


def test_export_from_before_reimport_cannot_be_installed_on_different_sources(
    project, ready, tmp_path
):
    game, exported = ready
    script = game / "game/script.rpy"
    script.write_text(
        script.read_text(encoding="utf-8") + "\n# new source version\n", encoding="utf-8"
    )
    GameImportService().scan(project.path, game)
    with pytest.raises(ValueError, match="export_source_mismatch"):
        InstallationService(project.path).install_copy(exported.export_id, tmp_path / "blocked")
    assert not (tmp_path / "blocked").exists()
