from pathlib import Path

from rat.security.safe_paths import ScanError, is_link


def detect_game(directory: Path) -> Path:
    directory = directory.expanduser().absolute()
    if not directory.is_dir() or is_link(directory):
        raise ScanError("invalid_game_directory")
    root = directory.resolve()
    game = root / "game"
    if not game.is_dir() or is_link(game):
        raise ScanError("missing_game_directory")
    return root
