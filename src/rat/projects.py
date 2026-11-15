from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import yaml

from rat.config.models import Settings, read_yaml
from rat.config.paths import default_workspace
from rat.database.migrations import check_schema, initialize_database, migrate_database
from rat.database.repositories import ProjectRepository, UnitRepository
from rat.database.session import Database
from rat.domain.base import StrictModel
from rat.domain.models import Project
from rat.logging_setup import log_event


class ProjectManifest(StrictModel):
    format_version: int = 1
    project: Project
    settings: Settings
    game_dir: str | None = None
    sdk_dir: str | None = None


@dataclass
class ProjectSession:
    path: Path
    project: Project
    settings: Settings
    database: Database

    @property
    def units(self) -> UnitRepository:
        return UnitRepository(self.database)

    def close(self) -> None:
        self.database.close()

    def __enter__(self) -> "ProjectSession":
        return self

    def __exit__(self, *_args) -> None:
        self.close()


class ProjectService:
    """Shared entry point for CLI and UI. Never accepts a game directory in phase 0."""

    def create(
        self, name: str, *, workspace: Path | None = None, settings: Settings | None = None
    ) -> ProjectSession:
        settings = settings or Settings()
        project = Project(project_id=uuid4().hex, name=name, created_at=datetime.now(UTC))
        workspace = workspace or settings.app.workspace_dir or default_workspace()
        workspace = workspace.expanduser().resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        path = workspace / project.project_id
        path.mkdir(exist_ok=False)
        database = Database(path / "project.sqlite", create=True)
        try:
            initialize_database(database)
            ProjectRepository(database).add(project)
            for directory in (
                "staging",
                "glossaries",
                "prompts",
                "logs",
                "checkpoints",
                "reports",
                "exports",
            ):
                (path / directory).mkdir()
            manifest = ProjectManifest(project=project, settings=settings)
            temporary = path / "project.yaml.tmp"
            temporary.write_text(
                yaml.safe_dump(
                    manifest.model_dump(mode="json"), allow_unicode=True, sort_keys=False
                ),
                encoding="utf-8",
            )
            temporary.replace(path / "project.yaml")
        except Exception:
            database.close()
            # Keep incomplete work for inspection; opening requires a valid manifest and schema.
            raise
        log_event("project_created")
        return ProjectSession(path, project, settings, database)

    def open(self, path: Path) -> ProjectSession:
        path = path.expanduser().resolve()
        manifest = ProjectManifest.model_validate(read_yaml(path / "project.yaml"))
        if manifest.format_version != 1:
            raise ValueError("Unsupported project format.")
        database = Database(path / "project.sqlite")
        try:
            project = ProjectRepository(database).get(manifest.project.project_id)
            if project != manifest.project:
                raise ValueError("Project manifest does not match the database.")
            migrate_database(database)
            check_schema(database)
        except Exception:
            database.close()
            raise
        log_event("project_opened")
        return ProjectSession(path, project, manifest.settings, database)
