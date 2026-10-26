"""Send chat requests with a timeout, retries with backoff, and a concurrency limit."""

import asyncio
import random
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import httpx

from modelbump.runner.backends import request_body, resolve_model
from modelbump.runner.types import ChatRequest, ChatResult

# Statuses worth another try: rate limits and server-side failures.
RETRY_STATUSES = frozenset({408, 429, 500, 502, 503, 504})

Sleep = Callable[[float], Awaitable[None]]


class RunnerError(Exception):
    """A call failed for good: a non-retryable error, or every attempt failed."""


class Runner:
    """Calls models. One Runner can be reused for many requests.

    - `timeout`: seconds each attempt may take.
    - `max_attempts`: tries per request, counting the first one.
    - `base_delay`, `max_delay`: exponential backoff with full jitter, in seconds.
      A `Retry-After` header from the server wins when it asks for longer.
    - `concurrency`: requests in flight at once in `run_many`.
    """

    def __init__(
        self,
        *,
        timeout: float = 120.0,
        max_attempts: int = 4,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        concurrency: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
        rng: random.Random | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1.")
        if concurrency < 1:
            raise ValueError("concurrency must be at least 1.")
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.concurrency = concurrency
        self._transport = transport
        self._sleep = sleep
        self._rng = rng or random.Random()

    async def run(self, request: ChatRequest) -> ChatResult:
        """Send one request."""
        async with self._client() as client:
            return await self._run(client, request)

    async def run_many(self, requests: Sequence[ChatRequest]) -> list[ChatResult]:
        """Send many requests, at most `concurrency` at a time. Results keep the input order."""
        gate = asyncio.Semaphore(self.concurrency)
        async with self._client() as client:

            async def one(request: ChatRequest) -> ChatResult:
                async with gate:
                    return await self._run(client, request)

            return list(await asyncio.gather(*(one(r) for r in requests)))

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self.timeout, transport=self._transport)

    async def _run(self, client: httpx.AsyncClient, request: ChatRequest) -> ChatResult:
        endpoint, model_name = resolve_model(request.model)
        url = f"{endpoint.base_url}/chat/completions"
        body = request_body(request, model_name)
        headers = endpoint.headers()
        start = time.monotonic()
        for attempt in range(1, self.max_attempts + 1):
            wait: float | None = None
            try:
                response = await client.post(url, json=body, headers=headers)
            except httpx.TimeoutException:
                reason = f"timed out after {self.timeout:g}s"
            except httpx.TransportError as error:
                reason = f"could not reach {endpoint.base_url} ({type(error).__name__})"
            else:
                if response.status_code == 200:
                    return _parse(response.json(), request.model, attempt, time.monotonic() - start)
                reason = f"HTTP {response.status_code}: {_error_text(response)}"
                if response.status_code not in RETRY_STATUSES:
                    raise RunnerError(f"{request.model}: {reason}")
                wait = _retry_after(response)
            if attempt == self.max_attempts:
                raise RunnerError(f"{request.model}: {reason} (gave up after {attempt} attempts)")
            await self._sleep(self._backoff(attempt, wait))
        raise AssertionError("unreachable")  # pragma: no cover

    def _backoff(self, attempt: int, retry_after: float | None) -> float:
        """Full jitter: a random wait up to base * 2^(attempt-1), capped at max_delay."""
        ceiling = min(self.max_delay, self.base_delay * 2 ** (attempt - 1))
        delay = self._rng.uniform(0, ceiling)
        if retry_after is not None:
            delay = max(delay, min(retry_after, self.max_delay))
        return delay


def _parse(data: dict[str, Any], model: str, attempts: int, seconds: float) -> ChatResult:
    try:
        choice = data["choices"][0]
        text = choice["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as error:
        raise RunnerError(f"{model}: unexpected response shape: {data!r:.200}") from error
    usage = data.get("usage") or {}
    return ChatResult(
        text=text,
        model=model,
        input_tokens=int(usage.get("prompt_tokens", 0)),
        output_tokens=int(usage.get("completion_tokens", 0)),
        finish_reason=str(choice.get("finish_reason") or "unknown"),
        attempts=attempts,
        seconds=seconds,
    )


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None  # an HTTP date; fall back to our own backoff


def _error_text(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text[:200] or "no body"
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        return str(error.get("message", error))[:200]
    if error is not None:
        return str(error)[:200]
    return str(data)[:200]
