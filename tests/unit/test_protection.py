import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest

from rat.domain.protection import ProtectedText
from rat.protection import (
    MaskingEngine,
    ProtectionService,
    RestorationEngine,
    TagProtector,
    TextTokenizer,
    ValidationEngine,
)

CASES = json.loads(
    (Path(__file__).parents[1] / "fixtures/placeholders/cases.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("case", CASES["valid"], ids=lambda case: case["name"])
def test_mask_serialize_restore_exactly(case):
    result = MaskingEngine().mask(case["text"])
    assert result.valid, result.issues
    package = result.protected
    assert [token.text for token in package.tokens] == case["protected"]
    assert len({token.marker for token in package.tokens}) == len(package.tokens)
    for token in package.tokens:
        assert package.source_text[token.start : token.end] == token.text
        assert package.masked_text.count(token.marker) == 1
    loaded = ProtectedText.model_validate_json(package.model_dump_json())
    restored = RestorationEngine().restore(loaded, loaded.masked_text)
    assert restored.valid, restored.issues
    assert restored.text == case["text"]


@pytest.mark.parametrize("case", CASES["invalid"])
def test_malformed_sources_fail_closed_with_spans(case):
    result = MaskingEngine().mask(case["text"])
    assert not result.valid and result.protected is None
    assert case["code"] in {issue.code for issue in result.issues}
    for issue in result.issues:
        assert case["text"][issue.start : issue.end] == issue.affected_text
        assert issue.stage == "source"


def package(text="Hello [name] {b}bold {i}italic{/i}{/b}"):
    return MaskingEngine().mask(text).protected


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("missing", "missing_marker"),
        ("duplicated", "duplicate_marker"),
        ("unknown", "unknown_marker"),
        ("foreign", "unknown_marker"),
        ("reordered", "marker_order"),
        ("damaged", "malformed_marker"),
        ("new_variable", "protected_structure_changed"),
        ("new_tag", "protected_structure_changed"),
        ("new_unbalanced_tag", "unclosed_tag"),
        ("new_escape", "protected_structure_changed"),
        ("boundary", "protected_structure_changed"),
    ],
)
def test_damaged_translations_never_return_restored_text(mutation, code):
    protected = package()
    text = protected.masked_text
    first, second = [token.marker for token in protected.tokens[:2]]
    if mutation == "missing":
        text = text.replace(first, "")
    elif mutation == "duplicated":
        text += first
    elif mutation == "unknown":
        text += "⟦PH_unknown_0001⟧"
    elif mutation == "foreign":
        text += package("[other]").tokens[0].marker
    elif mutation == "reordered":
        text = text.replace(first, "TEMP").replace(second, first).replace("TEMP", second)
    elif mutation == "damaged":
        text = text.replace(first, first[:-1])
    elif mutation == "new_variable":
        text += " [hacked]"
    elif mutation == "new_tag":
        text = "{color=#fff}" + text + "{/color}"
    elif mutation == "new_unbalanced_tag":
        text += "{b}"
    elif mutation == "new_escape":
        text += "{{"
    elif mutation == "boundary":
        text = text.replace(first, "[" + first)
    result = RestorationEngine().restore(protected, text)
    assert not result.valid and result.text is None
    assert code in {issue.code for issue in result.issues}
    assert all(issue.stage == "translation" for issue in result.issues)


def test_temporary_ids_are_unique_between_units_and_repeated_occurrences():
    a, b = package("[name] [name]"), package("[name] [name]")
    assert {token.marker for token in a.tokens}.isdisjoint(token.marker for token in b.tokens)
    assert len({token.marker for token in a.tokens}) == 2


def test_arabic_translation_restores_literal_syntax_without_source_change():
    original = "Hello [name]! {b}Welcome{/b}."
    protected = package(original)
    masked_translation = protected.masked_text.replace("Hello", "مرحبًا").replace("Welcome", "أهلًا")
    result = RestorationEngine().restore(protected, masked_translation)
    assert result.valid
    assert result.text == "مرحبًا [name]! {b}أهلًا{/b}."
    assert protected.source_text == original


@pytest.mark.parametrize(
    "mutation",
    ["source", "hash", "offset", "marker", "text", "masked", "namespace", "missing_token"],
)
def test_map_tampering_is_rejected_after_json_roundtrip(mutation):
    protected = package()
    data = protected.model_dump()
    if mutation == "source":
        data["source_text"] += "changed"
    elif mutation == "hash":
        data["source_text_sha256"] = "0" * 64
    elif mutation in {"offset", "marker", "text"}:
        data["tokens"] = list(data["tokens"])
        data["tokens"][0][{"offset": "start", "marker": "marker", "text": "text"}[mutation]] = {
            "offset": 0,
            "marker": "⟦PH_FAKE⟧",
            "text": "[changed]",
        }[mutation]
    elif mutation == "masked":
        data["masked_text"] += "changed"
    elif mutation == "namespace":
        data["namespace"] = uuid4().hex
    else:
        data["tokens"] = data["tokens"][1:]
    forged = ProtectedText.model_validate(data)
    result = RestorationEngine().restore(forged, protected.masked_text)
    assert result.text is None
    assert result.issues[0].code == "invalid_protection_map"
    assert result.issues[0].stage == "mapping"


def test_custom_tag_policy_is_explicit_and_never_imports_handlers():
    tags = TagProtector(custom_paired={"wave"}, custom_self_closing={"icon"})
    source = "{wave=2}Hello [name]{icon=heart}{/wave}"
    masked = MaskingEngine(tags=tags).mask(source)
    assert masked.valid
    result = RestorationEngine(ValidationEngine(tags=tags)).restore(
        masked.protected, masked.protected.masked_text
    )
    assert result.text == source
    assert not RestorationEngine().restore(masked.protected, masked.protected.masked_text).valid
    with pytest.raises(ValueError):
        TagProtector(custom_self_closing={"b"})


@pytest.mark.parametrize(
    "text", ["x" * 65537, "[" + "(" * 100 + "x" + ")" * 100 + "]", "[x] " * 3000]
)
def test_parser_limits_return_diagnostics_without_recursion_or_hang(text):
    result = MaskingEngine().mask(text)
    assert not result.valid
    assert any(issue.code.endswith("limit") for issue in result.issues)


def test_tokenizer_covers_original_text_once_with_character_offsets():
    source = "مرحبا [[ {b}[players['x]y']!s]{/b}\n100%%"
    parsed = TextTokenizer().tokenize(source)
    assert parsed.valid
    assert "".join(token.text for token in parsed.tokens) == source
    assert all(a.end == b.start for a, b in zip(parsed.tokens, parsed.tokens[1:], strict=False))


def test_syntax_is_never_executed(tmp_path):
    sentinel = tmp_path / "must-not-exist"
    source = f"[__import__('pathlib').Path({str(sentinel)!r}).write_text('executed')]"
    protected = package(source)
    assert protected is not None
    assert RestorationEngine().restore(protected, protected.masked_text).text == source
    assert not sentinel.exists()


@pytest.mark.parametrize("text", ["", "  "])
def test_empty_translation_is_rejected_even_without_variables(text):
    result = RestorationEngine().restore(package("Hello"), text)
    assert not result.valid and result.text is None
    assert result.issues[0].code == "empty_translation"


def test_raw_validation_and_unit_binding(source):
    service = ProtectionService()
    prepared = service.prepare_unit(source)
    assert prepared.ready
    assert service.validate_translation(source, source.source_text).valid
    assert not service.validate_translation(source, "بدون الرموز").valid
    foreign = prepared.model_copy(update={"unit_id": "other"})
    result = service.restore_unit(source, foreign, prepared.result.protected.masked_text)
    assert not result.valid and result.text is None
    assert result.issues[0].code == "unit_protection_mismatch"
    assert prepared.source_sha256 == source.source_sha256
    assert (
        prepared.result.protected.source_text_sha256
        == hashlib.sha256(source.source_text.encode("utf-8")).hexdigest()
    )


@pytest.mark.parametrize("text", ["⟦", "⟧", "⟦⟦", "⟦PH_incomplete", "⟦PH_⟧"])
def test_malformed_or_unknown_marker_protocol_is_rejected_without_hanging(text):
    result = RestorationEngine().restore(package("Hello"), text)
    assert not result.valid and result.text is None
    assert {issue.code for issue in result.issues} & {"malformed_marker", "unknown_marker"}


def test_variable_reordering_is_explicitly_rejected_by_the_default_policy():
    protected = package("[first] before [second]")
    first, second = (token.marker for token in protected.tokens)
    result = RestorationEngine().restore(protected, second + " ثم " + first)
    assert result.text is None
    assert result.issues[0].code == "marker_order"


def test_tag_interpolation_is_preserved_as_one_opaque_tag_and_syntax_checked():
    protected = package("{a=[target]}link{/a}")
    assert protected is not None
    assert [token.text for token in protected.tokens] == ["{a=[target]}", "{/a}"]
    assert (
        RestorationEngine().restore(protected, protected.masked_text).text == protected.source_text
    )
    assert not MaskingEngine().mask("{a=[target}link{/a}").valid


def test_decoded_backslash_does_not_hide_a_tag_or_interpolation():
    protected = package("\\{b}[name]{/b}")
    assert [token.text for token in protected.tokens] == ["\\", "{b}", "[name]", "{/b}"]


def test_marker_at_an_escape_boundary_is_rejected_even_with_correct_id_count():
    protected = package("{{ text")
    result = RestorationEngine().restore(protected, "{" + protected.masked_text)
    assert not result.valid and result.text is None


def test_plain_closing_brackets_are_not_incorrectly_rejected():
    protected = package("Literal ] and } are allowed.")
    assert protected.tokens == ()
    assert RestorationEngine().restore(protected, protected.masked_text).valid


@pytest.mark.parametrize("candidate", [None, 3, {"text": "hello"}])
def test_non_text_provider_values_fail_closed(candidate):
    result = RestorationEngine().restore(package(), candidate)
    assert not result.valid and result.text is None
    assert result.issues[0].code == "invalid_translation_type"


def test_oversized_translation_is_rejected_before_marker_parsing():
    result = RestorationEngine().restore(package("Hello"), "x" * 524289)
    assert not result.valid and result.issues[0].code == "translation_length_limit"


@pytest.mark.parametrize("translation", ["[changed]", "[name] [name]", "{b}[name]{/b}", "[name"])
def test_existing_translation_validation_detects_lost_changed_and_added_structure(
    source, translation
):
    result = ProtectionService().validate_translation(source, translation)
    assert not result.valid
