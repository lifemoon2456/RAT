from typing import Literal

from rat.domain.base import StrictModel
from rat.domain.enums import UnitKind
from rat.domain.models import TranslationUnit
from rat.domain.protection import UnitProtection


class DiscoveryIssue(StrictModel):
    code: str
    path: str | None = None
    line: int | None = None


class EngineVersion(StrictModel):
    version: str | None = None
    confidence: Literal["unknown", "reported", "static", "conflict", "sdk_verified"] = "unknown"
    evidence: tuple[str, ...] = ()


class InventoryFile(StrictModel):
    relpath: str
    extension: str
    size: int
    sha256: str | None = None
    language: str | None = None


class GameInventory(StrictModel):
    game_dir: str
    files: tuple[InventoryFile, ...]
    translation_languages: tuple[str, ...]
    engine: EngineVersion
    issues: tuple[DiscoveryIssue, ...] = ()


class ParsedText(StrictModel):
    text: str
    literal: str
    line: int
    kind: UnitKind
    speaker: str | None = None
    label: str | None = None
    renpy_identifier: str | None = None


class TemplateText(StrictModel):
    original: ParsedText
    identifier: str | None
    template_path: str
    template_line: int
    block_line: int = 0
    reference_path: str | None = None
    reference_line: int | None = None
    translation: str | None = None
    is_string: bool = False


class UnitOrigin(StrictModel):
    unit_id: str
    template_path: str | None = None
    template_line: int | None = None
    source_verified: bool = False
    confidence: Literal["official_template", "existing_template", "unverified"] | None = None


class PackedProvenance(StrictModel):
    run_id: str
    original_game_dir: str
    manifest_relpath: str
    partial: bool = False


class ImportReport(StrictModel):
    inventory: GameInventory
    units: tuple[TranslationUnit, ...] = ()
    origins: tuple[UnitOrigin, ...] = ()
    issues: tuple[DiscoveryIssue, ...] = ()
    added: int = 0
    reused: int = 0
    changed: int = 0
    sdk_dir: str | None = None
    template_dir: str | None = None
    sdk_version: str | None = None
    protection: tuple[UnitProtection, ...] = ()
    packed_source: PackedProvenance | None = None
