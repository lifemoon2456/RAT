import pytest

from rat.domain.models import SourceUnit
from rat.domain.review import EditorUnit
from rat.translation.quality import QAEngine


def unit(text):
    return SourceUnit(
        unit_id="qa",
        project_id="a" * 32,
        source_relpath="game/script.rpy",
        source_line=1,
        kind="narration",
        source_text=text,
    )


@pytest.mark.parametrize(
    "original,target,code",
    [
        ("Hello [name]", "مرحبًا", "missing_placeholders"),
        ("[name]", "[other]", "changed_placeholders"),
        ("{b}Hi{/b}", "مرحبًا", "missing_renpy_tags"),
        ("{b}Hi{/b}", "{i}مرحبًا{/i}", "changed_renpy_tags"),
        ("{b}{i}Hi{/i}{/b}", "{b}{i}مرحبًا{/b}{/i}", "broken_tag_nesting"),
        ("Hello", "", "empty_translation"),
        ("Hello", None, "invalid_output"),
        ("Hello", "bad\x00output", "invalid_output"),
        ("Hello", "bad\ud800output", "invalid_output"),
        ("[first] [second]", "[second] [first]", "invalid_output"),
        ("[[name] {{b}", "[name] {b}", "broken_tag_nesting"),
    ],
)
def test_qa_blocks_broken_structure(original, target, code):
    result = QAEngine().check(unit(original), target)
    assert not result.valid
    assert code in {issue.code for issue in result.issues}


def test_qa_accepts_preserved_syntax_and_labels_layout_as_estimate():
    result = QAEngine().check(unit("Hi [name] {b}yes{/b}"), "مرحبًا [name] {b}نعم{/b}")
    assert result.valid and result.overflow_risk == "low"
    long = QAEngine().check(unit("Hello"), "م" * 1100)
    assert long.valid and long.overflow_risk == "high"
    assert "extremely_long_translation" in {issue.code for issue in long.issues}


def test_untranslated_warning_does_not_claim_invalid_names():
    result = QAEngine().check(unit("Eileen"), "Eileen")
    assert result.valid
    assert result.issues[0].code == "suspicious_untranslated"


def test_invalid_source_control_characters_cannot_be_approved():
    result = QAEngine().check(unit("bad\x00source"), "ترجمة")
    assert not result.valid and result.issues[0].code == "invalid_source"


def test_duplicate_translations_are_review_warnings_for_different_sources():
    one, two = unit("Hello"), unit("Goodbye")
    two = SourceUnit.model_validate(
        {**two.model_dump(exclude={"source_sha256"}), "unit_id": "other", "source_line": 2}
    )
    from rat.domain.models import TranslationUnit

    records = [
        EditorUnit(
            source=TranslationUnit.model_validate(item.model_dump()), translation_text="نفس النص"
        )
        for item in (one, two)
    ]
    results = QAEngine().audit(records)
    assert all(
        result.valid and "duplicate_translation" in {issue.code for issue in result.issues}
        for result in results.values()
    )
