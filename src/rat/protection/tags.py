"""Static tag policy and LIFO balance checks; never load custom game handlers."""

from collections.abc import Iterable

from rat.domain.protection import ProtectionIssue, TextToken

# Names checked against the installed Ren'Py 8.5.3 SDK's text/extras.py.
# This independently written policy is intentionally strict about explicit closure.
PAIRED_TAGS = frozenset(
    "alpha alt art axis instance feature b i u a plain font color outlinecolor size "
    "noalt s shader rt rb k cps".split()
) | {""}
SELF_CLOSING_TAGS = frozenset("done image p w fast nw space vspace clear".split())


class TagProtector:
    def __init__(
        self,
        *,
        custom_paired: Iterable[str] = (),
        custom_self_closing: Iterable[str] = (),
    ):
        paired = frozenset(custom_paired)
        single = frozenset(custom_self_closing)
        if paired & single or (paired | single) & (PAIRED_TAGS | SELF_CLOSING_TAGS):
            raise ValueError("Custom tags must not override built-in tag roles.")
        if any(not name.isidentifier() for name in paired | single):
            raise ValueError("Custom tag names must be identifiers.")
        self.paired = PAIRED_TAGS | paired
        self.single = SELF_CLOSING_TAGS | single

    def validate(self, tokens: Iterable[TextToken]) -> tuple[ProtectionIssue, ...]:
        stack: list[tuple[str, TextToken]] = []
        issues = []
        for token in tokens:
            if token.kind != "tag":
                continue
            body = token.text[1:-1] if token.text.endswith("}") else ""
            if body.startswith("#") and len(body) > 1 and "{" not in body:
                continue
            closing = body.startswith("/")
            descriptor = body[1:] if closing else body
            name, separator, argument = descriptor.partition("=")
            base, qualifier_separator, qualifier = name.partition(":")
            malformed = (
                not body
                or "{" in body
                or any(char.isspace() for char in name)
                or (separator and not argument)
                or (qualifier_separator and (not qualifier or not separator or closing))
                or (base == "" and not (separator or closing))
                or (closing and bool(separator))
            )
            if malformed:
                issues.append(self._issue("malformed_tag", token))
                continue
            if base not in self.paired | self.single:
                issues.append(self._issue("unknown_tag", token))
            elif closing:
                if base in self.single or not stack:
                    issues.append(self._issue("unexpected_closing_tag", token))
                elif stack[-1][0] != base:
                    issues.append(self._issue("mismatched_tag", token))
                else:
                    stack.pop()
            elif base in self.paired:
                stack.append((base, token))
        issues.extend(self._issue("unclosed_tag", token) for _, token in stack)
        return tuple(issues)

    @staticmethod
    def _issue(code: str, token: TextToken) -> ProtectionIssue:
        return ProtectionIssue(
            code=code,
            affected_text=token.text,
            start=token.start,
            end=token.end,
            message="Text tags must be known, explicitly closed, and correctly nested.",
        )
