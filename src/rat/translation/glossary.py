import csv
import io
import json
from pathlib import Path
from uuid import uuid4

from rat.domain.translation import GlossaryTerm
from rat.protection import MaskingEngine
from rat.protection.validator import ValidationEngine


class GlossarySystem:
    def __init__(self, terms=()):
        self.terms = tuple(
            GlossaryTerm.model_validate(
                term.model_dump() if isinstance(term, GlossaryTerm) else term
            )
            for term in terms
        )
        if len(self.terms) > 1000:
            raise ValueError("glossary_too_large")
        seen = set()
        for term in self.terms:
            if not term.source.strip() or not term.target.strip():
                raise ValueError("empty_glossary_term")
            parsed_source = MaskingEngine().mask(term.source)
            if not parsed_source.valid or parsed_source.protected.tokens:
                raise ValueError("glossary_source_contains_syntax")
            key = term.source if term.case_sensitive else term.source.casefold()
            if key in seen:
                raise ValueError("conflicting_glossary")
            seen.add(key)
            target = MaskingEngine().mask(term.target)
            if not target.valid or target.protected.tokens:
                raise ValueError("glossary_target_contains_syntax")

    @classmethod
    def from_csv(cls, path: Path):
        if path.stat().st_size > 262144:
            raise ValueError("glossary_too_large")
        rows = csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig")))
        if not {"source", "target"}.issubset(rows.fieldnames or []):
            raise ValueError("glossary_headers")

        def boolean(value, default):
            if value in {None, ""}:
                return default
            if value.lower() not in {"true", "false", "1", "0"}:
                raise ValueError("glossary_boolean")
            return value.lower() in {"true", "1"}

        return cls(
            [
                GlossaryTerm(
                    source=row["source"],
                    target=row["target"],
                    notes=row.get("notes") or "",
                    locked=boolean(row.get("locked"), True),
                    case_sensitive=boolean(row.get("case_sensitive"), True),
                )
                for row in rows
            ]
        )

    def payload(self):
        return [term.model_dump(mode="json") for term in self.terms]

    def mask(self, text):
        namespace = uuid4().hex
        occurrences, errors = ValidationEngine._markers(text)
        if errors:
            raise ValueError("invalid_glossary_input")
        protected = {start: (marker, end) for marker, start, end in occurrences}
        mappings, parts = [], []
        index = 0
        terms = sorted(
            (term for term in self.terms if term.locked), key=lambda term: -len(term.source)
        )
        while index < len(text):
            if index in protected:
                marker, index = protected[index]
                parts.append(marker)
                continue
            match = None
            for term in terms:
                piece = text[index : index + len(term.source)]
                equal = (
                    piece == term.source
                    if term.case_sensitive
                    else piece.casefold() == term.source.casefold()
                )
                end = index + len(term.source)
                # Names match whole words, not fragments of another name or a transport marker.
                boundary = (
                    not term.source[0].isalnum() or index == 0 or not text[index - 1].isalnum()
                ) and (not term.source[-1].isalnum() or end == len(text) or not text[end].isalnum())
                if equal and boundary and "⟦" not in piece and "⟧" not in piece:
                    match = term
                    break
            if match:
                marker = f"⟦GL_{namespace}_{len(mappings) + 1:04d}⟧"
                mappings.append({"marker": marker, "target": match.target})
                parts.append(marker)
                index += len(match.source)
            else:
                parts.append(text[index])
                index += 1
        return "".join(parts), mappings

    @staticmethod
    def restore(text, mappings):
        occurrences, issues = ValidationEngine._markers(text)
        actual = [marker for marker, _, _ in occurrences if marker.startswith("⟦GL_")]
        expected = [item["marker"] for item in mappings]
        if issues or actual != expected:
            raise ValueError("glossary_markers_changed")
        lookup = {item["marker"]: item["target"] for item in mappings}
        parts, previous = [], 0
        for marker, start, end in occurrences:
            parts.extend((text[previous:start], lookup.get(marker, marker)))
            previous = end
        parts.append(text[previous:])
        return "".join(parts)

    def fingerprint(self):
        return json.dumps(self.payload(), ensure_ascii=False, sort_keys=True)
