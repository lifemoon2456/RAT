from pathlib import Path

from rat.security.safe_paths import is_link, safe_relative


def relative_export_path(value: str) -> str:
    value = safe_relative(value)
    reserved = {"CON", "PRN", "AUX", "NUL"} | {
        f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
    }
    for part in Path(value).parts:
        if (
            any(ord(char) < 32 for char in part)
            or part.endswith((" ", "."))
            or part.split(".")[0].upper() in reserved
        ):
            raise ValueError("unsafe_export_path")
    return value


def checked_path(root: Path, relative: str) -> Path:
    relative = relative_export_path(relative)
    root = root.absolute()
    path = root / relative
    for candidate in [root, *reversed(path.parents), path]:
        if candidate == root or candidate.is_relative_to(root):
            if candidate.exists() and is_link(candidate):
                raise ValueError("linked_export_path")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("unsafe_export_path")
    return path


def project_directory(project: Path, name: str, *, game_dir: str | None = None) -> Path:
    project = project.resolve()
    path = checked_path(project, name)
    if game_dir:
        game = Path(game_dir).resolve()
        if path.is_relative_to(game) or game.is_relative_to(path) or project.is_relative_to(game):
            raise ValueError("export_overlaps_game")
    path.mkdir(exist_ok=True)
    return path
