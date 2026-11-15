import pytest

from rat.extraction.renpy_sdk import validate_declarative_source
from rat.extraction.rpy_parser import decode_literal, parse_rpy
from rat.extraction.translation_parser import parse_template
from rat.security.safe_paths import ScanError


def test_context_parser_skips_python_variables_resources_and_dynamic_screen_text():
    source = """# Ren'Py file with an author's comment.
define e = Character("Eileen")
image background = "assets/background.png"
init python:
    message = "never translate this Python variable"
    evil = "import os"
label start:
    e happy "Hello [name] {b}world{/b}"
    $ filename = "sound.ogg"
    python:
        code = "not dialogue"
    menu:
        "Continue":
            "Narration."
    return
screen test():
    text _("UI  text")
    text "Dynamic" + player_name
    text variable
"""
    units, issues = parse_rpy(source)
    assert [unit.text for unit in units] == [
        "Hello [name] {b}world{/b}",
        "Continue",
        "Narration.",
        "UI  text",
    ]
    assert [unit.kind.value for unit in units] == [
        "dialogue",
        "menu_choice",
        "narration",
        "screen_text",
    ]
    assert units[0].speaker == "e" and units[0].label == "start"
    assert {issue.code for issue in issues} >= {"python_skipped", "dynamic_screen_text_skipped"}


def test_multiline_and_escapes_preserve_literal_and_renpy_semantics():
    source = 'label start:\n    "Hello\n        world. \\nNext: \\"yes\\" [names[0]]"\n'
    units, _ = parse_rpy(source)
    assert units[0].line == 2
    assert units[0].text == 'Hello world. \nNext: "yes" [names[0]]'
    assert "\n        world" in units[0].literal
    assert decode_literal(r'"escaped \[name] \{b} \% \u0627"') == "escaped [[name] {{b} %% ا"
    assert decode_literal('r"two  spaces"') == "two  spaces"


def test_template_original_is_comment_not_translated_text_and_ids_are_literal():
    template = """# game/script.rpy:42
translate arabic actual_engine_identifier:
    # e "Original [name]."
    e "ترجمة"

translate arabic strings:
    # game/script.rpy:50
    old "Start {#menu}"
    new "بدء"
"""
    units, issues = parse_template(template, "game/tl/arabic/script.rpy")
    assert not issues
    assert units[0].identifier == "actual_engine_identifier"
    assert units[0].original.text == "Original [name]."
    assert units[0].translation == "ترجمة"
    assert units[0].reference_line == 42
    assert units[1].identifier is None and units[1].is_string
    assert units[1].original.literal == '"Start {#menu}"'


def test_unsafe_template_references_and_python_blocks_are_not_executed():
    source = """# ../evil.rpy:1
translate arabic bad:
    # e "Source"
    $ __import__("pathlib").Path("never-created").write_text("bad")
    e "Target"
translate arabic strings:
    old "Orphan"
"""
    units, issues = parse_template(source, "game/tl/arabic/a.rpy")
    assert units == []
    assert {issue.code for issue in issues} >= {
        "unsafe_reference_path",
        "unsupported_translation_block",
        "missing_new",
    }


def test_split_translation_and_missing_comments_never_become_source():
    template = """translate arabic original_id:
    # "Source"
    "First"
    "Second"
translate arabic missing_comment:
    "Cannot be assumed to be original"
"""
    units, issues = parse_template(template, "game/tl/arabic/a.rpy")
    assert len(units) == 1
    assert units[0].original.text == "Source" and units[0].translation is None
    assert any(issue.code == "missing_original_comment" for issue in issues)


@pytest.mark.parametrize(
    "statement",
    [
        'init python:\n    raise RuntimeError("bad")',
        '$ print("bad")',
        'define e = Character("e")',
        "label start(x=evil()):\n    return",
        "label start:\n    call expression evil()",
        'screen x():\n    text "UI"',
    ],
)
def test_sdk_gate_rejects_executable_or_unsupported_projects(statement):
    with pytest.raises(ScanError):
        validate_declarative_source(statement)


def test_malformed_quote_does_not_produce_partial_untrusted_results():
    with pytest.raises(ScanError):
        parse_template('translate arabic strings:\n    old "unterminated', "game/tl/arabic/a.rpy")


def test_logical_lines_bound_long_unterminated_literals():
    with pytest.raises(ScanError, match="logical_line_limit"):
        parse_rpy('label start:\n    "' + ("unclosed\n" * 1000))


def test_explicit_identifiers_and_nointeract_are_preserved_without_relaxing_parser():
    for suffix in ("id start_real nointeract", "nointeract id start_real"):
        units, issues = parse_rpy(f'label start:\n    "Text" {suffix}\n')
        assert len(units) == 1 and units[0].renpy_identifier == "start_real" and not issues
    units, issues = parse_rpy('label start:\n    "Text" nointeract nointeract\n')
    assert not units and issues


def test_string_templates_use_python_literal_rules_without_executing_expressions():
    text = r"""translate arabic strings:
    old "  Keep   spaces [name] {b}bold{/b}"
    new "  مسافات   [name] {b}نص{/b}\t\\"
"""
    entries, issues = parse_template(text, "game/tl/arabic/strings.rpy")
    assert not issues and len(entries) == 1
    assert entries[0].original.text == "  Keep   spaces [name] {b}bold{/b}"
    assert entries[0].translation == "  مسافات   [name] {b}نص{/b}\t\\"
    bad, issues = parse_template(
        'translate arabic strings:\n    old "Hi"\n    new __import__("os").system("bad")',
        "game/tl/arabic/strings.rpy",
    )
    assert not bad and any(issue.code == "unsupported_string_entry" for issue in issues)
