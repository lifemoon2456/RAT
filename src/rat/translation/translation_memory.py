import hashlib
import json


class TranslationMemory:
    @staticmethod
    def key(project_id, source, context, profile, options, glossary):
        payload = {
            "project_id": project_id,
            "text": source.source_text,
            "kind": source.kind.value,
            "context": context,
            "source_language": options.source_language,
            "target_language": options.target_language,
            "style": options.style,
            "glossary": glossary.payload(),
            "provider": profile.provider_id,
            "model": profile.model,
            "base_url": profile.base_url,
            "policy": "protection-v1-strict",
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
