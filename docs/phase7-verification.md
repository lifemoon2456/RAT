# Phase 7 verification — 0.7.0b1 Beta candidate

Verification date: 2026-11-15. Windows x64, Python 3.13.12, PyInstaller 6.22.3,
PySide6 6.12.0, local Ren'Py SDK 8.5.3. No Phase 8 work or public publishing.

## Baseline and regression accounting

Before source changes, pytest reported **378 passed, 6 skipped** in 73.19s;
the skips required the optional SDK. Ruff and dependency checks passed.
With the local SDK, the first baseline run stalled around a UI test and was
stopped. That UI module passed alone, and a full verbose baseline rerun passed
**384 tests** in 138.40s. This transient baseline hang is not hidden or attributed
to Phase 7 changes. Evidence: `.local/phase7-baseline.log` and its JUnit XML.

During 7D, two new tests initially expected a destination-exists error where
the stronger source-overlap guard fired first. The assertions were corrected
and rerun. No failing tests were disabled. No remaining test failure is known.

## Stage verification

| Stage | Actual result |
| --- | --- |
| 7A | Audit recorded in [phase7-audit.md](phase7-audit.md); baseline above |
| 7B | Entrypoint tests: 7 passed; initial actual Windows EXE and isolated smoke passed |
| 7C | Settings, secrets, runtime paths and UI: 30 passed |
| 7D | Backup/restore and integration checks with SDK: 27 passed |
| 7E | E2E plus recovery: 15 passed; final standalone E2E: **4 passed in 12.42s** |
| 7F | Version/About/runtime/CLI: 12 passed |
| Final suite | **404 passed in 156.57s**, no skips, with local SDK |
| Final lint | `ruff check .` passed; final `ruff format --check .`: 292 files already formatted |

The E2E fixtures cover import, engine detection, official template generation,
extraction, protected variables/tags, mock translation, validation, approval,
export, SDK compile/lint, pause/resume, reopen, preservation of approvals,
backup/restore and unchanged original file hashes. Failure cases include lost
placeholders, interrupted checkpoints, stale exports, tampered backups,
overlapping paths, interrupted copy installation and compiled translation rollback.
Mock results remain marked simulated. No live translation request is claimed.

Final suite/build log: `.local/phase7-final-build.log`.
Standalone E2E: `.local/phase7-e2e-final.log` and `.local/phase7-e2e-final.xml`.

## Actual Windows artifacts

The final EXE was built with PyInstaller and passed the copied-executable smoke
with development Python environment variables removed and PATH reduced to
Windows System32. `QT_QPA_PLATFORM=offscreen` was used: a Qt window was created,
but this is not a manual visual review. The result reports version `0.7.0b1`,
`frozen=true`, exit code 0, official SDK templates (317 extracted entries),
mock/protection/review/export, backup/restore, copy installation/rollback,
diagnostics, bundled font/runtime/licenses, packed/RPYC checks, and loaded
WinVault backend. SDK clients were initialized without live API calls.

EXE SHA256: `e61fcd8e1aa279e775d6810624a4bf86b1683c39affd343db5c0424b35204589`;
size: 70,807,827 bytes. Evidence: `.local/phase7/windows-smoke.json`.

The PowerShell redirected build command returned a shell error status because
PyInstaller INFO output on stderr became `NativeCommandError`; the Python
builder reached its final successful output, and the independent frozen result
records exit 0. No Python traceback or failed build stage appears in that log.
PyInstaller optional/platform import warnings remain in
`build/pyinstaller/RAT/warn-RAT.txt`; supported frozen paths passed smoke.

Inno Setup 7.1.1 compiled the final Beta installer successfully. The official
compiler download had a valid Authenticode signature. Release packaging exited
0 and produced EXE, installer, portable ZIP, manifest and SHA256 sums under
`dist/release-0.7.0b1/`. Evidence: `.local/phase7-release-package.log`.
The first installer launch under sandbox failed to expand the Windows
`localappdata` shell constant, before installation. The setup log was inspected
before repeating the scoped install/run/uninstall check outside sandbox.

The repeated **actual installer test passed with process exit 0**: installed
EXE ran the complete frozen smoke, installation files remained unchanged while
running, uninstall removed the executable, and external test projects survived.
Evidence: `.local/phase7/installer-smoke.json` and
`.local/phase7-installer-final.log`. No existing RAT installation was replaced;
the verifier refuses an existing uninstall registration.

| Deliverable | Bytes | SHA256 |
| --- | ---: | --- |
| `RAT-0.7.0b1-windows-x64.exe` | 70,807,827 | `e61fcd8e1aa279e775d6810624a4bf86b1683c39affd343db5c0424b35204589` |
| `RAT-0.7.0b1-windows-x64-setup.exe` | 72,151,159 | `40b53d4bd22238475f2393413a58f9aa3f51a8a1288628b81cd62062316aadc4` |
| `RAT-0.7.0b1-windows-x64-portable.zip` | 70,364,349 | `52dc8a8e6fe3e76d8c9baf8576da956b6cf41e1438eca1525760f247d9dfb559` |

## Delivery and remaining acceptance

Runtime settings/logs use user AppData; projects use the user workspace under
Documents (home fallback). The portable package still stores writable settings
in AppData. Windows Credential Manager remains the secret store; no plaintext
fallback was added. Diagnostics use an allowlist and omit raw logs, credentials,
headers, environment, paths, game text and names.

Copy installation is explicit and limited to source imports. Packed imports
remain export-only for this operation. A new destination is required; original
game files are never patched. The prepared journal supports interrupted patch
recovery. A failed initial copy before journal creation must be retried into
another fresh destination. Close the copied game before install/restore.

This is a **local Beta candidate for controlled testing**, not unconditional
public Beta acceptance or production readiness. Remaining gates:

- Clean Windows 10/11 VM without developer tools, including upgrade testing.
- Manual GUI/Arabic layout review and representative authorized game testing.
- Explicitly budgeted real-provider smoke tests; mocks do not prove API behavior.
- Owner-selected application distribution license and third-party obligations review.
- Unsigned binaries; no signing identity or publication destination supplied.

The existing architecture and database schema v4 were retained. No original
user game was used for mutation tests. See [release-checklist.md](release-checklist.md).

## Created files

- `RELEASE_NOTICE.txt`
- `docs/installation.md`
- `docs/phase7-audit.md`
- `docs/phase7-verification.md`
- `docs/release-checklist.md`
- `scripts/build_installer.ps1`
- `scripts/installer.iss`
- `scripts/prepare_release.py`
- `scripts/verify_installer.py`
- `scripts/verify_windows.py`
- `src/rat/diagnostics.py`
- `src/rat/exporters/installation.py`
- `src/rat/ui/about_dialog.py`
- `tests/e2e/test_release_pipeline.py`
- `tests/integration/test_release_recovery.py`
- `tests/ui/test_release_pages.py`
- `tests/unit/test_release_runtime.py`

## Modified files

- `README.md`
- `START_HERE.md`
- `docs/architecture.md`
- `docs/windows-exe.md`
- `pyproject.toml`
- `scripts/RAT.spec`
- `scripts/build_windows.ps1`
- `scripts/build_windows.py`
- `src/rat/__init__.py`
- `src/rat/app.py`
- `src/rat/cli/commands.py`
- `src/rat/desktop_checks.py`
- `src/rat/exporters/backup.py`
- `src/rat/logging_setup.py`
- `src/rat/ui/main_window.py`
- `src/rat/ui/pages/export.py`

Generated build products, collected third-party notices, test reports and
workspace-local compiler files are separate from this source-file inventory.
