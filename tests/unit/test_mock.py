import asyncio

import pytest

from rat.domain.models import ProviderResult
from rat.domain.protocols import TranslationProvider
from rat.providers.registry import get_provider


def invoke(provider, items):
    return asyncio.run(
        provider.translate_batch(
            items, source_language="en", target_language="ar", context={}, settings={}
        )
    )


def test_mock_contract_and_mapping_by_unit_id(source, monkeypatch):
    def no_network(*_args, **_kwargs):
        raise AssertionError("Mock must not use a network socket")

    # Windows' asyncio loop may create a local socket pair during initialization.
    monkeypatch.setattr("socket.create_connection", no_network)
    monkeypatch.setattr("httpx.Client.request", no_network)
    monkeypatch.setattr("httpx.AsyncClient.request", no_network)
    provider = get_provider("mock")
    assert isinstance(provider, TranslationProvider)
    assert asyncio.run(provider.test_connection()) == {
        "provider_id": "mock",
        "status": "simulated",
        "network_used": False,
    }
    assert asyncio.run(provider.list_models()) is None
    items = [
        {"unit_id": "a", "text": source.source_text},
        {"unit_id": "b", "text": "{b}Hello{/b} [mood!t] %% %(name)s {#context}"},
        {"unit_id": "c", "text": 'عربي English 123\n"quoted"'},
    ]
    results = [ProviderResult.model_validate(result) for result in invoke(provider, items)]
    assert [result.unit_id for result in results] == ["c", "b", "a"]
    by_id = {result.unit_id: result for result in results}
    for item in items:
        assert by_id[item["unit_id"]].translation_text == item["text"]
        assert by_id[item["unit_id"]].simulated
        assert by_id[item["unit_id"]].usage is None
    # This verifies echo fidelity only, not a tokenizer or a Ren'Py validator.


@pytest.mark.parametrize(
    "items",
    [
        [{"unit_id": "x", "text": None}],
        [{"text": "hello"}],
        [{"unit_id": "x", "text": "a"}, {"unit_id": "x", "text": "b"}],
    ],
)
def test_mock_rejects_malformed_inputs(items):
    with pytest.raises(ValueError):
        invoke(get_provider("mock"), items)


def test_unimplemented_provider_is_not_reported_as_available():
    with pytest.raises(ValueError):
        get_provider("gemini")
