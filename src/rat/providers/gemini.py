from rat.domain.translation import ProviderConfig, StructuredBatch
from rat.providers.base import BaseTranslationProvider, ProviderError
from rat.providers.structured import messages, parse_response, safe_api_error


class GeminiProvider(BaseTranslationProvider):
    provider_id = "gemini"

    def __init__(self, config: ProviderConfig, api_key: str, *, client=None):
        if not api_key:
            raise ProviderError("missing_key")
        self.config = config
        if client is None:
            try:
                from google import genai
                from google.genai import types
            except ImportError:
                raise ProviderError("missing_dependency") from None
            client = genai.Client(
                vertexai=False,
                api_key=api_key,
                http_options=types.HttpOptions(
                    timeout=int(config.timeout_seconds * 1000),
                    retry_options=types.HttpRetryOptions(attempts=1),
                ),
            )
        self.client = client

    async def translate_batch(self, items, *, source_language, target_language, context, settings):
        if not self.config.model:
            raise ProviderError("missing_model")
        prompt = messages(items, source_language, target_language, context, settings)
        try:
            response = await self.client.aio.models.generate_content(
                model=self.config.model,
                contents=prompt[1]["content"],
                config={
                    "system_instruction": prompt[0]["content"],
                    "response_mime_type": "application/json",
                    "response_json_schema": StructuredBatch.model_json_schema(),
                    "max_output_tokens": settings.get("output_reserve_tokens", 2000),
                },
            )
        except Exception as error:
            raise safe_api_error(error) from None
        if (
            not response.candidates
            or str(response.candidates[0].finish_reason).split(".")[-1] != "STOP"
        ):
            raise ProviderError("invalid_response")
        usage = None
        if response.usage_metadata:
            usage = {
                "input_tokens": response.usage_metadata.prompt_token_count or 0,
                "output_tokens": response.usage_metadata.candidates_token_count or 0,
            }
        return parse_response(response.text, items, self.provider_id, usage)

    async def list_models(self):
        try:
            return [item.name async for item in await self.client.aio.models.list()]
        except Exception as error:
            raise safe_api_error(error) from None

    async def aclose(self):
        await self.client.aio.aclose()
        self.client.close()
