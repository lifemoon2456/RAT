# Phase 7A — Release audit (2026-11-14)

Baseline before source edits: `python -m pytest -q`: **378 passed, 6 skipped,
0 failed in 73.19s**. Skips require a Ren'Py SDK. `ruff check .`: passed.
The available SDK is `D:/B/777/LC/renpy-8.5.3-sdk`; a second baseline with
that SDK is recorded in `.local/phase7-baseline.xml`. Use explicit
`-c pyproject.toml tests` with additional pytest arguments in this workspace.
There is no Git metadata; `.local/phase7-initial-files.json` records initial hashes.

| Area | Existing implementation / release action |
|---|---|
| Entry points | CLI `rat.cli.commands:main`, GUI `rat.app:main`, frozen `scripts/rat_desktop.py`; retain worker dispatch |
| Dependencies | Python >=3.11; installed Windows build uses 3.13; require all `llm` extras for the published bundle |
| Assets | Amiri/OFL and authored demo via importlib.resources; notices generated at build time |
| Hidden imports | SQLite dialect, Windows vault, fontTools tables already explicit; test SDK clients and worker in frozen smoke |
| Resource paths | Bundled resources separate from writable user files; no cwd resource lookup |
| Runtime paths | platformdirs LocalAppData settings/logs; Documents projects or explicit user workspace |
| Settings | Safe typed YAML without secret fields; desktop loads default config; improve workspace persistence |
| Secrets | Windows Credential Manager allowlist; no plaintext fallback; retain existing implementation |
| Logging | Rotating allowlisted lifecycle/API logs; add JSON structure and safe crash event |
| Database | SQLite v4 per project, transactions, explicit backup before migration; no schema redesign needed |
| Packaging | Existing onefile EXE/spec and lock snapshots; add build preflight, isolated smoke and release artifacts |
| Installer | Missing; add per-user Inno Setup, no elevation, no deletion of projects/settings on uninstall |
| Portable | Existing standalone EXE is appropriate; ZIP with notices/instructions, user data remains outside EXE |
| Backup/recovery | SQLite backup exists; missing restore; preserve checkpoints and approved results in new restored directories |
| Patch install | Missing; add explicit install on a newly created copy only, verified backup before patching |
| Diagnostics | Add allowlisted versions/counts only, no raw logs/settings/paths/headers/game text |
| Release | Stale START_HERE/phase labels, no About version; designate beta and document acceptance gaps |

Risks: no clean Windows VM available; Inno compiler not found on PATH or standard
Program Files locations at audit time; no code signing identity; real provider
accounts not tested. Existing EXE is historical evidence, not this release's build.
Onefile uses the system temporary directory and may have delayed startup.
External SDK remains optional and is never bundled. Legacy Ren'Py support remains
limited to documented compatibility. Review third-party distribution obligations
and the owner's application license before public distribution.

References checked for packaging:
[PyInstaller runtime paths](https://pyinstaller.org/en/stable/runtime-information.html),
[hidden imports](https://pyinstaller.org/en/latest/when-things-go-wrong.html),
[Inno per-user privileges](https://jrsoftware.org/is6help/topic_setup_privilegesrequired.htm).

Follow-up: Phase 7 implementation, actual EXE/installer verification, remaining
acceptance gates and complete file inventory are recorded in
[phase7-verification.md](phase7-verification.md). The compiler absence found
during audit was resolved with a signed official workspace-local Inno download.
