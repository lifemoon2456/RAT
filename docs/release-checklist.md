# Release gate — 0.7.0b1 Beta candidate

- [x] Audit entry points, dependencies, assets, user paths, keyring and SQLite.
- [x] Baseline: 378 passed / 6 SDK skips; full SDK baseline retry: 384 passed.
- [x] Preserve architecture and database v4; use existing core services.
- [x] Independent EXE smoke, installer specification and portable packaging.
- [x] Restore, managed game copy rollback, privacy-preserving diagnostics.
- [x] Authored-fixture E2E: mock, checkpoints and immutable originals.
- [x] Final full pytest, ruff, E2E and frozen smoke results recorded.
- [x] Final installer built and install/uninstall exercised on isolated destination.
- [ ] Clean Windows 10/11 x64 VM without developer tools: launch/import/mock/export/upgrade.
- [ ] Manual GUI/Arabic layout review on that VM and representative authorized games.
- [ ] Real provider account smoke with a small explicit budget.
- [ ] Owner selects application distribution license and reviews third-party notices/source delivery.
- [ ] Optional signing identity and published download location supplied by owner.

Local verification is not clean-VM acceptance. No public publication or Phase 8 work is included.
Actual results and file inventory: [phase7-verification.md](phase7-verification.md).
