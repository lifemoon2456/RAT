import json

import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from pydantic import ValidationError

from rat.arabic.fonts import ARABIC_REQUIRED, FontManager
from rat.arabic.preview import PREVIEW_SAMPLE, preview_html
from rat.arabic.rtl_profiles import compatibility, resolve_profile
from rat.arabic.style_generator import StyleGenerator
from rat.discovery.version_detector import detect_version
from rat.domain.arabic import RuntimeOptions, RuntimeSizes
from rat.domain.discovery import EngineVersion


def latin_font(path, *, restricted=False):
    # Original synthetic outline fixture: no third-party font is modified.
    builder = FontBuilder(1000, isTTF=True)
    glyphs = [".notdef"] + [f"u{point:04x}" for point in range(32, 127)]
    builder.setupGlyphOrder(glyphs)
    builder.setupCharacterMap({point: f"u{point:04x}" for point in range(32, 127)})
    pen = TTGlyphPen(None)
    pen.moveTo((100, 0))
    pen.lineTo((500, 0))
    pen.lineTo((500, 700))
    pen.lineTo((100, 700))
    pen.closePath()
    glyph = pen.glyph()
    builder.setupGlyf({name: glyph for name in glyphs})
    builder.setupHorizontalMetrics({name: (600, 0) for name in glyphs})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable(
        {
            "familyName": "RAT Test Latin",
            "styleName": "Regular",
            "uniqueFontIdentifier": "RAT-Test-1",
            "fullName": "RAT Test Latin",
            "psName": "RATTestLatin",
        }
    )
    builder.setupOS2(
        sTypoAscender=800,
        sTypoDescender=-200,
        usWinAscent=800,
        usWinDescent=200,
        fsType=2 if restricted else 0,
    )
    builder.setupPost()
    builder.save(path)
    return path


@pytest.mark.parametrize(
    "version,supported,mode,order",
    [
        (None, False, "unknown", False),
        ("7.8.7", False, "legacy_unverified", False),
        ("8.1.3", False, "legacy_unverified", False),
        ("8.2.0", True, "native", False),
        ("8.3.6", True, "native", False),
        ("8.3.7", False, "known_regression", False),
        ("8.4.0", True, "native", True),
        ("8.5.3", True, "native", True),
        ("9.0.0", False, "unsupported", False),
        ("garbage", False, "unknown", False),
    ],
)
def test_compatibility_profiles(version, supported, mode, order):
    profile = compatibility(version)
    assert (profile.supported, profile.mode, profile.reading_order) == (supported, mode, order)


def test_manual_version_requires_confirmation_and_never_overrides_known_conflict():
    options = RuntimeOptions(target_version="8.5.3")
    with pytest.raises(ValueError, match="confirm"):
        resolve_profile(EngineVersion(), options)
    confirmed = options.model_copy(update={"target_version_confirmed": True})
    assert resolve_profile(EngineVersion(), confirmed).version == "8.5.3"
    with pytest.raises(ValueError, match="conflicts"):
        resolve_profile(EngineVersion(version="8.2.0", confidence="static"), confirmed)
    with pytest.raises(ValueError, match="conflict"):
        resolve_profile(EngineVersion(confidence="conflict"), confirmed)


def test_version_json_is_data_only_and_conflicting_log_is_not_ignored(tmp_path):
    (tmp_path / "renpy").mkdir()
    (tmp_path / "renpy/vc_version.json").write_text(json.dumps({"version": "8.5.3.26051504"}))
    assert detect_version(tmp_path).version == "8.5.3"
    (tmp_path / "renpy/__init__.py").write_text('raise RuntimeError("must never run")')
    assert detect_version(tmp_path).confidence == "static"
    (tmp_path / "log.txt").write_text("Ren'Py 7.8.7.1234\n")
    assert detect_version(tmp_path).confidence == "conflict"


def test_builtin_font_has_arabic_cmap_shaping_and_license():
    manager = FontManager()
    info = manager.inspect(manager.builtin_path())
    assert not info.missing_arabic and info.shaping_tables and not info.embedding_restricted
    assert ARABIC_REQUIRED <= set(info.codepoints)
    assert "SIL OPEN FONT LICENSE" in manager.builtin_path().with_name("OFL.txt").read_text()


def test_fallback_uses_one_complete_arabic_face_and_latin_primary(tmp_path):
    manager = FontManager()
    latin = manager.inspect(latin_font(tmp_path / "latin.ttf"))
    arabic = manager.inspect(manager.builtin_path())
    assert latin.missing_arabic
    assignments = manager.assignments([latin, arabic])
    assert (
        next(sha for sha, first, last in assignments if first <= ord("A") <= last) == latin.sha256
    )
    for point in ARABIC_REQUIRED:
        assert (
            next(sha for sha, first, last in assignments if first <= point <= last) == arabic.sha256
        )
    with pytest.raises(ValueError, match="no_font"):
        manager.assignments([latin])


def test_corrupt_font_and_restricted_embedding_are_detected(tmp_path):
    corrupt = tmp_path / "corrupt.ttf"
    corrupt.write_bytes(b"invalid")
    with pytest.raises(ValueError, match="invalid_font"):
        FontManager().inspect(corrupt)
    restricted = FontManager().inspect(latin_font(tmp_path / "restricted.ttf", restricted=True))
    assert restricted.embedding_restricted


@pytest.mark.parametrize("size", [0, 9, 129, 100000])
def test_sizes_are_bounded(size):
    with pytest.raises(ValidationError):
        RuntimeSizes(dialogue=size)


def test_style_generation_is_version_aware_and_never_preprocesses_text():
    manager = FontManager()
    font = manager.inspect(manager.builtin_path())
    for version, uses_order in (("8.2.0", False), ("8.5.3", True)):
        code = StyleGenerator().generate(
            RuntimeOptions(),
            compatibility(version),
            [font],
            {font.sha256: "tl/arabic/fonts/test.ttf"},
        )
        assert f"'reading_order': {uses_order}" in code
        assert 'target.shaper = "harfbuzz"' in code and "arabic_reshaper" not in code
        assert "get_display" not in code and "[::-1]" not in code
        assert "def set_enabled(value)" in code and "rat_runtime.disabled" in code


def test_preview_preserves_mixed_text_and_tags_without_evaluating_placeholders(tmp_path):
    text = PREVIEW_SAMPLE + " [[literal] {{tag}"
    before = text.encode("utf-8")
    rendered = preview_html(text)
    assert "Build 42 / 123" in rendered and "٣٤٥" in rendered and "Alex" in rendered
    assert "<b>المستوى 12</b>" in rendered and "[literal]" in rendered
    assert text.encode("utf-8") == before
    dangerous = "[__import__('os').system('must_not_run')]"
    assert "__import__" in preview_html(dangerous)
    assert "<script>" not in preview_html("<script>alert(1)</script>")
