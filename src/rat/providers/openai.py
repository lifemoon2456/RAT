from rat.providers.openai_compatible import OpenAICompatibleProvider


class OpenAIProvider(OpenAICompatibleProvider):
    provider_id = "openai"
    endpoint = "https://api.openai.com/v1"
