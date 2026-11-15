"""Run a copied EXE without development paths; never touch a user game."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4


def verify(executable: Path, output: Path, sdk: Path | None = None) -> dict:
    output = output.resolve()
    folder = output / ("smoke-" + uuid4().hex[:8])
    folder.mkdir(parents=True)
    copied = folder / "RAT.exe"
    shutil.copy2(executable, copied)
    working = folder / "empty-cwd"
    working.mkdir()
    environment = os.environ.copy()
    for name in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "RAT_RENPY_SDK"):
        environment.pop(name, None)
    environment.update(
        PATH=str(Path(environment.get("SYSTEMROOT", r"C:\Windows")) / "System32"),
        QT_QPA_PLATFORM="offscreen",
        PYINSTALLER_RESET_ENVIRONMENT="1",
    )
    if sdk:
        environment["RAT_RENPY_SDK"] = str(sdk.resolve())
    diagnostic = folder / "diagnostic"
    process = subprocess.run(
        [str(copied), "--self-test", str(diagnostic)],
        cwd=working,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=240,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    result = json.loads((diagnostic / "result.json").read_text(encoding="utf-8"))
    report = {
        "exit_code": process.returncode,
        "sha256": hashlib.sha256(copied.read_bytes()).hexdigest(),
        "size_bytes": copied.stat().st_size,
        "result": result,
        "clean_windows_vm": False,
    }
    (output / "windows-smoke.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if process.returncode or result.get("status") != "passed" or not result.get("frozen"):
        raise RuntimeError("Frozen smoke failed; inspect windows-smoke.json")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, default=Path("dist/RAT.exe"))
    parser.add_argument("--output", type=Path, default=Path(".local/phase7"))
    parser.add_argument("--sdk", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.exe, args.output, args.sdk), indent=2))
