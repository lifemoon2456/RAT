from rat.providers.openai_compatible import OpenAICompatibleProvider


class OpenRouterProvider(OpenAICompatibleProvider):
    provider_id = "openrouter"
    endpoint = "https://openrouter.ai/api/v1"
