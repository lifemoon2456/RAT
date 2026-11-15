"""Conservative, non-executing Ren'Py statement reader; not a Python interpreter."""

import ast
import re
from dataclasses import dataclass

from rat.domain.discovery import DiscoveryIssue, ParsedText
from rat.domain.enums import UnitKind
from rat.security.safe_paths import ScanError


@dataclass(frozen=True)
class LogicalLine:
    line: int
    indent: int
    code: str
    comment: bool = False


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    literal: str = ""


def _string_end(text: str, start: int) -> int:
    quote = text[start]
    delimiter = quote * 3 if text.startswith(quote * 3, start) else quote
    index = start + len(delimiter)
    while index < len(text):
        if text[index] == "\\":
            index += 2
        elif text.startswith(delimiter, index):
            return index + len(delimiter)
        else:
            index += 1
    raise ScanError("unterminated_literal")


def decode_literal(literal: str) -> str:
    raw = literal.startswith("r")
    value = literal[1:] if raw else literal
    delimiter = value[0] * (3 if value.startswith(value[0] * 3) else 1)
    value = value[len(delimiter) : -len(delimiter)]
    if raw:
        return value
    # Physical whitespace is folded before escaped spaces/newlines are expanded.
    value = re.sub(r"[ \n]+", " ", value.replace("\r\n", "\n"))
    output: list[str] = []
    index = 0
    while index < len(value):
        character = value[index]
        if character != "\\":
            output.append(character)
            index += 1
            continue
        index += 1
        if index == len(value):
            raise ScanError("invalid_escape")
        escaped = value[index]
        if escaped == "u":
            match = re.match(r"[0-9a-fA-F]{1,4}", value[index + 1 :])
            if not match:
                raise ScanError("invalid_unicode_escape")
            output.append(chr(int(match[0], 16)))
            index += 1 + len(match[0])
            continue
        output.append({"n": "\n", "[": "[[", "{": "{{", "%": "%%"}.get(escaped, escaped))
        index += 1
    return "".join(output)


def tokens(code: str) -> list[Token]:
    result: list[Token] = []
    index = 0
    while index < len(code):
        character = code[index]
        if character.isspace():
            index += 1
        elif character == "#":
            break
        elif character in "\"'`" or (
            character == "r" and index + 1 < len(code) and code[index + 1] in "\"'`"
        ):
            start = index
            quote_start = index + 1 if character == "r" else index
            index = _string_end(code, quote_start)
            literal = code[start:index]
            result.append(Token("string", decode_literal(literal), literal))
        elif character.isalpha() or character == "_":
            end = index + 1
            while end < len(code) and (code[end].isalnum() or code[end] in "_."):
                end += 1
            result.append(Token("word", code[index:end]))
            index = end
        else:
            result.append(Token("symbol", character))
            index += 1
    return result


def logical_lines(text: str) -> list[LogicalLine]:
    physical = text.replace("\r\n", "\n").replace("\r", "\n").splitlines(keepends=True)
    result = []
    index = 0
    while index < len(physical):
        first = physical[index]
        number = index + 1
        prefix = first[: len(first) - len(first.lstrip())]
        if "\t" in prefix:
            raise ScanError("tab_indentation")
        indent = len(first) - len(first.lstrip(" "))
        code = first[indent:]
        comment = code.startswith("#")
        if comment:
            code = code[1:].lstrip(" ")
        index += 1
        continuation_start = index
        if comment and not (
            code.startswith(('"', "'", "`", 'r"', "r'", "r`"))
            or re.match(r"""^[\w.]+(?:\s+[\w.]+)*\s+r?["'`]""", code)
        ):
            result.append(LogicalLine(number, indent, code.strip(), True))
            continue
        while True:
            if index - continuation_start > 256 or len(code) > 65536:
                raise ScanError("logical_line_limit")
            position = 0
            depth = 0
            unfinished = False
            while position < len(code):
                character = code[position]
                if character == "#":
                    break
                if character in "\"'`":
                    try:
                        position = _string_end(code, position)
                    except ScanError:
                        unfinished = True
                        break
                    continue
                if character in "([{":
                    depth += 1
                elif character in ")]}":
                    depth -= 1
                position += 1
            if not unfinished and depth <= 0 and not code.rstrip("\n").endswith("\\"):
                break
            if index >= len(physical):
                raise ScanError("unterminated_logical_line")
            following = physical[index]
            if comment:
                stripped = following.lstrip(" ")
                if not stripped.startswith("#"):
                    raise ScanError("unterminated_template_comment")
                following = stripped[1:]
                if following.startswith(" "):
                    following = following[1:]
            code += following
            index += 1
        result.append(LogicalLine(number, indent, code.strip(), comment))
    return result


_RESERVED = {
    "python",
    "init",
    "define",
    "default",
    "image",
    "scene",
    "show",
    "hide",
    "play",
    "stop",
    "queue",
    "voice",
    "nvl",
    "window",
    "pause",
    "jump",
    "call",
    "return",
    "pass",
    "label",
    "menu",
    "if",
    "elif",
    "else",
    "while",
    "screen",
    "translate",
    "style",
    "transform",
    "text",
    "textbutton",
    "use",
    "add",
    "on",
    "key",
    "timer",
    "old",
    "new",
    "extend",
}


def say_statement(code: str, line: int, *, label: str | None = None) -> ParsedText | None:
    values = tokens(code)
    if not values or values[0].value in _RESERVED:
        return None
    strings = [index for index, token in enumerate(values) if token.kind == "string"]
    if not strings:
        return None
    position = strings[-1]
    if len(strings) == 1:
        prefix = values[:position]
        if any(token.kind != "word" for token in prefix):
            return None
        speaker = prefix[0].value if prefix else None
    elif len(strings) == 2 and strings[0] == 0 and position == 1:
        speaker = values[0].value
    else:
        return None
    suffix = values[position + 1 :]
    identifier = None
    nointeract = False
    index = 0
    while index < len(suffix):
        if suffix[index].value == "nointeract" and not nointeract:
            nointeract = True
            index += 1
        elif (
            suffix[index].value == "id"
            and identifier is None
            and index + 1 < len(suffix)
            and suffix[index + 1].kind == "word"
        ):
            identifier = suffix[index + 1].value
            index += 2
        else:
            return None
    literal = values[position].literal
    if literal.lstrip("r").startswith(('"""', "'''")):
        return None  # Monologue splitting needs an engine-aware implementation.
    return ParsedText(
        text=values[position].value,
        literal=literal,
        line=line,
        speaker=speaker,
        label=label,
        renpy_identifier=identifier,
        kind=UnitKind.DIALOGUE if speaker else UnitKind.NARRATION,
    )


def parse_rpy(text: str) -> tuple[list[ParsedText], list[DiscoveryIssue]]:
    result: list[ParsedText] = []
    issues: list[DiscoveryIssue] = []
    frames: list[tuple[int, str]] = []
    label: str | None = None
    for statement in logical_lines(text):
        if statement.comment or not statement.code:
            continue
        while frames and statement.indent <= frames[-1][0]:
            frames.pop()
        if any(kind in {"python", "unknown", "translation"} for _, kind in frames):
            continue
        code = statement.code
        values = tokens(code)
        if not values:
            continue
        head = values[0].value
        if head == "$" or head in {"init", "python"}:
            issues.append(DiscoveryIssue(code="python_skipped", line=statement.line))
            if code.endswith(":"):
                frames.append((statement.indent, "python"))
            continue
        if head == "translate":
            if code.endswith(":"):
                frames.append((statement.indent, "translation"))
            continue
        match = re.fullmatch(r"label\s+([\w.]+)\s*:", code)
        if match:
            label = match[1]
            frames.append((statement.indent, "label"))
            continue
        if head == "screen" and code.endswith(":"):
            label = None
            frames.append((statement.indent, "screen"))
            continue
        in_menu = any(kind == "menu" for _, kind in frames)
        in_screen = any(kind == "screen" for _, kind in frames)
        in_label = any(kind == "label" for _, kind in frames)
        if head == "menu" and code.endswith(":") and in_label:
            frames.append((statement.indent, "menu"))
            continue
        if in_menu and values[0].kind == "string" and values[-1].value == ":":
            result.append(
                ParsedText(
                    text=values[0].value,
                    literal=values[0].literal,
                    line=statement.line,
                    kind=UnitKind.MENU_CHOICE,
                    label=label,
                )
            )
            frames.append((statement.indent, "choice"))
            continue
        if in_screen and head in {"text", "textbutton"}:
            arguments = values[1:]
            if arguments and arguments[0].value == "_":
                if len(arguments) >= 4 and arguments[1].value == "(" and arguments[3].value == ")":
                    arguments = [arguments[2], *arguments[4:]]
                else:
                    arguments = []
            if arguments and arguments[0].kind == "string":
                if len(arguments) > 1 and arguments[1].kind != "word":
                    issues.append(
                        DiscoveryIssue(code="dynamic_screen_text_skipped", line=statement.line)
                    )
                    continue
                try:
                    screen_text = ast.literal_eval(arguments[0].literal)
                except (ValueError, SyntaxError):
                    issues.append(
                        DiscoveryIssue(code="unsupported_screen_literal", line=statement.line)
                    )
                    continue
                result.append(
                    ParsedText(
                        text=screen_text,
                        literal=arguments[0].literal,
                        line=statement.line,
                        kind=UnitKind.SCREEN_TEXT,
                    )
                )
            else:
                issues.append(
                    DiscoveryIssue(code="dynamic_screen_text_skipped", line=statement.line)
                )
            continue
        parsed = say_statement(code, statement.line, label=label) if in_label else None
        if parsed:
            result.append(parsed)
            continue
        if code.endswith(":"):
            block = "control" if head in {"if", "elif", "else", "while"} and in_label else "unknown"
            frames.append((statement.indent, block))
        if head not in {
            "pass",
            "return",
            "scene",
            "show",
            "hide",
            "play",
            "stop",
            "voice",
            "window",
        }:
            issues.append(DiscoveryIssue(code="unsupported_source_statement", line=statement.line))
    return result, issues
