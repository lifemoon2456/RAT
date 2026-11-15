"""Explicit per-user install/run/uninstall smoke in a fresh local test directory."""

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4


def run(arguments, *, environment=None, cwd=None):
    return subprocess.run(
        arguments,
        env=environment,
        cwd=cwd,
        check=True,
        timeout=300,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def verify(installer: Path, output: Path, sdk: Path | None):
    import winreg

    registration = (
        r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
        r"\{B933267D-2826-4A11-B581-B074E27452C8}_is1"
    )
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, registration, 0, winreg.KEY_READ | view):
                raise RuntimeError("Existing RAT installation: refusing to alter its registration")
        except FileNotFoundError:
            pass
    output = output.resolve()
    root = output / ("installer-" + uuid4().hex[:8])
    root.mkdir(parents=True)
    installed = root / "application"
    environment = os.environ.copy()
    for name in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "RAT_RENPY_SDK"):
        environment.pop(name, None)
    environment["PATH"] = str(Path(os.environ["SYSTEMROOT"]) / "System32")
    environment["QT_QPA_PLATFORM"] = "offscreen"
    environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    if sdk:
        environment["RAT_RENPY_SDK"] = str(sdk.resolve())
    record = {
        "installer_sha256": hashlib.sha256(installer.read_bytes()).hexdigest(),
        "installed": False,
        "runtime_passed": False,
        "uninstalled": False,
    }
    try:
        run(
            [
                str(installer.resolve()),
                "/VERYSILENT",
                "/SUPPRESSMSGBOXES",
                "/NORESTART",
                "/NOICONS",
                f"/DIR={installed}",
                f"/LOG={root / 'setup.log'}",
            ]
        )
        record["installed"] = (installed / "RAT.exe").is_file()
        before = {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in installed.iterdir()
            if p.is_file()
        }
        run(
            [str(installed / "RAT.exe"), "--self-test", str(root / "diagnostic")],
            environment=environment,
            cwd=root,
        )
        result = json.loads((root / "diagnostic/result.json").read_text(encoding="utf-8"))
        record["runtime_passed"] = result["status"] == "passed" and result["frozen"]
        record["result"] = result
        record["installation_files_unchanged"] = before == {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in installed.iterdir()
            if p.is_file()
        }
    finally:
        uninstaller = installed / "unins000.exe"
        if uninstaller.is_file():
            run(
                [
                    str(uninstaller),
                    "/VERYSILENT",
                    "/SUPPRESSMSGBOXES",
                    "/NORESTART",
                    f"/LOG={root / 'uninstall.log'}",
                ]
            )
            record["uninstalled"] = not (installed / "RAT.exe").exists()
        record["projects_preserved_after_uninstall"] = any(
            (root / "diagnostic/projects").glob("*/project.sqlite")
        )
        (output / "installer-smoke.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    if not all(
        record.get(key)
        for key in (
            "installed",
            "runtime_passed",
            "uninstalled",
            "installation_files_unchanged",
            "projects_preserved_after_uninstall",
        )
    ):
        raise RuntimeError("Installer smoke failed; inspect installer-smoke.json")
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("installer", type=Path)
    parser.add_argument("--output", type=Path, default=Path(".local/phase7"))
    parser.add_argument("--sdk", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.installer, args.output, args.sdk), indent=2))
