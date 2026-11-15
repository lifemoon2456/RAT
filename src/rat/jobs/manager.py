import os
from pathlib import Path
from threading import Event

from rat.security.safe_paths import is_link


class JobControl:
    def __init__(self):
        self.pause_requested = Event()
        self.stop_requested = Event()

    def pause(self):
        self.pause_requested.set()

    def stop(self):
        self.stop_requested.set()

    @property
    def requested_status(self):
        return (
            "cancelled"
            if self.stop_requested.is_set()
            else "paused"
            if self.pause_requested.is_set()
            else None
        )


class ProjectJobLock:
    """OS-held lock, automatically released on process death; no stale PID guessing."""

    def __init__(self, project: Path):
        self.path = project / ".translation.lock"
        self.file = None

    def __enter__(self):
        if self.path.exists() and (is_link(self.path) or self.path.stat().st_nlink > 1):
            raise ValueError("unsafe_translation_lock")
        self.file = self.path.open("a+b")
        self.file.seek(0, 2)
        if self.file.tell() == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise ValueError("translation_already_running") from None
        return self

    def __exit__(self, *_args):
        self.file.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
        self.file.close()
