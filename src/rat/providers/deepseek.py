from rat.providers.openai_compatible import OpenAICompatibleProvider


class DeepSeekProvider(OpenAICompatibleProvider):
    provider_id = "deepseek"
    endpoint = "https://api.deepseek.com"
