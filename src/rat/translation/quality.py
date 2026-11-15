import unicodedata
from collections import Counter, defaultdict

from rat.domain.models import SourceUnit
from rat.domain.review import QAIssue, QAResult
from rat.protection import MaskingEngine, ProtectionService


class QAEngine:
    """Structural blockers plus conservative language/layout warnings; no renderer claims."""

    def check(self, source: SourceUnit, text: str | None) -> QAResult:
        issues = []
        if any(
            unicodedata.category(char) in {"Cs", "Cc"} and char not in "\n\r\t"
            for char in source.source_text
        ):
            return QAResult(
                unit_id=source.unit_id,
                issues=(
                    QAIssue(
                        code="invalid_source",
                        affected_text=source.source_text,
                        message="Source contains unsupported control or surrogate characters.",
                    ),
                ),
            )
        if not isinstance(text, str):
            return QAResult(
                unit_id=source.unit_id,
                issues=(QAIssue(code="invalid_output", message="Translation must be text."),),
            )
        if not text.strip():
            issues.append(QAIssue(code="empty_translation", message="Translation is empty."))
        if any(
            unicodedata.category(char) in {"Cs", "Cc"} and char not in "\n\r\t" for char in text
        ):
            issues.append(
                QAIssue(
                    code="invalid_output",
                    affected_text=text,
                    message="Unsupported control or surrogate character.",
                )
            )
        if any(unicodedata.category(char) == "Cs" for char in text):
            return QAResult(unit_id=source.unit_id, issues=tuple(issues))
        original = MaskingEngine().mask(source.source_text)
        target = MaskingEngine().mask(text)
        for issue in target.issues:
            code = (
                "broken_tag_nesting"
                if issue.code in {"unclosed_tag", "mismatched_tag", "unexpected_closing_tag"}
                else "invalid_output"
            )
            issues.append(QAIssue(code=code, affected_text=issue.affected_text, message=issue.code))
        if not original.valid:
            issues.append(
                QAIssue(
                    code="invalid_source",
                    affected_text=source.source_text,
                    message="Source cannot be protected safely.",
                )
            )
        if original.protected and target.protected:
            for kinds, missing, changed in (
                ({"interpolation", "percent"}, "missing_placeholders", "changed_placeholders"),
                ({"tag"}, "missing_renpy_tags", "changed_renpy_tags"),
            ):
                before = Counter(
                    token.text for token in original.protected.tokens if token.kind in kinds
                )
                after = Counter(
                    token.text for token in target.protected.tokens if token.kind in kinds
                )
                if before != after:
                    code = missing if sum(after.values()) < sum(before.values()) else changed
                    issues.append(
                        QAIssue(
                            code=code,
                            affected_text=text,
                            message="Protected syntax differs from the source.",
                        )
                    )
        if not any(unicodedata.category(char) == "Cs" for char in text):
            validation = ProtectionService().validate_translation(source, text)
            if not validation.valid and not any(
                issue.code
                in {
                    "empty_translation",
                    "invalid_source",
                    "broken_tag_nesting",
                    "missing_placeholders",
                    "changed_placeholders",
                    "missing_renpy_tags",
                    "changed_renpy_tags",
                    "invalid_output",
                }
                for issue in issues
            ):
                issues.append(
                    QAIssue(
                        code="invalid_output",
                        affected_text=text,
                        message="Protected count, order or escaping changed.",
                    )
                )
        if (
            text.strip()
            and text.strip() == source.source_text.strip()
            and any(char.isascii() and char.isalpha() for char in text)
        ):
            issues.append(
                QAIssue(
                    code="suspicious_untranslated",
                    severity="warning",
                    affected_text=text,
                    message="Translation equals the source; proper names may be legitimate.",
                )
            )
        ratio = len(text) / max(1, len(source.source_text))
        risk = (
            "high"
            if len(text) > 300 or (len(text) > 80 and ratio > 2.5)
            else "medium"
            if len(text) > 160 or (len(text) > 40 and ratio > 1.7)
            else "low"
        )
        if len(text) > 1000 or (len(text) > 100 and ratio > 4):
            issues.append(
                QAIssue(
                    code="extremely_long_translation",
                    severity="warning",
                    affected_text=text,
                    message="Length is suspicious; game layout is not measured.",
                )
            )
        return QAResult(
            unit_id=source.unit_id, issues=tuple(issues), overflow_risk=risk, length_ratio=ratio
        )

    def audit(self, records):
        result = {
            record.unit_id: self.check(record.source, record.translation_text) for record in records
        }
        groups = defaultdict(list)
        for record in records:
            if record.translation_text and len(record.translation_text.strip()) >= 3:
                groups[record.translation_text.strip()].append(record)
        for text, group in groups.items():
            if len({record.source.source_text for record in group}) > 1:
                for record in group:
                    old = result[record.unit_id]
                    result[record.unit_id] = old.model_copy(
                        update={
                            "issues": old.issues
                            + (
                                QAIssue(
                                    code="duplicate_translation",
                                    severity="warning",
                                    affected_text=text,
                                    message="Different sources share a translation.",
                                ),
                            )
                        }
                    )
        return result
