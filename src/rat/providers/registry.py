from rat.domain.protocols import TranslationProvider
from rat.domain.translation import ProviderConfig
from rat.providers.base import ProviderError
from rat.providers.mock import MockProvider


def get_provider(
    provider_id: str, config: ProviderConfig | None = None, *, secret_store=None, client=None
) -> TranslationProvider:
    import logging

    for name in ("openai", "httpx", "httpcore", "google.genai"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
        logging.getLogger(name).propagate = False
    if provider_id == "mock":
        return MockProvider()
    if config is None or config.provider_id != provider_id:
        raise ValueError("A matching provider profile is required.")
    from rat.providers.deepseek import DeepSeekProvider
    from rat.providers.gemini import GeminiProvider
    from rat.providers.google_translate import GoogleTranslateProvider
    from rat.providers.openai import OpenAIProvider
    from rat.providers.openai_compatible import OpenAICompatibleProvider
    from rat.providers.openrouter import OpenRouterProvider
    from rat.security.secrets import SecretStore

    if provider_id == "google_translate":
        return GoogleTranslateProvider(config)
    key = (secret_store or SecretStore()).get(config.profile_id)
    if not key and provider_id != "custom":
        raise ProviderError("missing_key")
    classes = {
        "gemini": GeminiProvider,
        "openai": OpenAIProvider,
        "deepseek": DeepSeekProvider,
        "openrouter": OpenRouterProvider,
        "custom": OpenAICompatibleProvider,
    }
    return classes[provider_id](config, key, client=client)
