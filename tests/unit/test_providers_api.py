import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from openai import AsyncOpenAI

from rat.domain.protocols import TranslationProvider
from rat.domain.translation import ProviderConfig
from rat.providers.base import BaseTranslationProvider, ProviderError
from rat.providers.deepseek import DeepSeekProvider
from rat.providers.gemini import GeminiProvider
from rat.providers.google_translate import GoogleTranslateProvider
from rat.providers.google_worker import run, translate_segments
from rat.providers.openai import OpenAIProvider
from rat.providers.openai_compatible import OpenAICompatibleProvider
from rat.providers.openrouter import OpenRouterProvider
from rat.providers.structured import parse_response


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    def denied(*_args, **_kwargs):
        raise AssertionError("Network access is forbidden in provider tests")

    monkeypatch.setattr("socket.create_connection", denied)


@pytest.mark.parametrize(
    "adapter", [OpenAIProvider, DeepSeekProvider, OpenRouterProvider, OpenAICompatibleProvider]
)
def test_openai_family_real_sdk_uses_ids_schema_timeout_and_no_internal_retry(adapter):
    captured = []

    def respond(request):
        data = json.loads(request.content)
        captured.append(data)
        items = json.loads(data["messages"][1]["content"])["items"]
        body = {
            "translations": [
                {"unit_id": item["unit_id"], "text": item["text"]} for item in reversed(items)
            ]
        }
        return httpx.Response(
            200,
            json={
                "id": "test",
                "object": "chat.completion",
                "created": 0,
                "model": "user-chosen-model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": json.dumps(body)},
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
            },
        )

    async def exercise():
        client = AsyncOpenAI(
            api_key="SYNTHETIC_TEST_KEY",
            base_url="https://example.test/v1",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        )
        config = ProviderConfig(
            provider_id=adapter.provider_id,
            model="user-chosen-model",
            base_url="https://example.test/v1",
        )
        provider = adapter(config, "SYNTHETIC_TEST_KEY", client=client)
        assert isinstance(provider, BaseTranslationProvider) and isinstance(
            provider, TranslationProvider
        )
        try:
            result = await provider.translate_batch(
                [{"unit_id": "a", "text": "Hello"}, {"unit_id": "b", "text": "World"}],
                source_language="en",
                target_language="ar",
                context={},
                settings={},
            )
            assert [item["unit_id"] for item in result] == ["b", "a"]
            assert result[0]["usage"] == {"input_tokens": 12, "output_tokens": 8}
            assert result[1]["usage"] is None
            assert captured[0]["response_format"]["type"] == (
                "json_object" if adapter is DeepSeekProvider else "json_schema"
            )
        finally:
            await provider.aclose()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "status,code,retryable",
    [
        (401, "authentication", False),
        (429, "rate_limit", True),
        (503, "server_error", True),
        (400, "request_rejected", False),
    ],
)
def test_api_failures_are_safe_categories(status, code, retryable):
    async def exercise():
        client = AsyncOpenAI(
            api_key="SYNTHETIC_SECRET",
            max_retries=0,
            http_client=httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda _request: httpx.Response(
                        status,
                        headers={"retry-after": "5"},
                        json={"error": {"message": "SYNTHETIC_SECRET"}},
                    )
                )
            ),
        )
        provider = OpenAIProvider(
            ProviderConfig(provider_id="openai", model="test-model"),
            "SYNTHETIC_SECRET",
            client=client,
        )
        try:
            with pytest.raises(ProviderError) as caught:
                await provider.translate_batch(
                    [{"unit_id": "a", "text": "Hello"}],
                    source_language="en",
                    target_language="ar",
                    context={},
                    settings={},
                )
            assert caught.value.code == code and caught.value.retryable == retryable
            assert "SYNTHETIC_SECRET" not in str(caught.value)
            if status == 429:
                assert caught.value.retry_after == 5
        finally:
            await provider.aclose()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        '{"translations":[]}',
        '{"translations":[{"unit_id":"foreign","text":"x"}]}',
        '{"translations":[{"unit_id":"a","text":"x"},{"unit_id":"a","text":"y"}]}',
        '{"translations":[{"unit_id":"a","text":null}]}',
    ],
)
def test_structured_output_rejects_missing_duplicate_unknown_and_invalid_text(raw):
    with pytest.raises(ProviderError, match="invalid_response"):
        parse_response(raw, [{"unit_id": "a", "text": "Hello"}], "openai")


def test_gemini_uses_installed_sdk_and_mock_http_transport():
    from google import genai
    from google.genai import types

    captured = []

    def respond(request):
        data = json.loads(request.content)
        captured.append(data)
        payload = json.loads(data["contents"][0]["parts"][0]["text"])
        raw = {
            "translations": [
                {"unit_id": item["unit_id"], "text": item["text"]} for item in payload["items"]
            ]
        }
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {"role": "model", "parts": [{"text": json.dumps(raw)}]},
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {"promptTokenCount": 11, "candidatesTokenCount": 7},
            },
        )

    async def exercise():
        client = genai.Client(
            api_key="SYNTHETIC_TEST_KEY",
            http_options=types.HttpOptions(
                retry_options=types.HttpRetryOptions(attempts=1),
                async_client_args={"transport": httpx.MockTransport(respond)},
            ),
        )
        provider = GeminiProvider(
            ProviderConfig(provider_id="gemini", model="user-model"),
            "SYNTHETIC_TEST_KEY",
            client=client,
        )
        try:
            result = await provider.translate_batch(
                [{"unit_id": "a", "text": "Hello"}],
                source_language="en",
                target_language="ar",
                context={},
                settings={},
            )
            assert result[0]["translation_text"] == "Hello"
            assert "responseJsonSchema" in captured[0]["generationConfig"]
            assert result[0]["usage"]["input_tokens"] == 11
        finally:
            await provider.aclose()

    asyncio.run(exercise())


def test_google_worker_preserves_markers_locally_and_ids_bind_to_each_item(monkeypatch, tmp_path):
    from rat.protection import MaskingEngine

    package = MaskingEngine().mask("Hello [name] {b}friend{/b}.").protected
    calls = []

    class FakeGoogle:
        def __init__(self, **_kwargs):
            pass

        def translate(self, text):
            calls.append(text)
            return text.replace("Hello", "مرحبا").replace("friend", "صديق")

    monkeypatch.setattr("deep_translator.GoogleTranslator", FakeGoogle)
    source, target = tmp_path / "in.json", tmp_path / "out.json"
    source.write_text(
        json.dumps(
            {
                "source": "en",
                "target": "ar",
                "items": [{"unit_id": "a", "text": package.masked_text}],
            }
        ),
        encoding="utf-8",
    )
    assert run(source, target) == 0
    body = json.loads(target.read_text(encoding="utf-8"))
    assert body["translations"][0]["unit_id"] == "a"
    assert all("⟦" not in call and "[name]" not in call for call in calls)
    assert all(token.marker in body["translations"][0]["text"] for token in package.tokens)


def test_google_hard_timeout_kills_and_reaps_the_worker(monkeypatch):
    process = SimpleNamespace(returncode=None, killed=False)

    async def wait():
        if not process.killed:
            await asyncio.sleep(5)
        process.returncode = -1
        return -1

    def kill():
        process.killed = True

    process.wait, process.kill = wait, kill

    async def launch(*_args, **_kwargs):
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
    provider = GoogleTranslateProvider(
        ProviderConfig(provider_id="google_translate", timeout_seconds=0.01)
    )
    with pytest.raises(ProviderError, match="timeout"):
        asyncio.run(
            provider.translate_batch(
                [{"unit_id": "a", "text": "Hello"}],
                source_language="en",
                target_language="ar",
                context={},
                settings={},
            )
        )
    assert process.killed and process.returncode == -1


def test_google_segmentation_preserves_whitespace_and_rejects_empty_translations():
    assert translate_segments(" hello ", lambda text: text.upper()) == " HELLO "
    with pytest.raises(ValueError):
        translate_segments("hello", lambda _text: None)


def test_list_models_uses_live_sdk_pagination_against_fake_transport():
    async def exercise():
        client = AsyncOpenAI(
            api_key="SYNTHETIC",
            max_retries=0,
            http_client=httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda _request: httpx.Response(
                        200,
                        json={
                            "object": "list",
                            "data": [
                                {
                                    "id": "account-model",
                                    "created": 0,
                                    "object": "model",
                                    "owned_by": "test",
                                }
                            ],
                        },
                    )
                )
            ),
        )
        provider = OpenAIProvider(
            ProviderConfig(provider_id="openai", model="chosen"), "SYNTHETIC", client=client
        )
        try:
            assert await provider.list_models() == ["account-model"]
        finally:
            await provider.aclose()

    asyncio.run(exercise())


def test_gemini_list_models_uses_the_installed_sdk_without_fixed_names():
    from google import genai
    from google.genai import types

    async def exercise():
        client = genai.Client(
            api_key="SYNTHETIC",
            http_options=types.HttpOptions(
                async_client_args={
                    "transport": httpx.MockTransport(
                        lambda _request: httpx.Response(
                            200, json={"models": [{"name": "models/account-model"}]}
                        )
                    )
                }
            ),
        )
        provider = GeminiProvider(
            ProviderConfig(provider_id="gemini", model="chosen"), "SYNTHETIC", client=client
        )
        try:
            assert await provider.list_models() == ["models/account-model"]
        finally:
            await provider.aclose()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "url",
    [
        "http://remote.example/v1",
        "https://user:password@example.test",
        "https://example.test?api_key=secret",
        "https://example.test/#secret",
    ],
)
def test_custom_endpoints_reject_credential_urls_and_insecure_remote_http(url):
    with pytest.raises(ValueError):
        ProviderConfig(provider_id="custom", base_url=url)
