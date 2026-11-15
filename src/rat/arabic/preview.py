import html
import re

from rat.protection import MaskingEngine
from rat.protection.tokenizer import TextTokenizer

PREVIEW_SAMPLE = "مرحبًا [player_name]! {b}المستوى 12{/b} — Build 42 / 123 — النتيجة ٣٤٥"
SAMPLE_VALUES = {"[player_name]": "Alex", "[score!s]": "123", "[points:03d]": "007"}


def preview_html(text: str, *, direction="auto") -> str:
    """Qt approximation only. Never evaluate game expressions or transform logical Unicode."""
    protected = MaskingEngine().mask(text)
    if not protected.valid:
        return html.escape(text)
    parts = []
    pairs = {
        "{b}": "<b>",
        "{/b}": "</b>",
        "{i}": "<i>",
        "{/i}": "</i>",
        "{u}": "<u>",
        "{/u}": "</u>",
        "{s}": "<s>",
        "{/s}": "</s>",
        "{/color}": "</span>",
    }
    for token in TextTokenizer().tokenize(text).tokens:
        if token.kind == "tag" and token.text in pairs:
            parts.append(pairs[token.text])
        elif token.kind == "tag" and re.fullmatch(r"\{color=#[0-9a-fA-F]{6}\}", token.text):
            parts.append('<span style="color:' + token.text[7:-1] + '">')
        else:
            value = (
                SAMPLE_VALUES.get(token.text, token.text)
                if token.kind == "interpolation"
                else {"[[": "[", "{{": "{", "%%": "%"}.get(token.text, token.text)
            )
            parts.append(html.escape(value).replace("\n", "<br>"))
    safe_direction = {"auto": "auto", "rtl": "rtl", "ltr": "ltr"}[direction]
    return f'<div dir="{safe_direction}">' + "".join(parts) + "</div>"
