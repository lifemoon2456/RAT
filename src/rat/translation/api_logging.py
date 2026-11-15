import logging
from logging.handlers import RotatingFileHandler

from rat.providers.base import ProviderError


class ApiLogger:
    def __init__(self, project_dir):
        self.logger = logging.Logger("rat.api.safe", level=logging.INFO)
        self.logger.propagate = False
        self.handler = RotatingFileHandler(
            project_dir / "logs/api.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8"
        )
        self.handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        self.logger.addHandler(self.handler)

    def error(self, provider_id, error):
        provider = (
            provider_id
            if provider_id
            in {"mock", "gemini", "openai", "deepseek", "openrouter", "custom", "google_translate"}
            else "unknown"
        )
        # Reapply the allowlist even for injected/misbehaving providers.
        code = ProviderError(getattr(error, "code", "provider_failure")).code
        self.logger.error("api_error provider=%s code=%s", provider, code)

    def close(self):
        self.handler.close()
