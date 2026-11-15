import hashlib
from uuid import uuid4

from rat.domain.protection import MaskingResult, ProtectedText, ProtectedToken
from rat.protection.tags import TagProtector
from rat.protection.tokenizer import TextTokenizer


def marker_for(namespace: str, ordinal: int) -> str:
    return f"⟦PH_{namespace}_{ordinal:04d}⟧"


class MaskingEngine:
    def __init__(self, *, tokenizer: TextTokenizer | None = None, tags: TagProtector | None = None):
        self.tokenizer = tokenizer or TextTokenizer()
        self.tags = tags or TagProtector()

    def mask(self, source_text: str) -> MaskingResult:
        parsed = self.tokenizer.tokenize(source_text)
        issues = parsed.issues + self.tags.validate(parsed.tokens)
        if issues:
            return MaskingResult(issues=issues)
        namespace = uuid4().hex
        protected = []
        parts = []
        for token in parsed.tokens:
            if token.kind == "text":
                parts.append(token.text)
                continue
            marker = marker_for(namespace, len(protected) + 1)
            protected.append(ProtectedToken(**token.model_dump(), marker=marker))
            parts.append(marker)
        return MaskingResult(
            protected=ProtectedText(
                source_text=source_text,
                source_text_sha256=hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
                namespace=namespace,
                masked_text="".join(parts),
                tokens=tuple(protected),
            )
        )
