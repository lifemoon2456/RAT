import json
import re
from pathlib import Path

from rat.domain.discovery import EngineVersion
from rat.security.safe_paths import ScanError, read_source


def detect_version(root: Path) -> EngineVersion:
    evidence: list[tuple[str, str, str]] = []
    rules = (
        ("renpy/__init__.py", r"(?m)^version_tuple\s*=\s*\((\d+),\s*(\d+),\s*(\d+)", "static"),
        ("renpy/vc_version.py", r"""(?m)^version\s*=\s*["'](\d+)\.(\d+)\.(\d+)""", "static"),
        ("log.txt", r"(?m)^Ren'Py (\d+)\.(\d+)\.(\d+)(?:\.|\s|$)", "reported"),
    )
    for relpath, pattern, confidence in rules:
        try:
            content = read_source(root / relpath, max_bytes=1024 * 1024)
        except (OSError, ScanError):
            continue
        match = re.search(pattern, content)
        if match:
            evidence.append((".".join(match.groups()), relpath, confidence))
    try:
        metadata = json.loads(read_source(root / "renpy/vc_version.json", max_bytes=65536))
        value = metadata.get("version", "") if isinstance(metadata, dict) else ""
        match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:\.\d+)?", str(value))
        if match:
            evidence.append((".".join(match.groups()), "renpy/vc_version.json", "static"))
    except (OSError, ValueError):
        pass
    versions = {item[0] for item in evidence}
    paths = tuple(item[1] for item in evidence)
    if len(versions) > 1:
        return EngineVersion(confidence="conflict", evidence=paths)
    if evidence:
        confidence = "static" if any(item[2] == "static" for item in evidence) else "reported"
        return EngineVersion(version=evidence[0][0], confidence=confidence, evidence=paths)
    return EngineVersion()
