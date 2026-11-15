import hashlib
import io
from importlib.resources import files
from pathlib import Path

from fontTools.ttLib import TTFont

from rat.domain.arabic import FontChoice, FontInfo
from rat.exporters.safe_io import checked_path
from rat.security.safe_paths import read_source_bytes

ARABIC_REQUIRED = frozenset(
    [0x060C, 0x061B, 0x061F]
    + list(range(0x0621, 0x063B))
    + list(range(0x0641, 0x0653))
    + list(range(0x0660, 0x066A))
)


class FontManager:
    @staticmethod
    def builtin_path() -> Path:
        return Path(str(files("rat") / "resources/fonts/amiri/Amiri-Regular.ttf"))

    def path(self, choice: FontChoice, project: Path | None = None) -> Path:
        if choice.path == "builtin:amiri":
            return self.builtin_path()
        path = Path(choice.path).expanduser()
        if not path.is_absolute():
            if project is None:
                raise ValueError("relative_font_requires_project")
            return checked_path(project, choice.path)
        return path

    def inspect(self, path: Path) -> FontInfo:
        if path.suffix.lower() not in {".ttf", ".otf"}:
            raise ValueError("unsupported_font_format")
        data = read_source_bytes(path, max_bytes=16 * 1024 * 1024)
        try:
            with TTFont(io.BytesIO(data), lazy=False) as font:
                cmap = font.getBestCmap() or {}
                points = tuple(
                    sorted(
                        cp
                        for cp, glyph in cmap.items()
                        if glyph != ".notdef" and font.getGlyphID(glyph) != 0
                    )
                )
                family = font["name"].getDebugName(1) if "name" in font else None
                restricted = bool(font["OS/2"].fsType & 0x0202) if "OS/2" in font else True
                shaping = "GSUB" in font and "GPOS" in font
        except Exception as error:
            raise ValueError("invalid_font_file") from error
        return FontInfo(
            path=str(path),
            sha256=hashlib.sha256(data).hexdigest(),
            family=family or path.stem,
            codepoints=points,
            missing_arabic=tuple(sorted(ARABIC_REQUIRED - set(points))),
            shaping_tables=shaping,
            embedding_restricted=restricted,
        )

    def license_bytes(self, choice: FontChoice, project: Path) -> bytes:
        if choice.path == "builtin:amiri":
            return self.builtin_path().with_name("OFL.txt").read_bytes()
        if not choice.redistribution_allowed or not choice.license_path:
            raise ValueError("font_redistribution_permission_required")
        license_path = Path(choice.license_path).expanduser()
        if not license_path.is_absolute():
            license_path = checked_path(project, choice.license_path)
        data = read_source_bytes(license_path, max_bytes=65536)
        if not data.strip():
            raise ValueError("font_license_empty")
        data.decode("utf-8-sig")
        return data

    @staticmethod
    def ranges(points):
        result = []
        for point in sorted(points):
            if result and point == result[-1][1] + 1:
                result[-1] = (result[-1][0], point)
            else:
                result.append((point, point))
        return result

    def assignments(self, fonts):
        arabic = next(
            (font for font in fonts if not font.missing_arabic and font.shaping_tables), None
        )
        if arabic is None:
            raise ValueError("no_font_covers_basic_arabic")
        used, assignments = set(), []
        # One complete Arabic face keeps connected words in the same shaping font.
        arabic_points = {
            cp
            for cp in arabic.codepoints
            if 0x0600 <= cp <= 0x06FF or 0x0750 <= cp <= 0x077F or 0x08A0 <= cp <= 0x08FF
        }
        for font, points in [(arabic, arabic_points), *[(f, set(f.codepoints)) for f in fonts]]:
            available = points - used
            assignments.extend((font.sha256, start, end) for start, end in self.ranges(available))
            used.update(available)
        return tuple(assignments)
