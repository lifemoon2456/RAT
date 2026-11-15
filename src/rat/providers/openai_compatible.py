from rat.domain.translation import ProviderConfig, StructuredBatch
from rat.providers.base import BaseTranslationProvider, ProviderError
from rat.providers.structured import messages, parse_response, safe_api_error


class OpenAICompatibleProvider(BaseTranslationProvider):
    provider_id = "custom"
    endpoint = ""

    def __init__(self, config: ProviderConfig, api_key: str, *, client=None):
        endpoint = config.base_url if self.provider_id == "custom" else self.endpoint
        if not endpoint:
            raise ProviderError("invalid_endpoint")
        if not api_key and self.provider_id != "custom":
            raise ProviderError("missing_key")
        self.config = config
        if client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError:
                raise ProviderError("missing_dependency") from None
            client = AsyncOpenAI(
                api_key=api_key or "local-no-key",
                base_url=endpoint,
                timeout=config.timeout_seconds,
                max_retries=0,
            )
        self.client = client

    async def translate_batch(self, items, *, source_language, target_language, context, settings):
        if not self.config.model:
            raise ProviderError("missing_model")
        mode = "json_object" if self.provider_id == "deepseek" else self.config.output_mode
        response_format = {"type": mode}
        if mode == "json_schema":
            response_format["json_schema"] = {
                "name": "translations",
                "strict": True,
                "schema": StructuredBatch.model_json_schema(),
            }
        try:
            response = await self.client.chat.completions.create(
                model=self.config.model,
                messages=messages(items, source_language, target_language, context, settings),
                response_format=response_format,
                **{
                    (
                        "max_completion_tokens" if self.provider_id == "openai" else "max_tokens"
                    ): settings.get("output_reserve_tokens", 2000)
                },
            )
        except Exception as error:
            raise safe_api_error(error) from None
        if not response.choices or response.choices[0].finish_reason != "stop":
            raise ProviderError("invalid_response")
        choice = response.choices[0].message
        if getattr(choice, "refusal", None):
            raise ProviderError("request_rejected")
        usage = None
        if response.usage:
            usage = {
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
            }
        return parse_response(choice.content, items, self.provider_id, usage)

    async def list_models(self):
        try:
            return [item.id async for item in self.client.models.list()]
        except Exception as error:
            raise safe_api_error(error) from None

    async def aclose(self):
        await self.client.close()
