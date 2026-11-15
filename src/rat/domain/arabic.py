from typing import Literal

from pydantic import Field

from rat.domain.base import StrictModel


class FontChoice(StrictModel):
    path: str = "builtin:amiri"
    license_path: str = ""
    redistribution_allowed: bool = False


class RuntimeSizes(StrictModel):
    dialogue: int = Field(default=32, ge=10, le=128)
    names: int = Field(default=32, ge=10, le=128)
    choices: int = Field(default=30, ge=10, le=128)
    history: int = Field(default=28, ge=10, le=128)
    preferences: int = Field(default=28, ge=10, le=128)


class RuntimeOptions(StrictModel):
    enabled: bool = False
    primary_font: FontChoice = Field(default_factory=FontChoice)
    fallback_fonts: tuple[FontChoice, ...] = Field(default=(), max_length=4)
    sizes: RuntimeSizes = Field(default_factory=RuntimeSizes)
    target_version: str = Field(default="", pattern=r"^(?:\d+\.\d+\.\d+)?$")
    target_version_confirmed: bool = False
    align_interfaces: bool = True


class CompatibilityProfile(StrictModel):
    version: str | None
    supported: bool
    mode: Literal["native", "unknown", "legacy_unverified", "known_regression", "unsupported"]
    reading_order: bool = False
    warnings: tuple[str, ...] = ()


class FontInfo(StrictModel):
    path: str
    sha256: str
    family: str
    codepoints: tuple[int, ...]
    missing_arabic: tuple[int, ...]
    shaping_tables: bool
    embedding_restricted: bool


class RuntimeAssessment(StrictModel):
    profile: CompatibilityProfile
    fonts: tuple[FontInfo, ...] = ()
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def valid(self):
        return self.profile.supported and not self.errors
