"""PyInstaller entry point; regular launches always open the desktop interface."""

import sys
from pathlib import Path

from rat.app import main

if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--google-worker":
        from rat.providers.google_worker import run

        raise SystemExit(run(Path(sys.argv[2]), Path(sys.argv[3])))
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        from rat.desktop_checks import run_desktop_check

        raise SystemExit(run_desktop_check(Path(sys.argv[2])))
    raise SystemExit(main())
