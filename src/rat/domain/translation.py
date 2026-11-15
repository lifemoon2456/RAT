from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import Field, field_validator

from rat.domain.base import StrictModel

ProviderId = Literal[
    "mock", "gemini", "openai", "deepseek", "openrouter", "google_translate", "custom"
]


class ProviderConfig(StrictModel):
    profile_id: str = Field(default_factory=lambda: uuid4().hex, pattern=r"^[0-9a-f]{32}$")
    provider_id: ProviderId = "mock"
    model: str = Field(default="", max_length=200)
    base_url: str = ""
    timeout_seconds: float = Field(default=90, gt=0, le=600)
    output_mode: Literal["json_schema", "json_object"] = "json_schema"

    @field_validator("base_url")
    @classmethod
    def safe_endpoint(cls, value: str) -> str:
        if not value:
            return value
        parsed = urlsplit(value)
        local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if (
            parsed.scheme != "https" and not (parsed.scheme == "http" and local)
        ) or not parsed.hostname:
            raise ValueError("Use HTTPS or an HTTP loopback endpoint.")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Endpoint must not contain credentials, query strings, or fragments.")
        return value.rstrip("/")


class TranslationOptions(StrictModel):
    source_language: str = "auto"
    target_language: str = "ar"
    style: str = Field(default="modern_standard_arabic", max_length=500)
    max_items: int = Field(default=12, ge=1, le=100)
    max_characters: int = Field(default=12000, ge=100, le=1000000)
    max_input_tokens: int = Field(default=6000, ge=128, le=1000000)
    output_reserve_tokens: int = Field(default=2000, ge=64, le=100000)
    model_context_limit: int | None = Field(default=None, ge=256)
    concurrency: int = Field(default=2, ge=1, le=16)
    requests_per_minute: int = Field(default=30, ge=1, le=100000)
    retry_attempts: int = Field(default=4, ge=1, le=10)
    alternatives_only: bool = False
    use_translation_memory: bool = True
    variant_index: int = Field(default=0, ge=0, le=5)


class GlossaryTerm(StrictModel):
    source: str = Field(min_length=1, max_length=200)
    target: str = Field(min_length=1, max_length=200)
    case_sensitive: bool = True
    locked: bool = True
    notes: str = Field(default="", max_length=500)


class StructuredTranslation(StrictModel):
    unit_id: str
    text: str


class StructuredBatch(StrictModel):
    translations: list[StructuredTranslation]


class JobProgress(StrictModel):
    job_id: str
    status: str
    total: int
    translated: int
    remaining: int
    errors: int
    simulated: int = 0
    skipped: int = 0
