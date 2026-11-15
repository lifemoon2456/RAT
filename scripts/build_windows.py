"""Build the single-file desktop EXE without changing PowerShell policies."""

import os
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path

from verify_windows import verify


def main() -> int:
    if os.name != "nt":
        raise SystemExit("Build the Windows EXE on Windows.")
    root = Path(__file__).resolve().parents[1]
    required = ("PyInstaller", "PySide6", "openai", "google.genai", "deep_translator")
    for module in required:
        if find_spec(module) is None:
            raise SystemExit(
                f"Missing build dependency: {module}; install .[dev,llm,windows-build]"
            )
    commands = [
        ["-m", "pytest", "-c", "pyproject.toml", "tests"],
        ["-m", "ruff", "check", "."],
        ["-m", "ruff", "format", "--check", "."],
        ["scripts/collect_licenses.py", "build/licenses/THIRD_PARTY_NOTICES.txt"],
        [
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--distpath",
            "dist",
            "--workpath",
            "build/pyinstaller",
            "scripts/RAT.spec",
        ],
    ]
    for command in commands:
        subprocess.run([sys.executable, *command], cwd=root, check=True)
    executable = root / "dist" / "RAT.exe"
    if not executable.is_file():
        raise RuntimeError("Build did not produce RAT.exe.")
    sdk = os.environ.get("RAT_RENPY_SDK")
    verify(executable, root / ".local/phase7", Path(sdk) if sdk else None)
    print(executable)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
