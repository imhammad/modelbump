"""Tests for the commit-search client: caching and rate limits."""

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from research.mining.github_search import USER_AGENT, CommitSearchClient, RateLimitError
from tests.research.fake_github import FakeGitHub, make_item

QUERY = '"model-a" committer-date:2026-01-01..2026-01-31'


class FakeClock:
    """A clock that only moves when the code under test sleeps."""

    def __init__(self) -> None:
        self.now = 1_000.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def make_client(tmp_path: Path, fake: FakeGitHub, clock: FakeClock) -> CommitSearchClient:
    return CommitSearchClient(
        tmp_path / "cache",
        "test-token",
        transport=fake.transport(),
        sleep=clock.sleep,
        clock=clock.time,
    )


@pytest.fixture
def fake() -> FakeGitHub:
    return FakeGitHub([("model-a", make_item("a1", "model-a", date(2026, 1, 5)))])


def test_second_search_comes_from_cache(tmp_path: Path, fake: FakeGitHub) -> None:
    clock = FakeClock()
    client = make_client(tmp_path, fake, clock)
    first = client.search(QUERY)
    second = client.search(QUERY)
    assert first == second
    assert len(fake.calls) == 1
    assert client.cache_hits == 1


def test_cache_survives_a_new_client(tmp_path: Path, fake: FakeGitHub) -> None:
    clock = FakeClock()
    make_client(tmp_path, fake, clock).search(QUERY)
    make_client(tmp_path, fake, clock).search(QUERY)
    assert len(fake.calls) == 1


def test_cache_file_records_query_and_time(tmp_path: Path, fake: FakeGitHub) -> None:
    make_client(tmp_path, fake, FakeClock()).search(QUERY)
    [path] = (tmp_path / "cache").glob("*.json")
    record = json.loads(path.read_text())
    assert record["query"] == QUERY
    assert record["page"] == 1
    assert "fetched_at" in record
    assert record["response"]["total_count"] == 1


def test_requests_are_spaced_out(tmp_path: Path, fake: FakeGitHub) -> None:
    clock = FakeClock()
    client = make_client(tmp_path, fake, clock)
    client.search(QUERY, 1)
    client.search(QUERY, 2)
    assert clock.sleeps == [pytest.approx(6.0)]


def test_waits_for_retry_after(tmp_path: Path, fake: FakeGitHub) -> None:
    fake.refusals.append(httpx.Response(429, headers={"retry-after": "300"}))
    clock = FakeClock()
    result = make_client(tmp_path, fake, clock).search(QUERY)
    assert result["total_count"] == 1
    assert 300.0 in clock.sleeps


def test_repeated_refusals_wait_longer_each_time(tmp_path: Path, fake: FakeGitHub) -> None:
    # Real case: GitHub said "retry-after: 60" every time, and retrying every
    # minute kept the secondary limit active for over half an hour.
    fake.refusals += [
        httpx.Response(403, headers={"retry-after": "60"}, json={"message": "secondary rate limit"})
        for _ in range(3)
    ]
    clock = FakeClock()
    make_client(tmp_path, fake, clock).search(QUERY)
    waits = [s for s in clock.sleeps if s >= 60]
    assert waits == [60.0, 120.0, 240.0]


def test_waits_until_rate_limit_reset(tmp_path: Path, fake: FakeGitHub) -> None:
    clock = FakeClock()
    reset = str(int(clock.now) + 45)
    fake.refusals.append(
        httpx.Response(403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": reset})
    )
    make_client(tmp_path, fake, clock).search(QUERY)
    assert 46.0 in clock.sleeps


def secondary_limit() -> httpx.Response:
    return httpx.Response(403, json={"message": "You have exceeded a secondary rate limit."})


def test_backs_off_without_headers(tmp_path: Path, fake: FakeGitHub) -> None:
    fake.refusals += [secondary_limit(), secondary_limit()]
    clock = FakeClock()
    make_client(tmp_path, fake, clock).search(QUERY)
    assert clock.sleeps[-2:] == [60.0, 120.0]


def test_gives_up_after_max_retries(tmp_path: Path, fake: FakeGitHub) -> None:
    fake.refusals += [secondary_limit() for _ in range(10)]
    with pytest.raises(RateLimitError):
        make_client(tmp_path, fake, FakeClock()).search(QUERY)


def test_other_errors_are_raised(tmp_path: Path, fake: FakeGitHub) -> None:
    fake.refusals.append(httpx.Response(422, json={"message": "Validation Failed"}))
    with pytest.raises(httpx.HTTPStatusError):
        make_client(tmp_path, fake, FakeClock()).search(QUERY)


def test_other_403_is_not_retried(tmp_path: Path, fake: FakeGitHub) -> None:
    # For example a bad token: waiting would not help, so fail at once.
    fake.refusals.append(httpx.Response(403, json={"message": "Resource not accessible"}))
    clock = FakeClock()
    with pytest.raises(httpx.HTTPStatusError):
        make_client(tmp_path, fake, clock).search(QUERY)
    assert clock.sleeps == []


def test_sends_a_named_user_agent(tmp_path: Path, fake: FakeGitHub) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["user-agent"])
        return fake.handler(request)

    client = CommitSearchClient(
        tmp_path / "cache", transport=httpx.MockTransport(handler), sleep=lambda _: None
    )
    client.search(QUERY)
    assert seen == [USER_AGENT]


def test_wait_message_shows_github_reason(
    tmp_path: Path, fake: FakeGitHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.refusals.append(secondary_limit())
    make_client(tmp_path, fake, FakeClock()).search(QUERY)
    err = capsys.readouterr().err
    assert "403: You have exceeded a secondary rate limit" in err
    assert "waiting 1 min" in err
