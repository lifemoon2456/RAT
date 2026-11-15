from enum import StrEnum

from pydantic import Field, model_validator

from rat.domain.base import StrictModel
from rat.domain.models import TranslationUnit


class ReviewStatus(StrEnum):
    UNTRANSLATED = "untranslated"
    TRANSLATED = "translated"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    ERROR = "error"
    LOCKED = "locked"


class QAIssue(StrictModel):
    code: str
    severity: str = "error"
    affected_text: str = ""
    message: str


class QAResult(StrictModel):
    unit_id: str
    issues: tuple[QAIssue, ...] = ()
    overflow_risk: str = "low"
    length_ratio: float = 1.0

    @property
    def valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)


class EditorUnit(StrictModel):
    source: TranslationUnit
    translation_text: str | None
    provider_id: str = ""
    state: ReviewStatus = ReviewStatus.UNTRANSLATED
    locked: bool = False
    skipped: bool = False
    revision: int = 0
    qa: QAResult | None = None

    @property
    def unit_id(self) -> str:
        return self.source.unit_id

    @property
    def status(self) -> ReviewStatus:
        return ReviewStatus.LOCKED if self.locked else self.state


class TranslationAlternative(StrictModel):
    alternative_id: str
    unit_id: str
    source_sha256: str
    text: str
    provider_id: str
    simulated: bool = False
    created_at: str


class ExportProblem(StrictModel):
    code: str
    unit_id: str | None = None
    path: str | None = None


class ExportReport(StrictModel):
    export_id: str
    status: str
    destination: str
    approved_only: bool = True
    exported: tuple[str, ...] = ()
    skipped: tuple[ExportProblem, ...] = ()
    errors: tuple[ExportProblem, ...] = ()
    created_files: tuple[str, ...] = ()
    file_hashes: dict[str, str] = Field(default_factory=dict)
    arabic_runtime: dict = Field(default_factory=dict)
    exported_count: int = 0
    skipped_count: int = 0
    error_count: int = 0

    @model_validator(mode="after")
    def derive_counts(self):
        object.__setattr__(self, "exported_count", len(self.exported))
        object.__setattr__(self, "skipped_count", len(self.skipped))
        object.__setattr__(self, "error_count", len(self.errors))
        return self
