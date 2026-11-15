from rat.domain.protection import ProtectedText, RestorationResult
from rat.protection.validator import ValidationEngine


class RestorationEngine:
    def __init__(self, validator: ValidationEngine | None = None):
        self.validator = validator or ValidationEngine()

    def restore(self, protected: ProtectedText, translated_text: str) -> RestorationResult:
        validation = self.validator.validate(protected, translated_text)
        if not validation.valid:
            # No partial text is exposed as an accepted translation.
            return RestorationResult(issues=validation.issues)
        occurrences, _ = self.validator._markers(translated_text)
        return RestorationResult(
            text=self.validator._replace(protected, translated_text, occurrences)
        )
