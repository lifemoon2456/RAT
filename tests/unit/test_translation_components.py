import asyncio

import pytest

from rat.domain.translation import GlossaryTerm, ProviderConfig, TranslationOptions
from rat.protection import MaskingEngine
from rat.providers.base import ProviderError
from rat.translation.batching import BatchManager, estimate_tokens
from rat.translation.context import ContextBuilder
from rat.translation.glossary import GlossarySystem
from rat.translation.rate_limits import RateLimitManager
from rat.translation.retries import RetryManager
from rat.translation.translation_memory import TranslationMemory


def test_batches_respect_count_and_unicode_budget_without_losing_units():
    options = TranslationOptions(max_items=2, max_characters=100, max_input_tokens=1000)
    items = [{"unit_id": str(i), "text": "مرحبا " * 4} for i in range(7)]
    batches, oversized = BatchManager(options).split(items)
    assert [len(batch) for batch in batches] == [2, 2, 2, 1]
    assert [item for batch in batches for item in batch] == items
    assert not oversized
    assert estimate_tokens("مرحبا") > estimate_tokens("hello")


def test_oversized_single_item_is_reported_and_later_items_continue():
    items = [{"unit_id": "large", "text": "x" * 10000}, {"unit_id": "small", "text": "ok"}]
    batches, errors = BatchManager(TranslationOptions(max_input_tokens=1000)).split(items)
    assert errors == ["large"]
    assert batches == [[items[1]]]


def test_context_limit_reserves_output_and_includes_shared_glossary():
    manager = BatchManager(TranslationOptions(model_context_limit=2048, output_reserve_tokens=1800))
    assert manager.split([{"unit_id": "a", "text": "x"}])[1] == ["a"]
    manager = BatchManager(TranslationOptions(max_input_tokens=1024))
    assert manager.split([{"unit_id": "a", "text": "x"}], {"glossary": "x" * 6000})[1] == ["a"]


def test_retry_exponential_backoff_and_retry_after():
    delays, calls = [], []

    async def sleep(seconds):
        delays.append(seconds)

    async def operation():
        calls.append(1)
        if len(calls) == 1:
            raise ProviderError("rate_limit", retryable=True, retry_after=3)
        if len(calls) == 2:
            raise ProviderError("server_error", retryable=True)
        return "done"

    assert asyncio.run(RetryManager(4, sleep=sleep, jitter=lambda: 0).run(operation)) == "done"
    assert delays == [3, 2]


@pytest.mark.parametrize(
    "code,retryable,attempts",
    [("authentication", False, 1), ("invalid_response", False, 1), ("timeout", True, 3)],
)
def test_retry_classifies_permanent_and_exhausted_errors(code, retryable, attempts):
    calls = []

    async def operation():
        calls.append(1)
        raise ProviderError(code, retryable=retryable)

    async def sleep(_seconds):
        pass

    with pytest.raises(ProviderError):
        asyncio.run(RetryManager(3, sleep=sleep).run(operation))
    assert len(calls) == attempts


def test_rate_limit_enforces_concurrency_and_spacing():
    async def run():
        limiter = RateLimitManager(2, 100000)
        active, peak = 0, 0

        async def work():
            nonlocal active, peak
            async with limiter.slot():
                active += 1
                peak = max(peak, active)
                await asyncio.sleep(0.01)
                active -= 1

        await asyncio.gather(*(work() for _ in range(8)))
        assert peak == 2
        clock, delays = [0.0], []

        async def sleep(delay):
            delays.append(delay)
            clock[0] += delay

        limiter = RateLimitManager(1, 60, clock=lambda: clock[0], sleep=sleep)
        for _ in range(3):
            async with limiter.slot():
                pass
        assert delays == [1, 1]

    asyncio.run(run())


def test_glossary_locks_names_and_does_not_touch_renpy_markers(tmp_path):
    path = tmp_path / "terms.csv"
    path.write_text(
        "source,target,locked,case_sensitive\nEileen,إيلين,true,false\n", encoding="utf-8"
    )
    glossary = GlossarySystem.from_csv(path)
    source = MaskingEngine().mask("Eileen met EILEEN and Eileenette [name]").protected
    masked, mapping = glossary.mask(source.masked_text)
    assert len(mapping) == 2
    assert source.tokens[0].marker in masked
    assert "Eileenette" in masked
    restored = glossary.restore(masked, mapping)
    assert restored.startswith("إيلين met إيلين")
    assert source.tokens[0].marker in restored


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "reorder", "unknown"])
def test_glossary_rejects_damaged_locked_markers(mutation):
    glossary = GlossarySystem([GlossaryTerm(source="Name", target="اسم")])
    text, mapping = glossary.mask("Name Name")
    a, b = [item["marker"] for item in mapping]
    if mutation == "missing":
        text = text.replace(a, "")
    elif mutation == "duplicate":
        text += a
    elif mutation == "reorder":
        text = b + " " + a
    else:
        text += "⟦GL_unknown⟧"
    with pytest.raises(ValueError):
        glossary.restore(text, mapping)


@pytest.mark.parametrize("target", ["[name]", "{b}bad{/b}", "⟦GL_reserved⟧", "line\nline"])
def test_glossary_cannot_inject_renpy_syntax(target):
    with pytest.raises(ValueError):
        GlossarySystem([GlossaryTerm(source="Name", target=target)])


def test_memory_keys_respect_sensitive_context_and_simulation(source):
    options, profile, glossary = TranslationOptions(), ProviderConfig(), GlossarySystem()
    context = ContextBuilder().build(source, [source])
    key = TranslationMemory.key(source.project_id, source, context, profile, options, glossary)
    for changed_context, changed_profile, changed_options, changed_glossary in [
        ({**context, "speaker": "other"}, profile, options, glossary),
        (
            context,
            profile.model_copy(update={"provider_id": "openai", "model": "user-model"}),
            options,
            glossary,
        ),
        (context, profile, options.model_copy(update={"style": "literary"}), glossary),
        (context, profile, options, GlossarySystem([GlossaryTerm(source="Name", target="اسم")])),
    ]:
        assert (
            TranslationMemory.key(
                source.project_id,
                source,
                changed_context,
                changed_profile,
                changed_options,
                changed_glossary,
            )
            != key
        )


def test_context_is_bounded_and_protected_without_mutating_source(source):
    builder = ContextBuilder(max_neighbors=1)
    context = {"speaker": "e", "label": "start", "before": ["Hello [name]"], "after": ["{b}broken"]}
    masked = builder.protected(context)
    assert "[name]" not in masked["before"][0]
    assert masked["after"] == []
    assert context["before"] == ["Hello [name]"]
    assert "[name]" not in builder.protected({**context, "speaker": "[name]"})["speaker"]


@pytest.mark.parametrize("source", ["[name]", "{b}name{/b}", " "])
def test_glossary_source_cannot_pass_unprotected_markup_as_metadata(source):
    with pytest.raises(ValueError):
        GlossarySystem([GlossaryTerm(source=source, target="اسم")])
