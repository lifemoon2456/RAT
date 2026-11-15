from enum import StrEnum


class UnitStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    TRANSLATED = "translated"
    VALIDATED = "validated"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"
    APPROVED = "approved"
    EXCLUDED = "excluded"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class UnitKind(StrEnum):
    DIALOGUE = "dialogue"
    NARRATION = "narration"
    MENU_CHOICE = "menu_choice"
    STRING = "string"
    SCREEN_TEXT = "screen_text"
    EXISTING_TRANSLATION = "existing_translation"
    UNKNOWN_DYNAMIC = "unknown_dynamic"
    IMAGE_TEXT = "image_text"
