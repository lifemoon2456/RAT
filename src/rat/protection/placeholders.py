"""Read interpolation boundaries without evaluating any expression."""

import ast

from rat.domain.protection import ProtectionIssue


class PlaceholderDetector:
    def __init__(self, max_depth: int = 64):
        self.max_depth = max_depth

    def read(self, text: str, start: int) -> tuple[int, tuple[ProtectionIssue, ...]]:
        stack = ["["]
        index = start + 1
        expression_end = None
        conversion_start = None
        conversion_end = None
        mode = "expression"
        while index < len(text):
            char = text[index]
            if mode == "expression":
                if char in "\"'":
                    quote = char * (3 if text.startswith(char * 3, index) else 1)
                    index += len(quote)
                    while index < len(text) and not text.startswith(quote, index):
                        index += 2 if text[index] == "\\" else 1
                    if index >= len(text):
                        return self._error(text, start, len(text), "unterminated_interpolation")
                    index += len(quote)
                    continue
                if char in "([{":
                    stack.append(char)
                    if len(stack) > self.max_depth:
                        return self._error(text, start, index + 1, "nesting_limit")
                elif char in ")]}":
                    if stack[-1] != {")": "(", "]": "[", "}": "{"}[char]:
                        return self._error(text, start, index + 1, "mismatched_bracket")
                    stack.pop()
                    if not stack:
                        expression_end = index
                        break
                elif len(stack) == 1 and char == "!" and text[index + 1 : index + 2] != "=":
                    expression_end = index
                    conversion_start = index + 1
                    mode = "conversion"
                elif len(stack) == 1 and char == ":":
                    expression_end = index
                    mode = "format"
            else:
                if char == "]":
                    break
                if mode == "conversion":
                    if char == ":":
                        conversion_end = index
                        mode = "format"
                    elif char not in "rstiqulc!":
                        return self._error(text, start, index + 1, "invalid_conversion")
                elif char in "[{\r\n":
                    return self._error(text, start, index + 1, "unsupported_format")
            index += 1
        if index >= len(text):
            return self._error(text, start, len(text), "unterminated_interpolation")
        if conversion_start is not None:
            conversion = text[conversion_start : conversion_end or index]
            if not conversion.strip("!"):
                return self._error(text, start, index + 1, "invalid_conversion")
        expression = text[start + 1 : expression_end].strip()
        if expression.endswith("="):
            expression = expression[:-1].rstrip()  # Ren'Py debug-expression syntax.
        try:
            # Syntax only: never compile/eval, resolve names, or import game modules.
            ast.parse(expression, mode="eval")
        except (SyntaxError, ValueError, RecursionError):
            return self._error(text, start, index + 1, "invalid_expression")
        return index + 1, ()

    @staticmethod
    def _error(text: str, start: int, end: int, code: str):
        return end, (
            ProtectionIssue(
                code=code,
                affected_text=text[start:end],
                start=start,
                end=end,
                message="Interpolation cannot be protected safely; expression was not evaluated.",
            ),
        )

    def read_percent(self, text: str, start: int) -> tuple[int, tuple[ProtectionIssue, ...]]:
        """Recognize Python-style percent fields; ordinary percent signs stay literal."""
        index = start + 1
        named = index < len(text) and text[index] == "("
        if named:
            depth = 1
            index += 1
            key_start = index
            while index < len(text) and depth:
                depth += (text[index] == "(") - (text[index] == ")")
                if depth > self.max_depth:
                    return self._error(text, start, index + 1, "nesting_limit")
                index += 1
            if depth or index == key_start + 1:
                return self._error(text, start, index, "invalid_percent_placeholder")
        while index < len(text) and text[index] in "#0- +0123456789.*hlL":
            index += 1
        if index < len(text) and text[index] in "diouxXeEfFgGcrsa":
            return index + 1, ()
        if named:
            return self._error(text, start, index, "invalid_percent_placeholder")
        return start, ()
