"""Privacy-by-construction diagnostics: fixed fields, never raw logs or settings."""

import json
import platform
import re
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from sqlalchemy import func, select

from rat import __version__
from rat.database.discovery_repository import DiscoveryRepository
from rat.database.tables import jobs, schema_version, translations, units
from rat.projects import ProjectService


def safe_version(value):
    return (
        value
        if isinstance(value, str) and re.fullmatch(r"[0-9][0-9.a-zA-Z+_-]{0,60}", value)
        else None
    )


def diagnostic_report(project: Path | None = None) -> dict:
    dependencies = {}
    for name in ("PySide6", "SQLAlchemy", "pydantic", "keyring", "openai", "google-genai"):
        try:
            dependencies[name] = safe_version(version(name))
        except PackageNotFoundError:
            dependencies[name] = None
    result = {
        "format_version": 1,
        "application_version": __version__,
        "python_version": platform.python_version(),
        "windows": sys.platform == "win32",
        "frozen": bool(getattr(sys, "frozen", False)),
        "dependencies": dependencies,
        "project": None,
        "omitted": ["credentials", "headers", "environment", "paths", "names", "text", "raw_logs"],
    }
    if project is not None:
        with (
            ProjectService().open(project) as session,
            session.database.transaction() as connection,
        ):
            imported = DiscoveryRepository(session.database).load(session.project.project_id)
            result["project"] = {
                "schema_version": connection.execute(select(schema_version.c.version)).scalar_one(),
                "units": connection.execute(select(func.count()).select_from(units)).scalar_one(),
                "saved_translations": connection.execute(
                    select(func.count()).select_from(translations)
                ).scalar_one(),
                "interrupted_jobs": connection.execute(
                    select(func.count())
                    .select_from(jobs)
                    .where(jobs.c.status.in_(["running", "paused", "failed"]))
                ).scalar_one(),
                "renpy_version": safe_version(imported.inventory.engine.version)
                if imported
                else None,
                "sdk_version": safe_version(imported.sdk_version) if imported else None,
            }
    return result


def write_diagnostics(output: Path, project: Path | None = None) -> Path:
    if project is not None:
        with ProjectService().open(project) as session:
            imported = DiscoveryRepository(session.database).load(session.project.project_id)
            if imported:
                original = Path(
                    imported.packed_source.original_game_dir
                    if imported.packed_source
                    else imported.inventory.game_dir
                ).resolve()
                if output.resolve().is_relative_to(original):
                    raise ValueError("diagnostics_overlap_game")
    report = diagnostic_report(project)
    # Exclusive creation cannot overwrite game/config/source files selected accidentally.
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=True, indent=2)
    return output
