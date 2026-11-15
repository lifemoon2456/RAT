from typing import Literal

from pydantic import Field

from rat.domain.base import StrictModel
from rat.domain.discovery import EngineVersion


class PackedLimits(StrictModel):
    max_members: int = Field(default=50000, ge=1, le=100000)
    max_file_bytes: int = Field(default=64 * 1024 * 1024, ge=1024, le=256 * 1024 * 1024)
    max_total_bytes: int = Field(default=512 * 1024 * 1024, ge=1024, le=2 * 1024**3)
    max_index_bytes: int = Field(default=16 * 1024 * 1024, ge=1024, le=32 * 1024 * 1024)
    timeout_seconds: int = Field(default=120, ge=1, le=600)


class PackedOptions(StrictModel):
    include_assets: bool = False
    decompile: bool = False
    import_texts: bool = True
    engine_version: str = Field(default="", pattern=r"^(?:\d+\.\d+\.\d+)?$")
    engine_version_confirmed: bool = False
    limits: PackedLimits = Field(default_factory=PackedLimits)


class PackedFile(StrictModel):
    file_id: str
    archive: str | None = None
    original_path: str
    workspace_path: str | None = None
    sha256: str | None = None
    size: int = 0
    extracted_at: str | None = None
    status: str
    error_code: str | None = None
    source_file_id: str | None = None
    decompiler_id: str | None = None
    decompile_status: str | None = None
    orphan_rpyc: bool = False
    published_path: str | None = None
    partial: bool = False
    warnings: tuple[str, ...] = ()


class PackedConflict(StrictModel):
    conflict_id: str
    path: str
    candidates: tuple[str, ...]
    selected: str | None = None
    resolved: bool = False
    kind: Literal["content", "file_directory"] = "content"


class PackedReport(StrictModel):
    format_version: int = 1
    project_id: str
    game_key: str
    run_id: str
    original_game_dir: str
    workspace_relpath: str
    view_relpath: str = ""
    manifest_relpath: str
    created_at: str
    engine: EngineVersion
    rpa_count: int = 0
    rpyc_count: int = 0
    files: tuple[PackedFile, ...] = ()
    conflicts: tuple[PackedConflict, ...] = ()
    status: Literal["ready", "partial", "conflicts", "failed", "cleaned"] = "failed"
    imported_count: int = 0
    import_error: str | None = None
    warnings: tuple[str, ...] = ()
    options: PackedOptions = Field(default_factory=PackedOptions)


class DecompilerCompatibility(StrictModel):
    supported: bool
    code: str
    tested: bool = False


class DecompiledSource(StrictModel):
    text: str
    partial: bool = False
    warnings: tuple[str, ...] = ()
