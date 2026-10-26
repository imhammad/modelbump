"""Tests for the runner, against a fake server (no network, no real waiting)."""

import asyncio
import json
import random
from collections.abc import Callable

import httpx
import pytest

from modelbump.runner import ChatRequest, Runner, RunnerError

Handler = Callable[[httpx.Request], httpx.Response]


def ok(text: str = "hello", prompt_tokens: int = 7, completion_tokens: int = 2) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
        },
    )


class FakeServer:
    """Answers with the given responses in order and records every request."""

    def __init__(self, *responses: httpx.Response | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def make_runner(server: Handler, **options: float | int) -> tuple[Runner, list[float]]:
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    runner = Runner(
        transport=httpx.MockTransport(server),
        sleep=fake_sleep,
        rng=random.Random(0),
        **options,  # type: ignore[arg-type]
    )
    return runner, waits


REQUEST = ChatRequest.ask("ollama/qwen2.5:7b", "Say hello.", "Be brief.", seed=1)


def test_a_successful_call_returns_text_and_tokens() -> None:
    server = FakeServer(ok())
    runner, waits = make_runner(server)
    result = asyncio.run(runner.run(REQUEST))
    assert (result.text, result.input_tokens, result.output_tokens) == ("hello", 7, 2)
    assert (result.attempts, result.finish_reason, result.model) == (1, "stop", REQUEST.model)
    assert waits == []
    sent = server.requests[0]
    assert str(sent.url) == "http://localhost:11434/v1/chat/completions"
    body = json.loads(sent.content)
    assert body["model"] == "qwen2.5:7b"
    assert body["seed"] == 1
    assert body["messages"][0]["role"] == "system"


@pytest.mark.parametrize(
    "failure",
    [
        httpx.Response(429, json={"error": {"message": "slow down"}}),
        httpx.Response(503, text="busy"),
        httpx.ReadTimeout("slow"),
        httpx.ConnectError("refused"),
    ],
)
def test_temporary_failures_are_retried(failure: httpx.Response | Exception) -> None:
    server = FakeServer(failure, failure, ok("finally"))
    runner, waits = make_runner(server)
    result = asyncio.run(runner.run(REQUEST))
    assert result.text == "finally"
    assert result.attempts == 3
    assert len(waits) == 2


def test_backoff_grows_and_stays_under_the_cap() -> None:
    errors = [httpx.Response(500, text="oops") for _ in range(5)]
    runner, waits = make_runner(FakeServer(*errors, ok()), max_attempts=6, max_delay=3.0)
    asyncio.run(runner.run(REQUEST))
    ceilings = [1.0, 2.0, 3.0, 3.0, 3.0]
    assert len(waits) == 5
    assert all(0 <= w <= c for w, c in zip(waits, ceilings, strict=True))


def test_retry_after_header_is_respected_up_to_the_cap() -> None:
    server = FakeServer(
        httpx.Response(429, headers={"Retry-After": "12"}, text="limit"),
        httpx.Response(429, headers={"Retry-After": "99"}, text="limit"),
        httpx.Response(429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}, text="x"),
        ok(),
    )
    runner, waits = make_runner(server, max_delay=30.0)
    asyncio.run(runner.run(REQUEST))
    assert waits[0] >= 12
    assert waits[1] == 30.0
    assert waits[2] <= 4.0  # a date is ignored: normal backoff


def test_gives_up_after_max_attempts() -> None:
    server = FakeServer(*[httpx.ReadTimeout("slow") for _ in range(3)])
    runner, waits = make_runner(server, max_attempts=3, timeout=5)
    with pytest.raises(RunnerError, match=r"timed out after 5s \(gave up after 3 attempts\)"):
        asyncio.run(runner.run(REQUEST))
    assert len(server.requests) == 3
    assert len(waits) == 2


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (
            httpx.Response(404, json={"error": "model 'x' not found"}),
            "HTTP 404: model 'x' not found",
        ),
        (httpx.Response(400, json={"error": {"message": "bad"}}), "HTTP 400: bad"),
        (httpx.Response(401, json={"detail": "no key"}), "HTTP 401: {'detail': 'no key'}"),
        (httpx.Response(403, text=""), "HTTP 403: no body"),
    ],
)
def test_other_client_errors_fail_at_once(response: httpx.Response, message: str) -> None:
    server = FakeServer(response)
    runner, waits = make_runner(server)
    with pytest.raises(RunnerError, match=message.replace("(", r"\(").replace(")", r"\)")):
        asyncio.run(runner.run(REQUEST))
    assert len(server.requests) == 1
    assert waits == []


def test_a_strange_response_is_an_error() -> None:
    runner, _ = make_runner(FakeServer(httpx.Response(200, json={"choices": []})))
    with pytest.raises(RunnerError, match="unexpected response shape"):
        asyncio.run(runner.run(REQUEST))


def test_missing_usage_counts_zero_tokens() -> None:
    response = httpx.Response(200, json={"choices": [{"message": {"content": None}}]})
    runner, _ = make_runner(FakeServer(response))
    result = asyncio.run(runner.run(REQUEST))
    assert (result.text, result.input_tokens, result.finish_reason) == ("", 0, "unknown")


def test_run_many_keeps_order_and_limits_concurrency() -> None:
    in_flight = 0
    most = 0

    class SlowTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            nonlocal in_flight, most
            in_flight += 1
            most = max(most, in_flight)
            await asyncio.sleep(0.01)
            in_flight -= 1
            prompt = json.loads(request.content)["messages"][-1]["content"]
            return ok(prompt.upper())

    runner = Runner(transport=SlowTransport(), concurrency=2)
    prompts = [f"p{i}" for i in range(6)]
    results = asyncio.run(runner.run_many([ChatRequest.ask("ollama/m", p) for p in prompts]))
    assert [r.text for r in results] == [p.upper() for p in prompts]
    assert most == 2


@pytest.mark.parametrize("option", [{"max_attempts": 0}, {"concurrency": 0}])
def test_bad_settings_are_rejected(option: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        Runner(**option)  # type: ignore[arg-type]
