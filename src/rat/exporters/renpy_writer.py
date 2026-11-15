import json
import re
import unicodedata
from collections import defaultdict

from rat.domain.review import ExportProblem
from rat.exporters.safe_io import relative_export_path
from rat.extraction.rpy_parser import _string_end, logical_lines, say_statement, tokens
from rat.extraction.translation_parser import parse_template


def quote_renpy(text: str) -> str:
    """Encode decoded text once, preserving whitespace and Ren'Py markup."""
    parts = ['"']
    for char in text:
        if char == "\\":
            parts.append("\\\\")
        elif char == '"':
            parts.append('\\"')
        elif char == "\n":
            parts.append("\\n")
        elif char == " ":
            parts.append("\\ ")
        elif char in "\r\t" or unicodedata.category(char) in {"Zl", "Zp"}:
            parts.append(f"\\u{ord(char):04x}")
        elif unicodedata.category(char) in {"Cs", "Cc"}:
            raise ValueError("invalid_output")
        else:
            parts.append(char)
    return "".join(parts) + '"'


def replace_say_literal(code: str, text: str) -> str:
    if say_statement(code, 1) is None:
        raise ValueError("unsupported_say_statement")
    spans = []
    index = 0
    while index < len(code):
        if code[index] == "#":
            break
        if code[index] in "\"'`" or (
            code[index] == "r" and code[index + 1 : index + 2] in {"'", '"', "`"}
        ):
            start = index
            quote_start = index + 1 if code[index] == "r" else index
            index = _string_end(code, quote_start)
            spans.append((start, index))
        else:
            index += 1
    start, end = spans[-1]
    return code[:start] + quote_renpy(text) + code[end:]


class RenPyWriter:
    def render(self, path, template, selected, origins):
        if any(
            unicodedata.category(char) in {"Cs", "Cc"} and char not in "\n\r\t" for char in template
        ):
            return "", (), (ExportProblem(code="invalid_template", path=path),)
        entries, issues = parse_template(template, path)
        problems = [ExportProblem(code=issue.code, path=path) for issue in issues]
        if problems:
            return "", (), tuple(problems)
        identifiers = defaultdict(set)
        for entry in entries:
            if entry.identifier:
                identifiers[entry.identifier].add(entry.block_line)
        if any(len(locations) > 1 for locations in identifiers.values()):
            return "", (), (ExportProblem(code="duplicate_translation_id", path=path),)
        by_position = {
            (origins[record.unit_id].template_path, origins[record.unit_id].template_line): record
            for record in selected
            if record.unit_id in origins
        }
        groups = defaultdict(list)
        for entry in entries:
            groups[entry.block_line].append(entry)
        statements = logical_lines(template)
        blocks = {}
        current = None
        for statement in statements:
            if (
                statement.indent == 0
                and not statement.comment
                and statement.code.startswith("translate ")
            ):
                current = statement.line
                blocks[current] = []
            elif current is not None:
                blocks[current].append(statement)
        output, exported, used_strings = [], [], set()
        for block_line, group in sorted(groups.items()):
            matches = [by_position.get((path, entry.template_line)) for entry in group]
            if not any(matches):
                continue
            for entry, record in zip(group, matches, strict=True):
                if record and (
                    record.source.source_text != entry.original.text
                    or record.source.old != (entry.original.text if entry.is_string else None)
                    or record.source.renpy_identifier != entry.identifier
                ):
                    problems.append(
                        ExportProblem(
                            code="template_source_mismatch", unit_id=record.unit_id, path=path
                        )
                    )
                    matches = []
                    break
            if not matches:
                continue
            if group[0].is_string:
                lines = []
                for entry, record in zip(group, matches, strict=True):
                    if record is None:
                        continue
                    if entry.original.text in used_strings:
                        problems.append(
                            ExportProblem(
                                code="duplicate_string", unit_id=record.unit_id, path=path
                            )
                        )
                        continue
                    used_strings.add(entry.original.text)
                    if entry.reference_path and entry.reference_line:
                        lines.append(
                            "    # "
                            + relative_export_path(entry.reference_path)
                            + f":{entry.reference_line}"
                        )
                    lines.extend(
                        (
                            f"    old {entry.original.literal}",
                            "    new "
                            + json.dumps(record.translation_text, ensure_ascii=False)
                            .replace("\u2028", "\\u2028")
                            .replace("\u2029", "\\u2029"),
                            "",
                        )
                    )
                    exported.append(record.unit_id)
                if lines:
                    output.append("translate arabic strings:\n\n" + "\n".join(lines))
                continue
            if not all(matches):
                problems.extend(
                    ExportProblem(code="partial_dialogue_block", unit_id=record.unit_id, path=path)
                    for record in matches
                    if record
                )
                continue
            body = blocks.get(block_line, [])
            says = [
                statement
                for statement in body
                if not statement.comment and say_statement(statement.code, statement.line)
            ]
            allowed = all(
                statement.comment
                or not statement.code
                or say_statement(statement.code, statement.line)
                or statement.code in {"pass", "nvl clear", "nvl show", "nvl hide"}
                or (
                    len(tokens(statement.code)) == 2
                    and tokens(statement.code)[0].value == "voice"
                    and tokens(statement.code)[1].kind == "string"
                )
                for statement in body
            )
            identifier = group[0].identifier
            if (
                len(says) != len(group)
                or not allowed
                or not identifier
                or not re.fullmatch(r"[^\W\d][\w.]*", identifier)
            ):
                problems.extend(
                    ExportProblem(
                        code="unsupported_translation_block", unit_id=record.unit_id, path=path
                    )
                    for record in matches
                )
                continue
            lines = []
            ref = group[0]
            if ref.reference_path and ref.reference_line:
                lines.append(f"# {relative_export_path(ref.reference_path)}:{ref.reference_line}")
            lines.extend((f"translate arabic {identifier}:", ""))
            replacements = {
                statement.line: record for statement, record in zip(says, matches, strict=True)
            }
            for statement in body:
                if not statement.code:
                    continue
                if statement.comment:
                    lines.append("    # " + statement.code.replace("\n", "\n    # "))
                elif statement.line in replacements:
                    record = replacements[statement.line]
                    lines.append(
                        "    " + replace_say_literal(statement.code, record.translation_text)
                    )
                    exported.append(record.unit_id)
                else:
                    lines.append("    " + statement.code)
            output.append("\n".join(lines) + "\n")
        text = "\n".join(output)
        # Parse the emitted form again before it can leave staging.
        if text:
            reparsed, errors = parse_template(text, path)
            actual = [(item.identifier, item.original.text, item.translation) for item in reparsed]
            lookup = {record.unit_id: record for record in selected}
            expected = [
                (
                    lookup[unit_id].source.renpy_identifier,
                    lookup[unit_id].source.source_text,
                    lookup[unit_id].translation_text,
                )
                for unit_id in exported
            ]
            if errors or actual != expected:
                return (
                    "",
                    (),
                    tuple(problems + [ExportProblem(code="output_roundtrip_failed", path=path)]),
                )
        return text, tuple(exported), tuple(problems)
