from rat.protection import MaskingEngine


class ContextBuilder:
    def __init__(self, max_neighbors=2, max_characters=600):
        self.max_neighbors, self.max_characters = max_neighbors, max_characters

    def build(self, source, sources):
        ordered = sorted(
            sources, key=lambda item: (item.source_relpath, item.source_line or 0, item.unit_id)
        )
        index = next(i for i, item in enumerate(ordered) if item.unit_id == source.unit_id)
        before = list(source.context_before) or [
            item.source_text
            for item in ordered[max(0, index - self.max_neighbors) : index]
            if item.source_relpath == source.source_relpath and item.label == source.label
        ]
        after = list(source.context_after) or [
            item.source_text
            for item in ordered[index + 1 : index + 1 + self.max_neighbors]
            if item.source_relpath == source.source_relpath and item.label == source.label
        ]
        return {
            "speaker": source.speaker,
            "label": source.label,
            "before": before[-self.max_neighbors :],
            "after": after[: self.max_neighbors],
        }

    def protected(self, context):
        result = {
            "speaker": context["speaker"],
            "label": context["label"],
            "before": [],
            "after": [],
        }
        for key in ("speaker", "label"):
            if result[key] is not None:
                masked = MaskingEngine().mask(result[key])
                result[key] = masked.protected.masked_text if masked.valid else None
        for key in ("before", "after"):
            for text in context[key]:
                # Do not cut a placeholder/tag in half. Omit oversized context instead.
                if len(text) <= self.max_characters:
                    masked = MaskingEngine().mask(text)
                    if masked.valid:
                        result[key].append(masked.protected.masked_text)
        return result
