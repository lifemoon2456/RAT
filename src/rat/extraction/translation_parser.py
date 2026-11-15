import ast
import re

from rat.domain.discovery import DiscoveryIssue, ParsedText, TemplateText
from rat.domain.enums import UnitKind
from rat.extraction.rpy_parser import logical_lines, say_statement, tokens
from rat.security.safe_paths import ScanError, safe_relative


def parse_template(
    text: str, template_path: str, *, language: str = "arabic"
) -> tuple[list[TemplateText], list[DiscoveryIssue]]:
    template_path = safe_relative(template_path)
    result: list[TemplateText] = []
    issues: list[DiscoveryIssue] = []
    block: str | None = None
    block_indent = -1
    block_line = 0
    reference: tuple[str | None, int | None] = (None, None)
    old: ParsedText | None = None
    pending: list[ParsedText] = []
    new_lines: list[ParsedText] = []
    block_reference = reference
    invalid = False

    def flush() -> None:
        if block and block != "strings":
            if pending and not invalid:
                for index, original in enumerate(pending):
                    translated = new_lines[index].text if len(pending) == len(new_lines) else None
                    result.append(
                        TemplateText(
                            original=original,
                            identifier=block,
                            template_path=template_path,
                            template_line=original.line,
                            block_line=block_line,
                            reference_path=block_reference[0],
                            reference_line=block_reference[1],
                            translation=translated or None,
                        )
                    )
            elif invalid:
                issues.append(
                    DiscoveryIssue(code="unsupported_translation_block", path=template_path)
                )
            else:
                issues.append(DiscoveryIssue(code="missing_original_comment", path=template_path))
        if old is not None:
            issues.append(DiscoveryIssue(code="missing_new", path=template_path, line=old.line))

    for statement in logical_lines(text):
        code = statement.code
        ref_match = re.fullmatch(r"(.+):(\d+)", code) if statement.comment else None
        if ref_match:
            try:
                reference = (safe_relative(ref_match[1]), int(ref_match[2]))
            except ScanError:
                issues.append(DiscoveryIssue(code="unsafe_reference_path", path=template_path))
                reference = (None, None)
            continue
        if statement.comment:
            if block and block != "strings" and statement.indent > block_indent:
                original = say_statement(code, statement.line)
                if original:
                    pending.append(original)
            continue
        if not code:
            continue
        if statement.indent <= block_indent:
            flush()
            block, block_indent, old = None, -1, None
            pending, new_lines, invalid = [], [], False
        header = re.fullmatch(r"translate\s+([^\W\d]\w*)\s+([^\W\d][\w.]*)\s*:", code)
        if header and statement.indent == 0:
            if header[1] == language and header[2] not in {"python", "style"}:
                block = header[2]
                block_indent = statement.indent
                block_line = statement.line
                block_reference = reference
            continue
        if block is None:
            continue
        if block == "strings":
            values = tokens(code)
            if (
                len(values) != 2
                or values[1].kind != "string"
                or values[0].value not in {"old", "new"}
            ):
                issues.append(
                    DiscoveryIssue(
                        code="unsupported_string_entry", path=template_path, line=statement.line
                    )
                )
                old = None
                continue
            if values[0].value == "old":
                if old is not None:
                    issues.append(
                        DiscoveryIssue(code="missing_new", path=template_path, line=old.line)
                    )
                try:
                    value = ast.literal_eval(values[1].literal)
                    if not isinstance(value, str):
                        raise ValueError("not_a_string")
                except (SyntaxError, ValueError):
                    issues.append(
                        DiscoveryIssue(
                            code="invalid_string_literal", path=template_path, line=statement.line
                        )
                    )
                    old = None
                    continue
                old = ParsedText(
                    text=value,
                    literal=values[1].literal,
                    line=statement.line,
                    kind=UnitKind.STRING,
                )
            elif old is None:
                issues.append(
                    DiscoveryIssue(code="new_without_old", path=template_path, line=statement.line)
                )
            else:
                try:
                    value = ast.literal_eval(values[1].literal)
                    if not isinstance(value, str):
                        raise ValueError("not_a_string")
                except (SyntaxError, ValueError):
                    issues.append(
                        DiscoveryIssue(
                            code="invalid_string_literal", path=template_path, line=statement.line
                        )
                    )
                    old = None
                    continue
                result.append(
                    TemplateText(
                        original=old,
                        identifier=None,
                        template_path=template_path,
                        template_line=old.line,
                        block_line=block_line,
                        reference_path=reference[0],
                        reference_line=reference[1],
                        translation=value or None,
                        is_string=True,
                    )
                )
                old = None
        else:
            translated = say_statement(code, statement.line)
            if translated:
                new_lines.append(translated)
            elif code != "pass" and tokens(code)[0].value not in {"voice", "nvl"}:
                invalid = True
    flush()
    return result, issues
