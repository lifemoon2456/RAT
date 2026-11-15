"""Public provider contract; concrete adapters depend on domain only."""

from abc import ABC, abstractmethod

from rat.domain.protocols import TranslationProvider


class ProviderError(Exception):
    """Safe category only: never retain remote messages, URLs, headers or secrets."""

    def __init__(self, code: str, *, retryable: bool = False, retry_after: float | None = None):
        allowed = {
            "timeout",
            "network_error",
            "rate_limit",
            "server_error",
            "authentication",
            "invalid_response",
            "request_rejected",
            "missing_dependency",
            "missing_key",
            "missing_model",
            "invalid_endpoint",
            "google_failed",
            "provider_failure",
        }
        self.code = code if code in allowed else "provider_failure"
        self.retryable = retryable
        self.retry_after = retry_after
        super().__init__(self.code)


class BaseTranslationProvider(ABC):
    provider_id: str

    @abstractmethod
    async def translate_batch(
        self,
        items: list[dict],
        *,
        source_language: str,
        target_language: str,
        context: dict,
        settings: dict,
    ) -> list[dict]: ...

    async def test_connection(self) -> dict:
        from rat.protection import MaskingEngine, RestorationEngine

        sample = MaskingEngine().mask("Hello [name]!")
        assert sample.protected is not None
        result = await self.translate_batch(
            [{"unit_id": "connection_test", "text": sample.protected.masked_text}],
            source_language="en",
            target_language="ar",
            context={},
            settings={},
        )
        if (
            len(result) != 1
            or result[0].get("unit_id") != "connection_test"
            or result[0].get("status") != "success"
            or not RestorationEngine()
            .restore(sample.protected, result[0].get("translation_text"))
            .valid
        ):
            raise ProviderError("invalid_response")
        return {"provider_id": self.provider_id, "status": "success", "network_used": True}

    async def list_models(self) -> list[str] | None:
        return None

    async def aclose(self) -> None:
        return None


__all__ = ["BaseTranslationProvider", "ProviderError", "TranslationProvider"]
