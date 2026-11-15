import hashlib
import os
import time
from pathlib import Path

from rat.discovery.game_detector import detect_game
from rat.discovery.version_detector import detect_version
from rat.domain.discovery import DiscoveryIssue, GameInventory, InventoryFile
from rat.security.safe_paths import ScanError, is_link, read_source_bytes

EXTENSIONS = {".rpy", ".rpym", ".rpyc", ".rpymc", ".rpa", ".py", ".pyc", ".pyo", ".pyd"}


def inventory_game(directory: Path, *, max_entries: int = 50000) -> GameInventory:
    root = detect_game(directory)
    files: list[InventoryFile] = []
    languages: set[str] = set()
    issues: list[DiscoveryIssue] = []
    stack = [root / "game"]
    visited = 0
    source_bytes = 0
    started = time.monotonic()
    while stack:
        folder = stack.pop()
        if time.monotonic() - started > 60:
            raise ScanError("inventory_time_limit")
        try:
            with os.scandir(folder) as iterator:
                entries = sorted(iterator, key=lambda item: item.name.casefold())
        except OSError as error:
            raise ScanError("unreadable_game_directory") from error
        for entry in entries:
            visited += 1
            if visited > max_entries:
                raise ScanError("inventory_entry_limit")
            path = Path(entry.path)
            relative = path.relative_to(root).as_posix()
            if is_link(path):
                issues.append(DiscoveryIssue(code="link_skipped", path=relative))
                continue
            parts = path.relative_to(root).parts
            if entry.is_dir(follow_symlinks=False):
                if len(parts) == 3 and parts[:2] == ("game", "tl"):
                    languages.add(parts[2])
                # Ren'Py cache/saves contain no source templates to import.
                if entry.name not in {"cache", "saves"}:
                    stack.append(path)
                continue
            suffix = path.suffix.lower()
            if suffix not in EXTENSIONS:
                continue
            size = entry.stat(follow_symlinks=False).st_size
            digest = None
            if suffix in {".rpy", ".rpym"}:
                source_bytes += size
                if source_bytes > 64 * 1024 * 1024:
                    raise ScanError("inventory_source_size_limit")
                try:
                    data = read_source_bytes(path)
                    data.decode("utf-8-sig")
                    digest = hashlib.sha256(data).hexdigest()
                except (ScanError, UnicodeError) as error:
                    code = error.code if isinstance(error, ScanError) else "unsupported_encoding"
                    issues.append(DiscoveryIssue(code=code, path=relative))
            language = parts[2] if len(parts) >= 4 and parts[:2] == ("game", "tl") else None
            files.append(
                InventoryFile(
                    relpath=relative, extension=suffix, size=size, sha256=digest, language=language
                )
            )
    files.sort(key=lambda item: item.relpath)
    if any(item.extension == ".rpa" for item in files):
        issues.append(DiscoveryIssue(code="archives_not_extracted"))
    if any(item.extension in {".rpyc", ".rpymc"} for item in files):
        issues.append(DiscoveryIssue(code="compiled_scripts_not_decompiled"))
    if any(item.extension in {".py", ".pyc", ".pyo", ".pyd"} for item in files):
        issues.append(DiscoveryIssue(code="python_modules_not_loaded"))
    return GameInventory(
        game_dir=str(root),
        files=tuple(files),
        translation_languages=tuple(sorted(languages)),
        engine=detect_version(root),
        issues=tuple(issues),
    )
