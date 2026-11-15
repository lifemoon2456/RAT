"""Bounded stateful scanner of decoded Ren'Py text, not .rpy source code."""

from rat.domain.protection import ProtectionIssue, TextToken, TokenizationResult
from rat.protection.placeholders import PlaceholderDetector

MAX_TEXT_LENGTH = 65_536
MAX_TOKENS = 4096


class TextTokenizer:
    def __init__(self, *, max_length: int = MAX_TEXT_LENGTH, max_tokens: int = MAX_TOKENS):
        self.max_length = max_length
        self.max_tokens = max_tokens
        self.placeholders = PlaceholderDetector()

    def tokenize(self, text: str) -> TokenizationResult:
        if len(text) > self.max_length:
            return TokenizationResult(
                issues=(self._issue("text_length_limit", text, 0, len(text)),)
            )
        output: list[TextToken] = []
        issues: list[ProtectionIssue] = []
        index = plain_start = 0
        while index < len(text):
            start = index
            char = text[index]
            kind = None
            end = index + 1
            if text.startswith(("[[", "{{", "%%", "〖〖"), index):
                kind, end = "escape", index + 2
            elif char == "[":
                kind = "interpolation"
                end, errors = self.placeholders.read(text, index)
                issues.extend(errors)
            elif char == "{":
                kind = "tag"
                while end < len(text) and text[end] != "}":
                    if text.startswith("[[", end):
                        end += 2
                    elif text[end] == "[":
                        end, errors = self.placeholders.read(text, end)
                        issues.extend(errors)
                    else:
                        end += 1
                if end == len(text):
                    issues.append(self._issue("unterminated_tag", text, start, end))
                else:
                    end += 1
            elif char == "\\":
                # Already-decoded text: a literal slash does not escape a following [ or {.
                kind = "escape"
                end = (
                    index + 2
                    if text[index + 1 : index + 2] in {"n", "r", "t", "\\", '"', "'"}
                    else index + 1
                )
            elif char in "\r\n\t":
                kind = "newline" if char in "\r\n" else "escape"
                end = index + 2 if text.startswith("\r\n", index) else index + 1
            elif char == "%":
                end, errors = self.placeholders.read_percent(text, index)
                issues.extend(errors)
                if end > index:
                    kind = "percent"
                else:
                    end = index + 1
            elif char in "⟦⟧":
                issues.append(self._issue("reserved_marker_in_source", text, start, end))
            elif char == "〖":
                issues.append(self._issue("unsupported_ruby", text, start, end))
            if kind is None:
                index = end
                continue
            if plain_start < start:
                output.append(
                    TextToken(
                        kind="text", text=text[plain_start:start], start=plain_start, end=start
                    )
                )
            output.append(TextToken(kind=kind, text=text[start:end], start=start, end=end))
            index = plain_start = end
            if len(output) > self.max_tokens:
                issues.append(self._issue("token_count_limit", text, start, end))
                return TokenizationResult(tokens=tuple(output), issues=tuple(issues))
        if plain_start < len(text):
            output.append(
                TextToken(kind="text", text=text[plain_start:], start=plain_start, end=len(text))
            )
        return TokenizationResult(tokens=tuple(output), issues=tuple(issues))

    @staticmethod
    def _issue(code: str, text: str, start: int, end: int) -> ProtectionIssue:
        return ProtectionIssue(
            code=code,
            affected_text=text[start:end],
            start=start,
            end=end,
            message="Text contains unsupported or malformed protection syntax.",
        )
