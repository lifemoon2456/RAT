"""Immutable protection results. Temporary markers are never Ren'Py identifiers."""

from typing import Literal

from pydantic import Field

from rat.domain.base import StrictModel

TokenKind = Literal["text", "interpolation", "tag", "escape", "newline", "percent"]


class ProtectionIssue(StrictModel):
    code: str
    affected_text: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    message: str
    stage: Literal["source", "translation", "mapping"] = "source"


class TextToken(StrictModel):
    kind: TokenKind
    text: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)


class TokenizationResult(StrictModel):
    tokens: tuple[TextToken, ...] = ()
    issues: tuple[ProtectionIssue, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.issues


class ProtectedToken(TextToken):
    marker: str


class ProtectedText(StrictModel):
    source_text: str
    source_text_sha256: str
    namespace: str
    masked_text: str
    tokens: tuple[ProtectedToken, ...]


class MaskingResult(StrictModel):
    protected: ProtectedText | None = None
    issues: tuple[ProtectionIssue, ...] = ()

    @property
    def valid(self) -> bool:
        return self.protected is not None and not self.issues


class ValidationResult(StrictModel):
    issues: tuple[ProtectionIssue, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.issues


class RestorationResult(ValidationResult):
    text: str | None = None

    @property
    def valid(self) -> bool:
        return self.text is not None and not self.issues


class UnitProtection(StrictModel):
    unit_id: str
    source_sha256: str
    result: MaskingResult

    @property
    def ready(self) -> bool:
        return self.result.valid
