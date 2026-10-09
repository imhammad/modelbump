"""Tests for the miner: time slicing, forks, duplicates and the command line."""

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from modelbump.registry import load_registry
from research.mining.github_search import CommitSearchClient
from research.mining.miner import (
    SKIPPED_IDS,
    MiningStats,
    Window,
    build_query,
    main,
    mentions,
    mine,
    model_ids_to_search,
    search_window,
)
from tests.research.fake_github import FakeGitHub, make_item

JANUARY = Window(date(2026, 1, 1), date(2026, 1, 31))


def make_client(tmp_path: Path, fake: FakeGitHub) -> CommitSearchClient:
    return CommitSearchClient(
        tmp_path / "cache", transport=fake.transport(), sleep=lambda _: None, min_interval=0
    )


def test_window_split_covers_every_day_once() -> None:
    left, right = JANUARY.split()
    assert left == Window(date(2026, 1, 1), date(2026, 1, 16))
    assert right == Window(date(2026, 1, 17), date(2026, 1, 31))
    assert not Window(date(2026, 1, 1), date(2026, 1, 1)).can_split()


def test_build_query_quotes_the_id() -> None:
    assert build_query("gpt-4", JANUARY) == '"gpt-4" committer-date:2026-01-01..2026-01-31'


def test_reads_every_page(tmp_path: Path) -> None:
    commits = [("model-a", make_item(f"s{i}", "model-a", date(2026, 1, 10))) for i in range(250)]
    fake = FakeGitHub(commits)
    stats = MiningStats()
    items = list(search_window(make_client(tmp_path, fake), "model-a", JANUARY, stats))
    assert len(items) == 250
    assert [page for _, page in fake.calls] == [1, 2, 3]


def test_splits_windows_over_the_cap(tmp_path: Path) -> None:
    # 1,200 commits spread over January: more than one search can return.
    commits = [
        ("model-a", make_item(f"s{i}", "model-a", date(2026, 1, 1) + timedelta(days=i % 31)))
        for i in range(1200)
    ]
    fake = FakeGitHub(commits)
    stats = MiningStats()
    items = list(search_window(make_client(tmp_path, fake), "model-a", JANUARY, stats))
    assert len({i["sha"] for i in items}) == 1200
    assert stats.truncated_windows == []


def test_records_a_truncated_single_day(tmp_path: Path) -> None:
    commits = [("model-a", make_item(f"s{i}", "model-a", date(2026, 1, 5))) for i in range(1100)]
    fake = FakeGitHub(commits)
    stats = MiningStats()
    items = list(search_window(make_client(tmp_path, fake), "model-a", JANUARY, stats))
    assert len(items) == 1000
    assert stats.truncated_windows == ['"model-a" committer-date:2026-01-05..2026-01-05']


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Migrate from gpt-4 to gpt-5.6-sol", True),
        ("Drop GPT-4.", True),
        ("model: 'gpt-4'", True),
        ("Switch to gpt-4o", False),
        ("Use gpt-4-turbo", False),
        ("Use gpt-4.1 now", False),
        ("Bump my-gpt-4 helper", False),
    ],
)
def test_mentions_whole_id_only(message: str, expected: bool) -> None:
    assert mentions(message, "gpt-4") is expected


def test_mine_drops_results_without_the_id(tmp_path: Path) -> None:
    # Real case: searching claude-3-haiku-20240307 returned a spam commit whose
    # SHA starts with 20240307 but whose message never mentions the model.
    noise = make_item("20240307e02c", "something-else", date(2026, 1, 3))
    fake = FakeGitHub(
        [("model-a", noise), ("model-a", make_item("a1", "model-a", date(2026, 1, 4)))]
    )
    candidates, stats = mine(make_client(tmp_path, fake), [("openai", "model-a")], JANUARY)
    assert [c.sha for c in candidates] == ["a1"]
    assert stats.not_in_message == 1


def test_same_commit_in_many_repos_is_kept_once(tmp_path: Path) -> None:
    # Real case: one commit pushed to many non-fork copies of a repository.
    fake = FakeGitHub(
        [
            ("model-a", make_item("s1", "model-a", date(2026, 1, 3), repo=f"user{i}/app"))
            for i in range(3)
        ]
    )
    candidates, stats = mine(make_client(tmp_path, fake), [("openai", "model-a")], JANUARY)
    [candidate] = candidates
    assert candidate.repos == ["user0/app", "user1/app", "user2/app"]
    assert stats.duplicates == 2
    assert stats.copies_in_other_repos == 2


def test_mine_skips_forks_and_merges_duplicates(tmp_path: Path) -> None:
    shared = make_item("both", "model-a and model-b", date(2026, 1, 3))
    fake = FakeGitHub(
        [
            ("model-a", shared),
            ("model-b", shared),
            ("model-a", make_item("fork1", "model-a", date(2026, 1, 4), fork=True)),
            ("model-b", make_item("b1", "model-b", date(2026, 1, 2))),
        ]
    )
    targets = [("openai", "model-a"), ("anthropic", "model-b")]
    lines: list[str] = []
    candidates, stats = mine(make_client(tmp_path, fake), targets, JANUARY, lines.append)
    assert lines == ["[1/2] model-a", "[2/2] model-b"]
    assert [c.sha for c in candidates] == ["b1", "both"]  # sorted by date
    assert candidates[1].matched_ids == ["model-a", "model-b"]
    assert candidates[1].providers == ["openai", "anthropic"]
    assert stats.forks_skipped == 1
    assert stats.duplicates == 1
    assert stats.items_seen == 4


def test_targets_include_aliases_but_skip_common_words() -> None:
    targets = {model_id for _, model_id in model_ids_to_search(load_registry())}
    assert "gpt-4" in targets  # alias of gpt-4-0613
    assert "o1-2024-12-17" in targets
    assert targets.isdisjoint(SKIPPED_IDS)


def test_only_limits_the_targets() -> None:
    assert model_ids_to_search(load_registry(), ["claude-2.1"]) == [("anthropic", "claude-2.1")]


def test_main_writes_candidates_and_stats(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeGitHub([("claude-2.1", make_item("c1", "claude-2.1", date(2025, 3, 1)))])
    out = tmp_path / "candidates.jsonl"
    code = main(
        ["--only", "claude-2.1", "--start", "2025-01-01", "--end", "2025-12-31", "--out", str(out)],
        client=make_client(tmp_path, fake),
    )
    assert code == 0
    [line] = out.read_text().splitlines()
    assert json.loads(line)["sha"] == "c1"
    stats = json.loads(out.with_suffix(".stats.json").read_text())
    assert stats["start"] == "2025-01-01"
    assert "Candidates written:  1" in capsys.readouterr().out


def test_main_needs_a_token(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert main(["--only", "claude-2.1"]) == 1
    assert "GITHUB_TOKEN" in capsys.readouterr().err
