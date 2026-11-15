"""Isolated unofficial Google adapter. A parent process enforces the hard deadline."""

import json
import sys
from pathlib import Path

from rat.protection.validator import ValidationEngine


def translate_segments(text, translate):
    occurrences, issues = ValidationEngine._markers(text)
    if issues:
        raise ValueError("malformed_markers")
    parts = []
    previous = 0
    for marker, start, end in [*occurrences, ("", len(text), len(text))]:
        plain = text[previous:start]
        # Preserve all markers locally. Only natural-language spans reach this service.
        for offset in range(0, len(plain), 2400):
            chunk = plain[offset : offset + 2400]
            if chunk.strip():
                left = chunk[: len(chunk) - len(chunk.lstrip())]
                right = chunk[len(chunk.rstrip()) :]
                result = translate(chunk.strip())
                if not isinstance(result, str) or not result.strip():
                    raise ValueError("invalid_response")
                parts.append(left + result + right)
            else:
                parts.append(chunk)
        parts.append(marker)
        previous = end
    return "".join(parts)


def run(input_path: Path, output_path: Path) -> int:
    try:
        from deep_translator import GoogleTranslator

        if input_path.stat().st_size > 2_000_000:
            raise ValueError("large_input")
        request = json.loads(input_path.read_text(encoding="utf-8"))
        translator = GoogleTranslator(source=request["source"], target=request["target"])
        result = {
            "translations": [
                {
                    "unit_id": item["unit_id"],
                    "text": translate_segments(item["text"], translator.translate),
                }
                for item in request["items"]
            ]
        }
    except Exception as error:
        code = "rate_limit" if type(error).__name__ == "TooManyRequests" else "google_failed"
        result = {"error": code}
    output_path.write_text(json.dumps(result, ensure_ascii=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(run(Path(sys.argv[1]), Path(sys.argv[2])))
