"""Tests for the response cache."""

import asyncio
import dataclasses
import random
from pathlib import Path

import httpx
import pytest

from modelbump.runner import (
    ChatRequest,
    ChatResult,
    Message,
    ResponseCache,
    Runner,
    RunnerError,
    cache_key,
    default_cache_path,
)

BASE = ChatRequest.ask("ollama/qwen2.5:7b", "Name a fruit.", "Be brief.", seed=1)


def answer(text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 9, "completion_tokens": 4},
        },
    )


class CountingServer:
    """Answers every request and counts how many reached it."""

    def __init__(self, response: httpx.Response | None = None) -> None:
        self.calls = 0
        self.response = response

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        return self.response or answer(f"answer {self.calls}")


async def no_wait(seconds: float) -> None:
    return None


def runner_with(server: CountingServer, cache: ResponseCache | None) -> Runner:
    return Runner(
        transport=httpx.MockTransport(server),
        cache=cache,
        sleep=no_wait,
        rng=random.Random(0),
        max_attempts=2,
    )


@pytest.fixture
def cache(tmp_path: Path) -> ResponseCache:
    return ResponseCache(tmp_path / "c" / "responses.sqlite")


def test_the_key_is_stable_and_covers_everything_that_changes_an_answer() -> None:
    key = cache_key(BASE)
    assert key == cache_key(
        ChatRequest.ask("ollama/qwen2.5:7b", "Name a fruit.", "Be brief.", seed=1)
    )
    assert len(key) == 64
    changed = [
        ChatRequest.ask("ollama/qwen3:8b", "Name a fruit.", "Be brief.", seed=1),
        ChatRequest.ask("ollama/qwen2.5:7b", "Name a fruit!", "Be brief.", seed=1),
        ChatRequest.ask("ollama/qwen2.5:7b", "Name a fruit.", "Be short.", seed=1),
        ChatRequest.ask("ollama/qwen2.5:7b", "Name a fruit.", seed=1),
        ChatRequest.ask("ollama/qwen2.5:7b", "Name a fruit.", "Be brief.", seed=2),
        ChatRequest.ask("ollama/qwen2.5:7b", "Name a fruit.", "Be brief.", seed=1, temperature=0.7),
        ChatRequest.ask("ollama/qwen2.5:7b", "Name a fruit.", "Be brief.", seed=1, max_tokens=5),
        ChatRequest.ask("ollama/qwen2.5:7b", "Name a fruit.", "Be brief.", seed=1, sample=1),
        ChatRequest.ask(
            "ollama/qwen2.5:7b", "Name a fruit.", "Be brief.", seed=1, reasoning_effort="none"
        ),
        dataclasses.replace(BASE, model_version="845dbda0ea48"),
        # Same text, different roles.
        ChatRequest(
            "ollama/qwen2.5:7b",
            (Message("user", "Be brief."), Message("user", "Name a fruit.")),
            seed=1,
        ),
    ]
    keys = {cache_key(r) for r in changed}
    assert key not in keys
    assert len(keys) == len(changed)


def test_get_returns_none_until_put(cache: ResponseCache) -> None:
    assert cache.get(BASE) is None
    cache.put(BASE, ChatResult("Apple.", BASE.model, 9, 2, "stop", 2, 1.5))
    found = cache.get(BASE)
    assert found == ChatResult("Apple.", BASE.model, 9, 2, "stop", 0, 0.0, cached=True)


def test_answers_survive_closing_and_reopening(tmp_path: Path) -> None:
    path = tmp_path / "responses.sqlite"
    first = ResponseCache(path)
    first.put(BASE, ChatResult("Pear.", BASE.model, 9, 2, "stop", 1, 0.3))
    first.close()
    second = ResponseCache(path)
    found = second.get(BASE)
    assert found is not None
    assert found.text == "Pear."


def test_running_the_same_suite_twice_calls_the_model_once(cache: ResponseCache) -> None:
    server = CountingServer()
    suite = [ChatRequest.ask("ollama/m", f"q{i}") for i in range(5)]
    first = asyncio.run(runner_with(server, cache).run_many(suite))
    second = asyncio.run(runner_with(server, cache).run_many(suite))
    assert server.calls == 5
    assert [r.text for r in first] == [r.text for r in second]
    assert not any(r.cached for r in first)
    assert all(r.cached and r.attempts == 0 for r in second)


def test_each_sample_number_is_its_own_entry(cache: ResponseCache) -> None:
    server = CountingServer()
    draws = [ChatRequest.ask("ollama/m", "q", temperature=0.8, sample=k) for k in range(3)]
    texts = [r.text for r in asyncio.run(runner_with(server, cache).run_many(draws))]
    assert len(set(texts)) == 3
    asyncio.run(runner_with(server, cache).run_many(draws))
    assert server.calls == 3


def test_failures_are_not_cached(cache: ResponseCache) -> None:
    server = CountingServer(httpx.Response(503, text="busy"))
    runner = runner_with(server, cache)
    with pytest.raises(RunnerError):
        asyncio.run(runner.run(BASE))
    assert cache.get(BASE) is None
    assert server.calls == 2


def test_without_a_cache_every_run_calls_the_model() -> None:
    server = CountingServer()
    runner = runner_with(server, None)
    asyncio.run(runner.run(BASE))
    asyncio.run(runner.run(BASE))
    assert server.calls == 2


def test_stats_and_clear(cache: ResponseCache) -> None:
    empty = cache.stats()
    assert (empty.entries, empty.output_tokens) == (0, 0)
    cache.put(BASE, ChatResult("A", BASE.model, 9, 4, "stop", 1, 0.1))
    other = ChatRequest.ask("ollama/m", "other")
    cache.put(other, ChatResult("B", other.model, 3, 6, "stop", 1, 0.1))
    stats = cache.stats()
    assert (stats.entries, stats.output_tokens) == (2, 10)
    assert stats.size_bytes > 0
    assert cache.clear() == 2
    assert cache.get(BASE) is None


def test_default_path_follows_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MODELBUMP_CACHE_DIR", str(tmp_path / "mine"))
    assert default_cache_path() == tmp_path / "mine" / "responses.sqlite"
    monkeypatch.delenv("MODELBUMP_CACHE_DIR")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    assert default_cache_path() == tmp_path / "xdg" / "modelbump" / "responses.sqlite"
    monkeypatch.delenv("XDG_CACHE_HOME")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert default_cache_path() == tmp_path / "home" / ".cache" / "modelbump" / "responses.sqlite"
