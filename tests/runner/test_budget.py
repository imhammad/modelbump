"""Tests for the budget: limits on tokens and requests, and the spend report."""

import asyncio
import random
from pathlib import Path

import httpx
import pytest

from modelbump.runner import (
    Budget,
    BudgetExceeded,
    ChatRequest,
    ChatResult,
    ResponseCache,
    Runner,
    RunnerError,
)


class Server:
    """Answers with 10 tokens in and 5 out, after the given failures."""

    def __init__(self, *failures: httpx.Response) -> None:
        self.failures = list(failures)
        self.calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.failures:
            return self.failures.pop(0)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": f"a{self.calls}"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )


async def no_wait(seconds: float) -> None:
    return None


def make_runner(
    server: Server, budget: Budget, cache: ResponseCache | None = None, concurrency: int = 1
) -> Runner:
    return Runner(
        transport=httpx.MockTransport(server),
        budget=budget,
        cache=cache,
        concurrency=concurrency,
        sleep=no_wait,
        rng=random.Random(0),
    )


SUITE = [ChatRequest.ask("ollama/m", f"q{i}") for i in range(10)]


def test_without_limits_everything_is_counted() -> None:
    budget = Budget()
    asyncio.run(make_runner(Server(), budget).run_many(SUITE[:3]))
    spend = budget.spend
    assert (spend.requests, spend.answers, spend.input_tokens, spend.output_tokens) == (
        3,
        3,
        30,
        15,
    )
    assert spend.tokens == 45
    assert budget.summary() == (
        "Spent: 3 requests, 45 tokens (30 in, 15 out). From cache: 0 answers (0 tokens saved)."
    )


def test_token_limit_stops_new_requests() -> None:
    server = Server()
    budget = Budget(max_tokens=40)
    outcomes = asyncio.run(make_runner(server, budget).run_each(SUITE))
    # 15 tokens per answer: after 3 answers (45 >= 40) nothing more is sent.
    assert server.calls == 3
    assert [isinstance(o, ChatResult) for o in outcomes] == [True] * 3 + [False] * 7
    assert all(isinstance(o, BudgetExceeded) for o in outcomes[3:])
    assert "45 of 40 tokens used" in str(outcomes[3])
    assert budget.spend.tokens == 45
    assert "Budget used: 112% of 40 tokens." in budget.summary()


def test_request_limit_counts_retries() -> None:
    server = Server(httpx.Response(503, text="busy"), httpx.Response(429, text="slow"))
    budget = Budget(max_requests=4)
    outcomes = asyncio.run(make_runner(server, budget).run_each(SUITE[:3]))
    # 2 failed tries + 1 success for the first, 1 for the second, none left for the third.
    assert server.calls == 4
    assert isinstance(outcomes[0], ChatResult)
    assert outcomes[0].attempts == 3
    assert isinstance(outcomes[1], ChatResult)
    assert isinstance(outcomes[2], BudgetExceeded)
    assert "4 of 4 requests sent" in str(outcomes[2])
    assert "100% of 4 requests" in budget.summary()


def test_run_many_raises_budget_exceeded_after_trying_everything() -> None:
    server = Server()
    with pytest.raises(BudgetExceeded):
        asyncio.run(make_runner(server, Budget(max_requests=2)).run_many(SUITE[:4]))
    assert server.calls == 2
    assert issubclass(BudgetExceeded, RunnerError)


def test_cached_answers_are_free_so_a_rerun_finishes_the_job(tmp_path: Path) -> None:
    cache = ResponseCache(tmp_path / "responses.sqlite")
    server = Server()
    first = Budget(max_requests=6)
    asyncio.run(make_runner(server, first, cache).run_each(SUITE))
    assert server.calls == 6
    # Same limit again: the 6 cached answers cost nothing, 4 new requests finish the suite.
    second = Budget(max_requests=6)
    results = asyncio.run(make_runner(server, second, cache).run_many(SUITE))
    assert len(results) == 10
    assert server.calls == 10
    spend = second.spend
    assert (spend.requests, spend.answers, spend.cached_answers, spend.cached_tokens) == (
        4,
        4,
        6,
        90,
    )
    # A third run is entirely free.
    third = Budget(max_requests=1)
    asyncio.run(make_runner(server, third, cache).run_many(SUITE))
    assert server.calls == 10
    assert third.spend.requests == 0
    assert "From cache: 10 answers (150 tokens saved)." in third.summary()


def test_overshoot_is_limited_to_requests_in_flight() -> None:
    server = Server()

    class SlowTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            await asyncio.sleep(0.01)
            return server(request)

    budget = Budget(max_tokens=20)
    runner = Runner(transport=SlowTransport(), budget=budget, concurrency=3)
    asyncio.run(runner.run_each(SUITE))
    # Three requests start before any answer arrives, then the limit holds.
    assert server.calls == 3
    assert budget.spend.tokens == 45


@pytest.mark.parametrize("limits", [{"max_tokens": 0}, {"max_requests": 0}])
def test_limits_must_be_positive(limits: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        Budget(**limits)
