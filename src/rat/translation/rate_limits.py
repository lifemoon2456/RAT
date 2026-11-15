import asyncio
import time
from contextlib import asynccontextmanager


class RateLimitManager:
    def __init__(
        self, concurrency=2, requests_per_minute=30, *, clock=time.monotonic, sleep=asyncio.sleep
    ):
        if concurrency < 1 or requests_per_minute <= 0:
            raise ValueError("Rate limits must be positive.")
        self.semaphore = asyncio.Semaphore(concurrency)
        self.lock = asyncio.Lock()
        self.interval = 60.0 / requests_per_minute
        self.next_request = 0.0
        self.clock, self.sleep = clock, sleep

    @asynccontextmanager
    async def slot(self):
        async with self.semaphore:
            async with self.lock:
                delay = max(0, self.next_request - self.clock())
                if delay:
                    await self.sleep(delay)
                self.next_request = self.clock() + self.interval
            yield
