import json
import math

from rat.domain.translation import TranslationOptions


def estimate_tokens(value) -> int:
    """Conservative UTF-8 heuristic, including long marker IDs; not a billed-token count."""
    return math.ceil(len(json.dumps(value, ensure_ascii=False).encode("utf-8")) / 3)


class BatchManager:
    def __init__(self, options: TranslationOptions):
        self.options = options

    def fits(self, items, context):
        data = {"items": items, **context}
        budget = self.options.max_input_tokens
        if self.options.model_context_limit:
            budget = min(
                budget, self.options.model_context_limit - self.options.output_reserve_tokens
            )
        return (
            len(items) <= self.options.max_items
            and sum(len(item["text"]) for item in items) <= self.options.max_characters
            and estimate_tokens(data) + 512 <= budget
        )

    def split(self, items, context=None):
        batches, oversized, current = [], [], []
        context = context or {}
        for item in items:
            if not self.fits([item], context):
                oversized.append(item["unit_id"])
                continue
            if current and not self.fits([*current, item], context):
                batches.append(current)
                current = []
            current.append(item)
        if current:
            batches.append(current)
        return batches, oversized
