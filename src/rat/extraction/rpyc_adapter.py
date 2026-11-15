"""Decompiler contract and a conservative, non-executing Ren'Py AST adapter."""

import re
import struct
from typing import Protocol

from rat.domain.discovery import EngineVersion
from rat.domain.packed import DecompiledSource, DecompilerCompatibility
from rat.exporters.renpy_writer import quote_renpy
from rat.security.pickle_data import PickleDataReader, Record, inflate


class DecompilerAdapter(Protocol):
    adapter_id: str

    def compatibility(self, engine: EngineVersion, data: bytes) -> DecompilerCompatibility: ...
    def decompile(self, data: bytes) -> DecompiledSource: ...


def rpyc_slots(data: bytes):
    if not data.startswith(b"RENPY RPC2"):
        raise ValueError("unsupported_legacy_or_obfuscated_rpyc")
    slots = {}
    ranges = []
    end = None
    for position in range(10, min(len(data), 10 + 12 * 16), 12):
        if position + 12 > len(data):
            raise ValueError("truncated_rpyc_header")
        slot, start, length = struct.unpack_from("<III", data, position)
        if slot == 0:
            end = position + 12
            break
        if slot in slots or slot not in {1, 2} or length <= 0 or start + length > len(data):
            raise ValueError("invalid_rpyc_slot")
        slots[slot] = (start, length)
        ranges.append((start, start + length))
    if end is None or 1 not in slots or any(start < end for start, _ in ranges):
        raise ValueError("invalid_rpyc_header")
    if len(ranges) == 2 and max(ranges[0][0], ranges[1][0]) < min(ranges[0][1], ranges[1][1]):
        raise ValueError("overlapping_rpyc_slots")
    return {
        slot: PickleDataReader(records=True).read(
            inflate(data[start : start + length], limit=32 * 1024 * 1024)
        )
        for slot, (start, length) in slots.items()
    }


def scalar(value):
    if isinstance(value, Record) and value.symbol.name == "PyExpr" and value.args:
        return value.args[0]
    return value


def sequence(value):
    if isinstance(value, Record) and value.symbol.name == "RevertableList":
        return value.sequence
    return value if type(value) in {tuple, list} else ()


class SourceLines(list):
    """Bound output during construction, including repeated references in an AST."""

    def __init__(self):
        super().__init__()
        self.bytes_written = 0

    def append(self, value):
        self.bytes_written += len(value.encode("utf-8")) + 1
        if self.bytes_written > 4 * 1024 * 1024:
            raise ValueError("decompiled_source_size_limit")
        super().append(value)

    def extend(self, values):
        for value in values:
            self.append(value)


class SafeRpycDecompiler:
    adapter_id = "rat-inert-rpyc-v1"

    def compatibility(self, engine: EngineVersion, data: bytes) -> DecompilerCompatibility:
        if engine.confidence == "conflict":
            return DecompilerCompatibility(supported=False, code="conflicting_engine_version")
        if not engine.version:
            return DecompilerCompatibility(supported=False, code="unknown_engine_version")
        if not re.fullmatch(r"\d+\.\d+\.\d+(?:\.\d+)?", engine.version):
            return DecompilerCompatibility(supported=False, code="invalid_engine_version")
        numbers = tuple(map(int, engine.version.split(".")[:3]))
        if numbers[0] != 8 or numbers < (8, 2, 0) or numbers >= (8, 6, 0):
            return DecompilerCompatibility(supported=False, code="unverified_rpyc_engine_family")
        if not data.startswith(b"RENPY RPC2"):
            return DecompilerCompatibility(supported=False, code="unsupported_rpyc_container")
        return DecompilerCompatibility(
            supported=True, code="inert_ast_supported", tested=numbers == (8, 5, 3)
        )

    def decompile(self, data: bytes) -> DecompiledSource:
        try:
            return self._decompile(data)
        except (TypeError, KeyError, IndexError, RecursionError, OverflowError) as error:
            raise ValueError("invalid_rpyc_ast_data") from error

    def _decompile(self, data: bytes) -> DecompiledSource:
        slots = rpyc_slots(data)
        root = slots.get(2, slots[1])
        if type(root) is not tuple or len(root) != 2 or type(root[0]) is not dict:
            raise ValueError("invalid_rpyc_ast_root")
        if root[0].get("key", "unlocked") != "unlocked":
            raise ValueError("locked_rpyc_not_supported")
        self.lines, self.warnings, self.visiting, self.count = SourceLines(), [], set(), 0
        self.emit_nodes(sequence(root[1]), 0)
        if not self.lines:
            raise ValueError("no_supported_rpyc_statements")
        text = "\n".join(self.lines) + "\n"
        if len(text.encode("utf-8")) > 4 * 1024 * 1024:
            raise ValueError("decompiled_source_size_limit")
        return DecompiledSource(
            text=text, partial=bool(self.warnings), warnings=tuple(dict.fromkeys(self.warnings))
        )

    def emit(self, node, text, indent):
        line = node.values.get("linenumber", 0)
        if type(line) is int and len(self.lines) < line <= 100000:
            self.lines.extend([""] * (line - len(self.lines) - 1))
        self.lines.append("    " * indent + text)

    def emit_nodes(self, nodes, indent):
        if indent > 64:
            raise ValueError("rpyc_ast_depth_limit")
        for node in nodes:
            self.count += 1
            if self.count > 100000 or not isinstance(node, Record) or id(node) in self.visiting:
                raise ValueError("invalid_or_cyclic_rpyc_ast")
            self.visiting.add(id(node))
            try:
                self.emit_node(node, indent)
            finally:
                self.visiting.remove(id(node))

    def emit_node(self, node, indent):
        name, values = node.symbol.name, node.values
        if node.symbol.module != "renpy.ast":
            self.skip(node, indent)
        elif name == "Label":
            label = values.get("name") or values.get("label") or values.get("_name")
            if type(label) is not str or not re.fullmatch(
                r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?", label
            ):
                self.skip(node, indent)
                return
            if values.get("parameters") is not None:
                self.warnings.append("label_parameters_not_reconstructed")
            self.emit(node, f"label {label}:", indent)
            first = len(self.lines)
            self.emit_nodes(sequence(values.get("block")), indent + 1)
            if not any(
                line.strip() and not line.lstrip().startswith("#") for line in self.lines[first:]
            ):
                self.lines.append("    " * (indent + 1) + "pass")
        elif name in {"Say", "TranslateSay"}:
            what, who = scalar(values.get("what")), scalar(values.get("who"))
            if type(what) is not str:
                self.skip(node, indent)
                return
            speaker = ""
            if who is not None:
                if type(who) is not str:
                    self.skip(node, indent)
                    return
                if re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", who):
                    speaker = who + " "
                elif who[:1] in {'"', "'"}:
                    import ast

                    try:
                        literal = ast.literal_eval(who)
                    except (SyntaxError, ValueError):
                        self.skip(node, indent)
                        return
                    if type(literal) is not str:
                        self.skip(node, indent)
                        return
                    speaker = quote_renpy(literal) + " "
                else:
                    self.skip(node, indent)
                    return
            attrs = sequence(values.get("attributes"))
            if attrs and speaker:
                if not all(
                    type(attr) is str and re.fullmatch(r"-?[A-Za-z_]\w*", attr) for attr in attrs
                ):
                    self.skip(node, indent)
                    return
                speaker += " ".join(attrs) + " "
            suffix = " nointeract" if values.get("interact") is False else ""
            identifier = values.get("identifier")
            if type(identifier) is str and re.fullmatch(r"[A-Za-z_]\w*", identifier):
                suffix += " id " + identifier
            self.emit(node, speaker + quote_renpy(what) + suffix, indent)
        elif name == "Menu":
            self.emit(node, "menu:", indent)
            for item in sequence(values.get("items")):
                if type(item) is not tuple or len(item) != 3 or type(item[0]) is not str:
                    raise ValueError("unsupported_rpyc_menu_item")
                text, condition, block = item
                if scalar(condition) not in {"True", True, None}:
                    self.warnings.append("menu_condition_omitted")
                if block is None:
                    self.lines.append("    " * (indent + 1) + quote_renpy(text))
                else:
                    self.lines.append("    " * (indent + 1) + quote_renpy(text) + ":")
                    first = len(self.lines)
                    self.emit_nodes(sequence(block), indent + 2)
                    if not any(
                        line.strip() and not line.lstrip().startswith("#")
                        for line in self.lines[first:]
                    ):
                        self.lines.append("    " * (indent + 2) + "pass")
        elif name == "Init":
            # Walk safe Ren'Py children, but never emit executable Python/init code.
            self.emit_nodes(sequence(values.get("block")), indent)
        elif name == "TranslateString":
            language, old, new = values.get("language"), values.get("old"), values.get("new")
            if language == "arabic" and type(old) is str and type(new) is str:
                import json

                self.emit(node, "translate arabic strings:", indent)
                self.lines.extend(
                    [
                        "    " * (indent + 1) + "old " + json.dumps(old, ensure_ascii=False),
                        "    " * (indent + 1) + "new " + json.dumps(new, ensure_ascii=False),
                    ]
                )
            else:
                self.skip(node, indent)
        elif name == "Translate":
            language, identifier = values.get("language"), values.get("identifier")
            if (
                language == "arabic"
                and type(identifier) is str
                and re.fullmatch(r"[A-Za-z_]\w*", identifier)
            ):
                # Compiled TL does not preserve original-comment text; never invent it.
                self.skip(node, indent)
            else:
                self.emit_nodes(sequence(values.get("block")), indent)
        elif name in {"Return", "Pass"}:
            if values.get("expression") is not None:
                self.warnings.append("return_expression_omitted")
            self.emit(node, "return" if name == "Return" else "pass", indent)
        elif name == "If":
            self.warnings.append("conditional_branches_flattened_for_analysis")
            for _condition, block in sequence(values.get("entries")):
                self.emit_nodes(sequence(block), indent)
        elif name in {"EndTranslate"}:
            pass
        else:
            self.skip(node, indent)

    def skip(self, node, indent):
        self.warnings.append("omitted_ast_node:" + node.symbol.name)
        self.emit(node, "# RAT analysis: omitted " + node.symbol.name + " (never executed)", indent)
