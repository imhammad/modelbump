"""Tests for labeling candidates and the funnel counts."""

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from research.filtering.filter import label, main, run

STARTS = {"gpt-4": date(2026, 3, 23)}


def candidate(
    message: str, day: str = "2026-05-01", ids: tuple[str, ...] = ("gpt-4",)
) -> dict[str, Any]:
    return {
        "sha": message[:8],
        "repo": "acme/app",
        "repos": ["acme/app"],
        "url": "https://github.com/acme/app/commit/x",
        "committed_at": f"{day}T12:00:00Z",
        "message": message,
        "matched_ids": list(ids),
        "providers": ["google" if ids[0].startswith("gemini") else "openai"],
    }


def test_label_a_clear_migration() -> None:
    row = label(candidate("Migrate from gpt-4 to gpt-5.6-sol"), STARTS)
    assert row["migration"] and row["migration_strict"]
    assert row["direction"] == "away"
    assert row["after_notice_start"] is True
    assert not row["migration_with_ai"]


@pytest.mark.parametrize(
    "message",
    [
        "Use gpt-4 for summaries",  # no migration word
        "Switch to gpt-4",  # into the model
        "Bump openai from 1.0.0 to 1.2.0 and drop gpt-4",  # bot
    ],
)
def test_label_rejects(message: str) -> None:
    assert not label(candidate(message), STARTS)["migration"]


def test_label_rejects_commits_long_before_the_notice() -> None:
    row = label(candidate("Migrate from gpt-4 to gpt-4o", day="2024-05-13"), STARTS)
    assert row["after_notice_start"] is False
    assert not row["migration"]


def test_label_keeps_ids_without_a_notice_date() -> None:
    row = label(candidate("drop gemini-2.0-flash", ids=("gemini-2.0-flash",)), STARTS)
    assert row["after_notice_start"] is None
    assert row["migration"]


def test_ai_trailer_is_counted_separately() -> None:
    message = "Migrate from gpt-4 to gpt-5.6-sol\n\nCo-Authored-By: Claude <noreply@anthropic.com>"
    row = label(candidate(message), STARTS)
    assert not row["migration"]
    assert row["migration_with_ai"]


def test_unclear_direction_is_broad_but_not_strict() -> None:
    row = label(candidate("Update models (gpt-4)"), STARTS)
    assert row["migration"] and not row["migration_strict"]


def test_run_counts_the_funnel() -> None:
    rows = [
        candidate("Use gpt-4"),
        candidate("Switch to gpt-4"),
        candidate("Migrate from gpt-4 to gpt-4o", day="2024-05-13"),
        candidate("Migrate from gpt-4 to gpt-5.6-sol"),
        candidate("Update models (gpt-4)"),
        candidate("Migrate from gpt-4 to x-1\n\nCo-authored-by: Copilot <c@github.com>"),
    ]
    labeled, stats = run(rows, STARTS)
    assert len(labeled) == 6
    assert stats.candidates == 6
    assert stats.with_migration_word == 5
    assert stats.not_into == 4
    assert stats.not_before_notice == 3
    assert stats.not_bot == 3
    assert stats.migration == 2
    assert stats.migration_strict == 1
    assert stats.migration_with_ai == 1
    assert stats.by_provider == {"openai": 2}
    assert stats.directions == {"away": 3, "into": 2, "unclear": 1}


def test_main(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "candidates.jsonl"
    source.write_text(
        json.dumps(candidate("Migrate from gpt-4 to gpt-5.6-sol")) + "\n", encoding="utf-8"
    )
    out = tmp_path / "labeled.jsonl"
    assert main(["--candidates", str(source), "--out", str(out)]) == 0
    [row] = [json.loads(line) for line in out.read_text().splitlines()]
    assert row["migration"]
    assert json.loads(out.with_suffix(".stats.json").read_text())["migration"] == 1
    assert "= MIGRATION" in capsys.readouterr().out


def test_main_needs_candidates(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--candidates", str(tmp_path / "missing.jsonl")]) == 1
    assert "Run research.mining.miner first" in capsys.readouterr().err
