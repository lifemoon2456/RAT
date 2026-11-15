from typing import Protocol, runtime_checkable


@runtime_checkable
class TranslationProvider(Protocol):
    provider_id: str

    async def test_connection(self) -> dict: ...

    async def list_models(self) -> list[str] | None: ...

    async def translate_batch(
        self,
        items: list[dict],
        *,
        source_language: str,
        target_language: str,
        context: dict,
        settings: dict,
    ) -> list[dict]: ...
