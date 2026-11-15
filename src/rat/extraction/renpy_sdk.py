import os
import re
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

from rat.domain.discovery import GameInventory
from rat.extraction.rpy_parser import logical_lines, say_statement, tokens
from rat.security.safe_paths import ScanError, is_link, read_source


def sdk_command(sdk_dir: Path) -> list[str]:
    sdk_dir = sdk_dir.expanduser().absolute()
    if not sdk_dir.is_dir() or is_link(sdk_dir):
        raise ScanError("invalid_sdk_directory")
    root = sdk_dir.resolve()
    python = root / "lib" / "py3-windows-x86_64" / "python.exe"
    entry = root / "renpy.py"
    if os.name != "nt":
        raise ScanError("sdk_platform_not_tested")
    if not python.is_file() or not entry.is_file() or is_link(python) or is_link(entry):
        raise ScanError("invalid_sdk_layout")
    return [str(python), "-B", str(entry)]


def run_sdk(arguments: list[str], cwd: Path, *, timeout: int = 120) -> str:
    environment = os.environ.copy()
    for name in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV"):
        environment.pop(name, None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["RENPY_DISABLE_JOYSTICK"] = "1"
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with tempfile.TemporaryFile(dir=cwd) as output:
        try:
            result = subprocess.run(
                arguments,
                cwd=cwd,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                shell=False,
                creationflags=creationflags,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise ScanError("sdk_timeout") from error
        except OSError as error:
            raise ScanError("sdk_start_failed") from error
        output.seek(0)
        data = output.read(1024 * 1024 + 1)
    if result.returncode != 0:
        raise ScanError("sdk_command_failed")
    if len(data) > 1024 * 1024:
        raise ScanError("sdk_output_limit")
    return data.decode("utf-8", errors="replace")


def validate_declarative_source(text: str) -> None:
    """Reject executable expressions, init, Python and unknown statements before SDK use."""
    has_label = False
    for statement in logical_lines(text):
        if statement.comment or not statement.code:
            continue
        code = statement.code
        if re.fullmatch(r"label\s+[A-Za-z_]\w*\s*:", code):
            has_label = True
            continue
        if statement.indent == 0:
            raise ScanError("sdk_unsafe_or_unsupported_source")
        if code in {"menu:", "pass", "return"}:
            continue
        values = tokens(code)
        if len(values) == 2 and values[0].kind == "string" and values[1].value == ":":
            continue
        if say_statement(code, statement.line) is not None:
            continue
        raise ScanError("sdk_unsafe_or_unsupported_source")
    if not has_label:
        raise ScanError("sdk_no_declarative_labels")


def generate_templates(
    inventory: GameInventory,
    sdk_dir: Path,
    project_dir: Path,
    *,
    packed_manifest: Path | None = None,
) -> tuple[Path, str]:
    root = Path(inventory.game_dir)
    project_dir = project_dir.resolve()
    if packed_manifest is not None:
        from rat.extraction.packed_workspace import validate_packed_import

        recovered = validate_packed_import(project_dir, root, packed_manifest)
        if recovered.status != "ready" or any(item.partial for item in recovered.files):
            raise ScanError("sdk_generation_on_partial_recovery_not_supported")
    if project_dir.is_relative_to(root) or (
        root.is_relative_to(project_dir) and packed_manifest is None
    ):
        raise ScanError("workspace_overlaps_game")
    command = sdk_command(sdk_dir)
    source_names = {item.relpath.casefold() for item in inventory.files if item.language is None}
    for item in inventory.files:
        if item.language is not None:
            continue
        if item.extension in {".rpa", ".py", ".pyc", ".pyo", ".pyd"} or (
            item.extension in {".rpyc", ".rpymc"}
            and item.relpath[:-1].casefold() not in source_names
        ):
            raise ScanError("sdk_requires_complete_declarative_source")
    sources: list[tuple[str, str]] = []
    for item in inventory.files:
        if item.language is None and item.extension in {".rpy", ".rpym"}:
            if item.extension == ".rpym":
                raise ScanError("sdk_unsafe_or_unsupported_source")
            text = read_source(root / item.relpath)
            validate_declarative_source(text)
            sources.append((item.relpath, text))
    if not sources:
        raise ScanError("sdk_no_source_files")
    stage = project_dir / "staging" / f"sdk-{uuid4().hex}"
    stage.mkdir(parents=True, exist_ok=False)
    # Only validated text is copied; no game Python, bytecode, archives, media or caches.
    for relative, text in sources:
        destination = stage / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Preserve CRLF: write_text would expand an existing CRLF to CRCRLF on Windows.
        destination.write_bytes(text.encode("utf-8"))
    output = run_sdk([*command, "--version"], stage)
    match = re.search(r"Ren'Py (8\.\d+\.\d+)(?:\.\d+)?", output)
    if not match:
        raise ScanError("unsupported_sdk_version")
    version = match[1]
    if inventory.engine.confidence == "conflict":
        raise ScanError("conflicting_engine_evidence")
    known = inventory.engine.version
    if known and known.split(".")[:2] != version.split(".")[:2]:
        raise ScanError("sdk_engine_version_mismatch")
    run_sdk(
        [
            *command,
            "--savedir",
            str(stage / "saves"),
            str(stage),
            "translate",
            "arabic",
            "--empty",
            "--no-todo",
        ],
        stage,
    )
    templates = stage / "game" / "tl" / "arabic"
    if not templates.is_dir() or not any(templates.rglob("*.rpy")):
        raise ScanError("sdk_no_templates_generated")
    return stage, version
