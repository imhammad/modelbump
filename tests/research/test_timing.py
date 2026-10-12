"""Tests for placing migration commits on the retirement timeline."""

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from modelbump.registry import (
    EarlierPlan,
    Provider,
    ProviderFile,
    Registry,
    RetiredModel,
    load_registry,
)
from research.enrichment.timing import (
    first_per_repo,
    left_model,
    main,
    notice,
    phase,
    run,
    timing_row,
)

OLD = RetiredModel(id="old-1", announced=date(2026, 3, 1), shutdown=date(2026, 6, 1))
RESCHEDULED = RetiredModel(
    id="old-2",
    announced=date(2026, 4, 1),
    shutdown=date(2026, 9, 1),
    superseded=(EarlierPlan(announced=date(2025, 12, 1), shutdown=date(2026, 3, 1)),),
)
GOOGLE = RetiredModel(id="gem-1", shutdown=date(2026, 5, 1), shutdown_is_earliest=True)


def registry() -> Registry:
    def source(provider: Provider, *models: RetiredModel) -> ProviderFile:
        return ProviderFile(
            provider=provider,
            source_url="https://example.com/deprecations",  # type: ignore[arg-type]
            retrieved=date(2026, 10, 8),
            models=models,
        )

    return Registry([source(Provider.OPENAI, OLD, RESCHEDULED), source(Provider.GOOGLE, GOOGLE)])


def commit(
    message: str, day: str, ids: tuple[str, ...] = ("old-1",), repo: str = "acme/app"
) -> dict[str, Any]:
    return {
        "sha": f"{repo}-{day}-{message[:6]}",
        "repo": repo,
        "url": "https://github.com/acme/app/commit/x",
        "committed_at": f"{day}T12:00:00Z",
        "message": message,
        "matched_ids": list(ids),
        "migration_away": True,
    }


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 2, 28), "before_notice"),
        (date(2026, 3, 1), "after_notice"),
        (date(2026, 5, 31), "after_notice"),
        (date(2026, 6, 1), "after_shutdown"),
    ],
)
def test_phase(day: date, expected: str) -> None:
    assert phase(day, OLD) == expected


def test_phase_without_a_notice_date() -> None:
    assert phase(date(2026, 4, 1), GOOGLE) == "no_notice"
    assert phase(date(2026, 5, 1), GOOGLE) == "after_shutdown"


def test_notice_counts_rescheduled_plans() -> None:
    assert notice(RESCHEDULED) == date(2025, 12, 1)
    assert notice(GOOGLE) is None
    assert phase(date(2026, 1, 1), RESCHEDULED) == "after_notice"


def test_left_model_prefers_the_model_moved_away_from() -> None:
    row = commit(
        "Switch from old-2 to new-9, keep old-1 for tests", "2026-07-01", ("old-1", "old-2")
    )
    assert left_model(row, registry()) == ("old-2", "openai", RESCHEDULED)


def test_left_model_falls_back_to_the_first_shut_down() -> None:
    row = commit("Update models old-2 and old-1", "2026-07-01", ("old-2", "old-1"))
    model = left_model(row, registry())
    assert model is not None and model[0] == "old-1"
    assert left_model(commit("x", "2026-07-01", ("unknown-model",)), registry()) is None


def test_timing_row() -> None:
    row = timing_row(commit("Migrate from old-1 to new-1", "2026-06-11"), registry())
    assert row is not None
    assert row["phase"] == "after_shutdown"
    assert row["days_from_shutdown"] == 10
    assert row["notice"] == "2026-03-01"
    assert row["in_kim_window"] is True
    google = timing_row(commit("from gem-1 to gem-2", "2026-04-01", ("gem-1",)), registry())
    assert google is not None
    assert google["in_kim_window"] is None and google["shutdown_is_earliest"]


def test_first_per_repo() -> None:
    rows = [
        {"repo": "a/b", "model_id": "old-1", "committed": "2026-07-01", "sha": "2"},
        {"repo": "a/b", "model_id": "old-1", "committed": "2026-05-01", "sha": "1"},
        {"repo": "c/d", "model_id": "old-1", "committed": "2026-06-01", "sha": "3"},
    ]
    assert [r["sha"] for r in first_per_repo(rows)] == ["1", "3"]


def test_run_counts_and_headline() -> None:
    labeled = [
        commit("from old-1 to new-1", "2026-01-01"),  # before notice, outside Kim's window
        commit("from old-1 to new-1", "2026-04-01", repo="b/b"),  # after notice
        commit("from old-1 to new-1", "2026-06-02", repo="c/c"),  # after shutdown
        commit("from old-1 to new-1", "2026-06-20", repo="c/c"),  # same repo, later
        commit("from old-2 to new-2", "2026-08-01", ("old-2",)),  # not shut down by the end
        commit("from gem-1 to gem-2", "2026-05-02", ("gem-1",)),
        commit("from gem-1 to gem-2", "2026-04-02", ("gem-1",)),
        commit("unknown", "2026-04-02", ("mystery-1",)),
        {**commit("from old-1 to new-1", "2026-07-01"), "migration_away": False},
    ]
    rows, stats = run(labeled, registry())
    assert stats.commits == 8
    assert stats.not_in_registry == 1
    assert len(rows) == 7
    assert stats.retired_by == "2026-08-01"
    assert stats.phases["openai"]["after_notice"] == 2  # old-2 counts here
    assert stats.phases_retired["openai"] == {
        "before_notice": 1,
        "after_notice": 1,
        "after_shutdown": 2,
        "no_notice": 0,
    }
    assert stats.phases_retired["google"]["no_notice"] == 1
    headline = stats.headline
    assert (headline["exact_dates"].after, headline["exact_dates"].total) == (2, 4)
    assert headline["exact_dates_kim_window"].total == 3
    assert headline["exact_dates_first_per_repo"].after == 1
    assert headline["exact_dates_first_per_repo"].total == 3
    assert headline["google_earliest_dates"].share == 0.5


def test_run_retired_by() -> None:
    labeled = [commit("from old-1 to new-1", "2026-06-02")]
    _, stats = run(labeled, registry(), retired_by=date(2026, 5, 1))
    assert stats.headline["exact_dates"].total == 0
    assert stats.headline["exact_dates"].share == 0.0


def test_main(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    model = load_registry().get("claude-sonnet-4-20250514")
    assert model is not None and model[1].shutdown == date(2026, 6, 15)
    rows = [
        commit("Switch from claude-sonnet-4-20250514 to claude-sonnet-4-6", day, ids=(i,))
        for day, i in [
            ("2026-06-20", "claude-sonnet-4-20250514"),
            ("2026-05-01", "claude-sonnet-4-20250514"),
        ]
    ]
    labeled = tmp_path / "labeled.jsonl"
    labeled.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    out = tmp_path / "timing.jsonl"
    assert main(["--labeled", str(labeled), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "OpenAI + Anthropic (exact dates)" in printed
    assert "1 of        2 =  50.0%" in printed
    assert "Kim (2026)" in printed and "82.0%" in printed
    stats = json.loads(out.with_suffix(".stats.json").read_text(encoding="utf-8"))
    assert stats["headline"]["exact_dates"] == {"after": 1, "total": 2}
    assert len(out.read_text(encoding="utf-8").splitlines()) == 2


def test_main_needs_labels(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--labeled", str(tmp_path / "missing.jsonl")]) == 1
    assert "Run research.filtering.filter first" in capsys.readouterr().err
    empty = tmp_path / "labeled.jsonl"
    empty.write_text(json.dumps({**commit("x", "2026-01-01"), "migration_away": False}) + "\n")
    assert main(["--labeled", str(empty), "--out", str(tmp_path / "t.jsonl")]) == 1
    assert "No commits are labelled" in capsys.readouterr().err
