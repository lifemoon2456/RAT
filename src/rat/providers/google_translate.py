import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from rat.domain.translation import ProviderConfig
from rat.providers.base import BaseTranslationProvider, ProviderError
from rat.providers.structured import parse_response


class GoogleTranslateProvider(BaseTranslationProvider):
    """Unofficial deep-translator route, not Google Cloud Translation."""

    provider_id = "google_translate"

    def __init__(self, config: ProviderConfig):
        self.config = config

    async def translate_batch(self, items, *, source_language, target_language, context, settings):
        with tempfile.TemporaryDirectory(prefix="rat-google-") as directory:
            input_path, output_path = (
                Path(directory) / "input.json",
                Path(directory) / "output.json",
            )
            input_path.write_text(
                json.dumps({"items": items, "source": source_language, "target": target_language}),
                encoding="utf-8",
            )
            command = (
                [sys.executable, "--google-worker"]
                if getattr(sys, "frozen", False)
                else [sys.executable, "-m", "rat.providers.google_worker"]
            )
            process = await asyncio.create_subprocess_exec(
                *command,
                str(input_path),
                str(output_path),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
            )
            try:
                await asyncio.wait_for(process.wait(), timeout=self.config.timeout_seconds)
            except TimeoutError:
                raise ProviderError("timeout", retryable=True) from None
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
            if (
                process.returncode
                or not output_path.is_file()
                or output_path.stat().st_size > 2_000_000
            ):
                raise ProviderError("google_failed")
            raw = output_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if "error" in data:
                raise ProviderError(data["error"], retryable=data["error"] == "rate_limit")
            return parse_response(raw, items, self.provider_id)
