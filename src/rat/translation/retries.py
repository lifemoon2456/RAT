import asyncio
import random

from rat.providers.base import ProviderError


class RetryManager:
    def __init__(
        self,
        max_attempts=4,
        *,
        base_delay=1.0,
        max_delay=60.0,
        sleep=asyncio.sleep,
        jitter=random.random,
    ):
        self.max_attempts = max_attempts
        self.base_delay, self.max_delay = base_delay, max_delay
        self.sleep, self.jitter = sleep, jitter

    async def run(self, operation, *, on_error=None):
        for attempt in range(self.max_attempts):
            try:
                return await operation()
            except ProviderError as error:
                if on_error:
                    on_error(error)
                if not error.retryable or attempt + 1 == self.max_attempts:
                    raise
                delay = min(self.max_delay, self.base_delay * 2**attempt) + self.jitter()
                await self.sleep(max(delay, error.retry_after or 0))
        raise RuntimeError("Unreachable retry state")
