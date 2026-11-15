"""Reject damaged transport markers and reparse the restored text independently."""

import hashlib
from collections import Counter

from pydantic import ValidationError

from rat.domain.protection import ProtectedText, ProtectionIssue, ValidationResult
from rat.protection.masking import marker_for
from rat.protection.tags import TagProtector
from rat.protection.tokenizer import MAX_TOKENS, TextTokenizer

MAX_TRANSLATED_LENGTH = 524_288


class ValidationEngine:
    def __init__(self, *, tokenizer: TextTokenizer | None = None, tags: TagProtector | None = None):
        self.tokenizer = tokenizer or TextTokenizer()
        self.tags = tags or TagProtector()

    def validate(self, protected: ProtectedText, translated_text: str) -> ValidationResult:
        checked, issues = self._mapping(protected)
        if issues:
            return ValidationResult(issues=issues)
        assert checked is not None
        if not isinstance(translated_text, str):
            return ValidationResult(issues=(self._issue("invalid_translation_type", "", 0),))
        if len(translated_text) > MAX_TRANSLATED_LENGTH:
            return ValidationResult(
                issues=(self._issue("translation_length_limit", translated_text, 0),)
            )
        occurrences, errors = self._markers(translated_text)
        issues = list(errors)
        expected = [token.marker for token in checked.tokens]
        actual = [marker for marker, _, _ in occurrences]
        expected_set = set(expected)
        counts = Counter(actual)
        first_positions = {}
        for marker, start, _ in occurrences:
            first_positions.setdefault(marker, start)
            if marker not in expected_set:
                issues.append(self._issue("unknown_marker", marker, start))
        for marker in expected:
            if not counts[marker]:
                issues.append(self._issue("missing_marker", marker, 0))
            elif counts[marker] > 1:
                issues.append(self._issue("duplicate_marker", marker, first_positions[marker]))
        if not issues and actual != expected:
            issues.append(self._issue("marker_order", translated_text, 0))
        if issues:
            return ValidationResult(issues=tuple(issues))
        restored = self._replace(checked, translated_text, occurrences)
        parsed = self.tokenizer.tokenize(restored)
        issues.extend(
            error.model_copy(update={"stage": "translation"})
            for error in parsed.issues + self.tags.validate(parsed.tokens)
        )
        source_signature = [(token.kind, token.text) for token in checked.tokens]
        restored_signature = [
            (token.kind, token.text) for token in parsed.tokens if token.kind != "text"
        ]
        if source_signature != restored_signature:
            issues.append(self._issue("protected_structure_changed", restored, 0))
        if checked.source_text.strip() and not restored.strip():
            issues.append(self._issue("empty_translation", restored, 0))
        return ValidationResult(issues=tuple(issues))

    def _mapping(
        self, protected: ProtectedText
    ) -> tuple[ProtectedText | None, tuple[ProtectionIssue, ...]]:
        """Recheck even model_copy/serialized maps; do not trust a caller's map or offsets."""
        try:
            package = ProtectedText.model_validate(protected.model_dump())
        except (ValidationError, AttributeError, TypeError):
            return None, (self._issue("invalid_protection_map", "", 0, stage="mapping"),)
        source = package.source_text
        parsed = self.tokenizer.tokenize(source)
        source_tokens = [token for token in parsed.tokens if token.kind != "text"]
        expected_tokens = []
        parts = []
        ordinal = 0
        for token in parsed.tokens:
            if token.kind == "text":
                parts.append(token.text)
            else:
                ordinal += 1
                marker = marker_for(package.namespace, ordinal)
                expected_tokens.append({**token.model_dump(), "marker": marker})
                parts.append(marker)
        valid_namespace = len(package.namespace) == 32 and all(
            char in "0123456789abcdef" for char in package.namespace
        )
        invalid = (
            not valid_namespace
            or parsed.issues
            or self.tags.validate(source_tokens)
            or len(package.tokens) > MAX_TOKENS
            or hashlib.sha256(source.encode("utf-8")).hexdigest() != package.source_text_sha256
            or [token.model_dump() for token in package.tokens] != expected_tokens
            or package.masked_text != "".join(parts)
        )
        if invalid:
            return None, (self._issue("invalid_protection_map", source, 0, stage="mapping"),)
        return package, ()

    @staticmethod
    def _markers(text: str) -> tuple[list[tuple[str, int, int]], tuple[ProtectionIssue, ...]]:
        occurrences = []
        issues = []
        index = 0
        while index < len(text):
            if text[index] == "⟦":
                end = index + 1
                while end < len(text) and text[end] not in "⟦⟧":
                    end += 1
                if end == len(text) or text[end] != "⟧":
                    issues.append(
                        ValidationEngine._issue("malformed_marker", text[index:end], index)
                    )
                    index = end
                    continue
                end += 1
                occurrences.append((text[index:end], index, end))
                index = end
            elif text[index] == "⟧":
                issues.append(ValidationEngine._issue("malformed_marker", "⟧", index))
                index += 1
            else:
                index += 1
        return occurrences, tuple(issues)

    @staticmethod
    def _replace(
        protected: ProtectedText, text: str, occurrences: list[tuple[str, int, int]]
    ) -> str:
        mapping = {token.marker: token.text for token in protected.tokens}
        parts = []
        previous = 0
        for marker, start, end in occurrences:
            parts.extend((text[previous:start], mapping[marker]))
            previous = end
        parts.append(text[previous:])
        return "".join(parts)

    @staticmethod
    def _issue(
        code: str, affected: str, start: int, *, stage: str = "translation"
    ) -> ProtectionIssue:
        return ProtectionIssue(
            code=code,
            affected_text=affected,
            start=start,
            end=start + len(affected),
            message="Protection validation failed; translation must not be accepted or exported.",
            stage=stage,
        )
