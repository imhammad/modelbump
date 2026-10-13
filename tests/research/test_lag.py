"""Tests for how long before or after the shutdown projects migrate."""

import json
import math
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from research.analysis.lag import (
    Spread,
    finite,
    main,
    median_ci,
    notice_days,
    quantile,
    run,
    window,
)


def row(
    days: int,
    provider: str = "openai",
    model_id: str = "old-1",
    repo: str = "a/b",
    notice: str | None = "2026-03-01",
    shutdown: str = "2026-06-01",
) -> dict[str, Any]:
    committed = date.fromordinal(date.fromisoformat(shutdown).toordinal() + days)
    if days >= 0:
        phase = "after_shutdown"
    elif notice is None:
        phase = "no_notice"
    else:
        phase = "after_notice" if committed.isoformat() >= notice else "before_notice"
    return {
        "sha": f"{repo}-{model_id}-{days}",
        "repo": repo,
        "committed": committed.isoformat(),
        "model_id": model_id,
        "provider": provider,
        "notice": notice,
        "shutdown": shutdown,
        "phase": phase,
        "days_from_shutdown": days,
    }


def test_quantile() -> None:
    assert quantile([1, 2, 3, 4], 0.5) == 2.5
    assert quantile([1, 2, 3, 4], 0.25) == 1.75
    assert quantile([7], 0.75) == 7
    assert math.isnan(quantile([], 0.5))


def test_median_ci_contains_the_median_and_narrows() -> None:
    small = list(range(20))
    low, high = median_ci(small)
    assert low <= quantile(small, 0.5) <= high
    big = list(range(2000))
    big_low, big_high = median_ci(big)
    assert (big_high - big_low) / len(big) < (high - low) / len(small)
    assert median_ci([5]) == (5, 5)
    assert all(math.isnan(v) for v in median_ci([]))


def test_spread() -> None:
    spread = Spread.of([4, 1, 3, 2])
    assert spread.n == 4
    assert spread.median == 2.5
    assert (spread.q1, spread.q3) == (1.75, 3.25)


@pytest.mark.parametrize(
    ("days", "expected"),
    [
        (-400, "more than 180 days before"),
        (-181, "more than 180 days before"),
        (-180, "91 to 180 days before"),
        (-1, "1 to 30 days before"),
        (0, "0 to 30 days after"),
        (90, "31 to 90 days after"),
        (365, "181 to 365 days after"),
        (366, "more than 365 days after"),
    ],
)
def test_window(days: int, expected: str) -> None:
    assert window(days) == expected


def test_notice_days() -> None:
    assert notice_days(row(0)) == 92
    assert notice_days(row(0, notice=None)) is None


def test_run_groups_and_models() -> None:
    timing = [
        row(-100),  # before the notice
        row(-10),  # after the notice
        row(5, repo="c/d"),
        row(40, repo="c/d"),
        row(-30, provider="anthropic", model_id="old-a", repo="e/f"),
        row(-5, provider="google", model_id="gem-1", notice=None),
        row(10, model_id="late", shutdown="2026-12-01"),  # shut down after the end
    ]
    stats = run(timing, retired_by=date(2026, 9, 1), minimum=2)
    assert stats.retired_by == "2026-09-01"
    assert stats.rows == 6
    both = stats.groups["openai+anthropic"]
    assert both.days_from_shutdown.n == 5
    assert both.days_from_shutdown.median == -10  # median of -100, -30, -10, 5, 40
    assert both.after_shutdown.n == 2
    assert both.first_per_repo.n == 3
    assert both.windows["91 to 180 days before"] == 1
    assert both.notice_period.n == 2
    assert both.notice_used.n == 2  # -10 and -30 fall in the notice period
    assert stats.groups["google"].notice_period.n == 0
    assert [m.model_id for m in stats.models] == ["old-1"]
    assert stats.models[0].commits == 4
    assert stats.models[0].after_shutdown == 0.5


def test_run_defaults_to_the_last_commit_day() -> None:
    stats = run([row(-10), row(3)])
    assert stats.retired_by == "2026-06-04"
    assert stats.rows == 2


def test_finite() -> None:
    assert finite({"a": [math.nan, 1.0], "b": "x"}) == {"a": [None, 1.0], "b": "x"}


def test_main(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    timing = tmp_path / "timing.jsonl"
    rows = [row(-10), row(5), row(30, provider="google", model_id="gem-1", notice=None)]
    timing.write_text("".join(json.dumps(r) + "\n" for r in rows))
    out = tmp_path / "lag.stats.json"
    assert main(["--timing", str(timing), "--out", str(out), "--min-commits", "1"]) == 0
    stats = json.loads(out.read_text())
    assert stats["rows"] == 3
    assert stats["groups"]["google"]["notice_used"]["median"] is None
    printed = capsys.readouterr().out
    assert "median (95% CI)" in printed
    assert "Models with the most migrations" in printed


def test_main_without_input(tmp_path: Path) -> None:
    assert main(["--timing", str(tmp_path / "missing.jsonl")]) == 1
    timing = tmp_path / "timing.jsonl"
    timing.write_text(json.dumps(row(5, shutdown="2027-01-01")) + "\n")
    assert main(["--timing", str(timing), "--retired-by", "2026-01-01"]) == 1
