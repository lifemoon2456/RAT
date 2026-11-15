from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)

from rat.domain.enums import UnitStatus

metadata = MetaData()

schema_version = Table("schema_version", metadata, Column("version", Integer, primary_key=True))

projects = Table(
    "projects",
    metadata,
    Column("project_id", String, primary_key=True),
    Column("name", String, nullable=False),
    Column("created_at", String, nullable=False),
    Column("target_language", String, nullable=False),
)

units = Table(
    "units",
    metadata,
    Column("unit_id", String, primary_key=True),
    Column("project_id", ForeignKey("projects.project_id"), nullable=False),
    Column("location_key", String, nullable=False),
    # Full immutable source contract, including old and the real Ren'Py identifier.
    Column("source_data", JSON, nullable=False),
    UniqueConstraint("project_id", "location_key"),
)

_statuses = ",".join(f"'{value.value}'" for value in UnitStatus)
translations = Table(
    "translations",
    metadata,
    Column("unit_id", ForeignKey("units.unit_id"), primary_key=True),
    Column("translation_text", Text, nullable=True),
    Column("provider_id", String, nullable=False),
    Column("status", String, nullable=False),
    CheckConstraint(f"status IN ({_statuses})"),
    CheckConstraint(
        "status NOT IN ('translated', 'validated', 'approved') OR translation_text IS NOT NULL"
    ),
)

translation_revisions = Table(
    "translation_revisions",
    metadata,
    Column("revision_id", Integer, primary_key=True),
    Column("unit_id", ForeignKey("units.unit_id"), nullable=False),
    Column("translation_text", Text, nullable=True),
    Column("provider_id", String, nullable=False),
    Column("status", String, nullable=False),
    Column("created_at", String, nullable=False),
)

game_imports = Table(
    "game_imports",
    metadata,
    Column("project_id", ForeignKey("projects.project_id"), primary_key=True),
    Column("payload", JSON, nullable=False),
)

source_files = Table(
    "source_files",
    metadata,
    Column("project_id", ForeignKey("projects.project_id"), primary_key=True),
    Column("relpath", String, primary_key=True),
    Column("payload", JSON, nullable=False),
)

unit_discovery = Table(
    "unit_discovery",
    metadata,
    Column("unit_id", ForeignKey("units.unit_id"), primary_key=True),
    Column("active", Integer, nullable=False),
    Column("origin", JSON, nullable=False),
)

providers = Table(
    "providers",
    metadata,
    Column("profile_id", String, primary_key=True),
    Column("project_id", ForeignKey("projects.project_id"), nullable=False),
    Column("config", JSON, nullable=False),
)
jobs = Table(
    "jobs",
    metadata,
    Column("job_id", String, primary_key=True),
    Column("project_id", ForeignKey("projects.project_id"), nullable=False),
    Column("profile", JSON, nullable=False),
    Column("options", JSON, nullable=False),
    Column("glossary", JSON, nullable=False),
    Column("status", String, nullable=False),
    Column("created_at", String, nullable=False),
    Column("updated_at", String, nullable=False),
)
job_items = Table(
    "job_items",
    metadata,
    Column("job_id", ForeignKey("jobs.job_id"), primary_key=True),
    Column("unit_id", ForeignKey("units.unit_id"), primary_key=True),
    Column("source_sha256", String, nullable=False),
    Column("status", String, nullable=False),
    Column("request", JSON, nullable=True),
    Column("error_code", String, nullable=True),
)
tm_entries = Table(
    "tm_entries",
    metadata,
    Column("cache_key", String, primary_key=True),
    Column("project_id", ForeignKey("projects.project_id"), nullable=False),
    Column("translation_text", Text, nullable=False),
    Column("simulated", Integer, nullable=False),
    Column("provider_id", String, nullable=False),
)

unit_reviews = Table(
    "unit_reviews",
    metadata,
    Column("unit_id", ForeignKey("units.unit_id"), primary_key=True),
    Column("payload", JSON, nullable=False),
)
review_revisions = Table(
    "review_revisions",
    metadata,
    Column("revision_id", Integer, primary_key=True),
    Column("unit_id", ForeignKey("units.unit_id"), nullable=False),
    Column("payload", JSON, nullable=False),
    Column("created_at", String, nullable=False),
)
translation_alternatives = Table(
    "translation_alternatives",
    metadata,
    Column("alternative_id", String, primary_key=True),
    Column("unit_id", ForeignKey("units.unit_id"), nullable=False),
    Column("source_sha256", String, nullable=False),
    Column("text", Text, nullable=False),
    Column("provider_id", String, nullable=False),
    Column("simulated", Integer, nullable=False),
    Column("job_id", ForeignKey("jobs.job_id"), nullable=False),
    Column("created_at", String, nullable=False),
    UniqueConstraint("job_id", "unit_id"),
)
template_snapshots = Table(
    "template_snapshots",
    metadata,
    Column("project_id", ForeignKey("projects.project_id"), primary_key=True),
    Column("snapshot_key", String, primary_key=True),
    Column("path", String, primary_key=True),
    Column("sha256", String, nullable=False),
    Column("content", Text, nullable=False),
)
exports = Table(
    "exports",
    metadata,
    Column("export_id", String, primary_key=True),
    Column("project_id", ForeignKey("projects.project_id"), nullable=False),
    Column("report", JSON, nullable=False),
    Column("created_at", String, nullable=False),
)
