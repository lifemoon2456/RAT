"""Derived protection for extracted units; never update immutable source fields."""

from collections.abc import Iterable

from rat.domain.models import SourceUnit
from rat.domain.protection import (
    ProtectionIssue,
    RestorationResult,
    UnitProtection,
    ValidationResult,
)
from rat.protection.masking import MaskingEngine
from rat.protection.restoration import RestorationEngine
from rat.protection.validator import ValidationEngine


class ProtectionService:
    def __init__(self, masking: MaskingEngine | None = None):
        self.masking = masking or MaskingEngine()
        self.validator = ValidationEngine(tokenizer=self.masking.tokenizer, tags=self.masking.tags)
        self.restoration = RestorationEngine(self.validator)

    def prepare_unit(self, source: SourceUnit) -> UnitProtection:
        source = SourceUnit.model_validate(source.model_dump(include=set(SourceUnit.model_fields)))
        return UnitProtection(
            unit_id=source.unit_id,
            source_sha256=source.source_sha256,
            result=self.masking.mask(source.source_text),
        )

    def prepare_units(self, sources: Iterable[SourceUnit]) -> tuple[UnitProtection, ...]:
        return tuple(self.prepare_unit(source) for source in sources)

    def restore_unit(
        self, source: SourceUnit, prepared: UnitProtection, translated_text: str
    ) -> RestorationResult:
        source = SourceUnit.model_validate(source.model_dump(include=set(SourceUnit.model_fields)))
        prepared = UnitProtection.model_validate(prepared.model_dump())
        if (
            prepared.unit_id != source.unit_id
            or prepared.source_sha256 != source.source_sha256
            or not prepared.ready
            or prepared.result.protected is None
            or prepared.result.protected.source_text != source.source_text
        ):
            return RestorationResult(
                issues=(
                    ProtectionIssue(
                        code="unit_protection_mismatch",
                        affected_text=translated_text,
                        start=0,
                        end=len(translated_text),
                        message="Protection belongs to another unit or source version.",
                        stage="mapping",
                    ),
                )
            )
        return self.restoration.restore(prepared.result.protected, translated_text)

    def validate_translation(self, source: SourceUnit, translation: str) -> ValidationResult:
        """Validate already-restored text, including translations imported from old templates."""
        prepared = self.prepare_unit(source)
        if not prepared.ready:
            return ValidationResult(issues=prepared.result.issues)
        if not isinstance(translation, str):
            return ValidationResult(
                issues=(self.validator._issue("invalid_translation_type", "", 0),)
            )
        translated = self.masking.mask(translation)
        if not translated.valid:
            return ValidationResult(
                issues=tuple(
                    issue.model_copy(update={"stage": "translation"}) for issue in translated.issues
                )
            )
        original_package = prepared.result.protected
        candidate = translated.protected
        assert original_package is not None and candidate is not None
        source_signature = [(item.kind, item.text) for item in original_package.tokens]
        candidate_signature = [(item.kind, item.text) for item in candidate.tokens]
        if source_signature != candidate_signature:
            return ValidationResult(
                issues=(
                    ProtectionIssue(
                        code="protected_structure_changed",
                        affected_text=translation,
                        start=0,
                        end=len(translation),
                        message="Translation changed protected syntax, count, or order.",
                        stage="translation",
                    ),
                )
            )
        if source.source_text.strip() and not translation.strip():
            return ValidationResult(
                issues=(self.validator._issue("empty_translation", translation, 0),)
            )
        return ValidationResult()
