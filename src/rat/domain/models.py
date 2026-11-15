import hashlib
import json
from datetime import datetime
from pathlib import PurePosixPath, PureWindowsPath
from typing import Literal

from pydantic import Field, field_validator, model_validator

from rat.domain.base import StrictModel
from rat.domain.enums import UnitKind, UnitStatus


class Project(StrictModel):
    project_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    name: str = Field(min_length=1, max_length=200)
    created_at: datetime
    target_language: Literal["arabic"] = "arabic"

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Project name must not be blank.")
        return value


class SourceUnit(StrictModel):
    unit_id: str = Field(min_length=1)
    project_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    source_relpath: str
    source_line: int | None = Field(default=None, ge=1)
    renpy_identifier: str | None = None
    kind: UnitKind
    speaker: str | None = None
    label: str | None = None
    source_text: str
    old: str | None = None
    source_language: str = "auto"
    target_language: str = "ar"
    protected_tokens: tuple[str, ...] = ()
    context_before: tuple[str, ...] = ()
    context_after: tuple[str, ...] = ()
    source_sha256: str = ""
    confidence: Literal["official_template", "existing_template", "unverified"] = "unverified"
    source_location: str | None = None
    source_literal: str | None = None

    @field_validator("source_relpath")
    @classmethod
    def relative_path(cls, value: str) -> str:
        posix = PurePosixPath(value)
        windows = PureWindowsPath(value)
        if (
            not value
            or posix.is_absolute()
            or windows.drive
            or windows.root
            or ".." in posix.parts
            or "\\" in value
            or ":" in value
            or value == "."
        ):
            raise ValueError("Expected a safe POSIX relative source path.")
        return value

    @model_validator(mode="after")
    def check_source(self) -> "SourceUnit":
        if not self.renpy_identifier and self.source_line is None and self.source_location is None:
            raise ValueError("A real identifier or precise source line is required.")
        data = self.model_dump(
            mode="json",
            include=set(SourceUnit.model_fields) - {"unit_id", "project_id", "source_sha256"},
        )
        # New optional provenance fields do not invalidate phase-0 fingerprints.
        for field in ("source_location", "source_literal"):
            if data[field] is None:
                del data[field]
        if self.source_location is not None:
            data.pop(
                "confidence"
            )  # Derived confidence may improve without changing source identity.
        digest = hashlib.sha256(
            json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        if self.source_sha256 and self.source_sha256 != digest:
            raise ValueError("Source hash does not match source data.")
        object.__setattr__(self, "source_sha256", digest)
        return self

    @property
    def location_key(self) -> str:
        # This is a database key only; it never generates a Ren'Py identifier.
        if self.source_location is not None:
            return json.dumps([self.source_location, self.source_sha256])
        position = self.renpy_identifier or f"line:{self.source_line}"
        return json.dumps([self.source_relpath, self.kind.value, position])


class TranslationUnit(SourceUnit):
    translation_text: str | None = None
    status: UnitStatus = UnitStatus.PENDING


class ProviderResult(StrictModel):
    unit_id: str = Field(min_length=1)
    translation_text: str | None
    provider_id: str
    status: Literal["success", "error"]
    error: str | None = None
    usage: dict[str, int] | None = None
    simulated: bool = False

    @model_validator(mode="after")
    def valid_result(self) -> "ProviderResult":
        if self.status == "success" and self.translation_text is None:
            raise ValueError("A successful result requires translation_text.")
        if self.status == "error" and not self.error:
            raise ValueError("An error result requires an error code.")
        return self
