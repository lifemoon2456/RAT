from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field

from rat.domain.arabic import RuntimeOptions
from rat.domain.base import StrictModel
from rat.domain.translation import ProviderId


class AppSettings(StrictModel):
    interface_language: Literal["ar", "en"] = "ar"
    theme: Literal["system", "light", "dark"] = "system"
    workspace_dir: Path | None = None


class ProjectSettings(StrictModel):
    target_language: Literal["arabic"] = "arabic"
    source_language: str = "auto"
    write_original_game: Literal[False] = False
    use_official_templates_first: Literal[True] = True
    allow_decompile: Literal[False] = False


class TranslationSettings(StrictModel):
    provider: ProviderId = "mock"
    model: str = ""
    style: str = "modern_standard_arabic"
    batch_max_units: int = Field(default=12, ge=1, le=1000)
    batch_max_characters: int = Field(default=6500, ge=1)
    concurrent_requests: int = Field(default=2, ge=1)
    request_timeout_seconds: float = Field(default=90, gt=0)
    retry_max_attempts: int = Field(default=4, ge=1)
    preserve_approved_translations: Literal[True] = True
    fallback_provider: None = None


class QualitySettings(StrictModel):
    require_placeholder_match: Literal[True] = True
    require_valid_renpy_syntax: Literal[True] = True
    block_export_on_critical_errors: Literal[True] = True
    detect_suspicious_untranslated_text: bool = True


class ArabicSettings(StrictModel):
    font_family: str = ""
    layout_direction: Literal["auto", "rtl", "ltr"] = "auto"
    shape_with_engine_when_supported: Literal[True] = True
    legacy_preprocess: Literal["disabled"] = "disabled"
    runtime: RuntimeOptions = Field(default_factory=RuntimeOptions)


class ExportSettings(StrictModel):
    mode: Literal["translation_patch"] = "translation_patch"
    zip_package: bool = True
    include_install_instructions: bool = True


class Settings(StrictModel):
    app: AppSettings = Field(default_factory=AppSettings)
    project: ProjectSettings = Field(default_factory=ProjectSettings)
    translation: TranslationSettings = Field(default_factory=TranslationSettings)
    quality: QualitySettings = Field(default_factory=QualitySettings)
    arabic: ArabicSettings = Field(default_factory=ArabicSettings)
    export: ExportSettings = Field(default_factory=ExportSettings)


def read_yaml(path: Path) -> dict:
    if path.stat().st_size > 65536:
        raise ValueError("Configuration file exceeds 64 KiB.")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Configuration must be a YAML mapping.")
    return data


def load_settings(path: Path | None = None) -> Settings:
    return Settings() if path is None else Settings.model_validate(read_yaml(path))


def save_settings(settings: Settings, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        yaml.safe_dump(settings.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    temporary.replace(path)
