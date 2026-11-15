from rat.domain.models import ProviderResult
from rat.providers.base import BaseTranslationProvider


class MockProvider(BaseTranslationProvider):
    """Offline echo simulator. Does not translate or validate Ren'Py text."""

    provider_id = "mock"

    async def test_connection(self) -> dict:
        return {"provider_id": self.provider_id, "status": "simulated", "network_used": False}

    async def list_models(self) -> list[str] | None:
        return None

    async def translate_batch(
        self,
        items: list[dict],
        *,
        source_language: str,
        target_language: str,
        context: dict,
        settings: dict,
    ) -> list[dict]:
        results = []
        seen: set[str] = set()
        for item in items:
            unit_id = item.get("unit_id")
            text = item.get("text")
            if not isinstance(unit_id, str) or not unit_id or unit_id in seen:
                raise ValueError("Mock items require unique non-empty unit_id values.")
            if not isinstance(text, str):
                raise ValueError("Mock items require a string text field.")
            seen.add(unit_id)
            results.append(
                ProviderResult(
                    unit_id=unit_id,
                    translation_text=text,
                    provider_id=self.provider_id,
                    status="success",
                    simulated=True,
                ).model_dump()
            )
        # Intentionally reversed: consumers must associate results by unit_id.
        return list(reversed(results))
