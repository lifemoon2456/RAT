import json
import subprocess
import sys
from pathlib import Path

from rat.database.tables import (
    exports,
    review_revisions,
    schema_version,
    template_snapshots,
    translation_alternatives,
    unit_reviews,
)
from rat.domain.enums import UnitStatus
from rat.exporters.backup import BackupManager
from rat.extraction.scanner import GameImportService
from rat.projects import ProjectService
from rat.review import ReviewService


def test_qa_export_and_backup_commands_use_persisted_editor_decisions(project):
    GameImportService().scan(project.path, Path(__file__).parents[1] / "fixtures/game_with_tl")
    review = ReviewService(project.path)
    for record in review.list_units():
        review.save(record.unit_id, record.source.source_text)
    review.action([record.unit_id for record in review.list_units()], "approve")
    results = {}
    for command in ("qa", "export", "backup"):
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                "from rat.cli.commands import main; raise SystemExit(main())",
                "--log-dir",
                str(project.path / "logs"),
                command,
                "--project",
                str(project.path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        results[command] = json.loads(completed.stdout)
    assert len(results["qa"]) == 8 and all(row["state"] == "approved" for row in results["qa"])
    assert results["export"]["exported_count"] == 8
    manifest = BackupManager(project.path).verify(results["backup"]["backup_path"])
    assert manifest["kind"] == "rat_project_only"


def test_v3_migration_keeps_approval_and_creates_review_tables_with_backup(project, source):
    project.units.add_source(source)
    project.units.save_translation(
        source.unit_id, source.source_text, provider_id="manual", status=UnitStatus.APPROVED
    )
    with project.database.transaction() as connection:
        for table in (
            exports,
            template_snapshots,
            translation_alternatives,
            review_revisions,
            unit_reviews,
        ):
            table.drop(connection)
        connection.execute(schema_version.update().values(version=3))
    with ProjectService().open(project.path) as reopened:
        assert reopened.units.get(source.unit_id).status == UnitStatus.APPROVED
        assert reopened.units.get(source.unit_id).source_sha256 == source.source_sha256
    assert len(list(project.path.glob("project.sqlite.before-v4-*.bak"))) == 1
    assert ReviewService(project.path).list_units()[0].state == "approved"
