"""Tests for drawing the hand-labelling sample."""

import csv
import json
from pathlib import Path
from typing import Any

import pytest

from research.validation.sample import STRATA, draw, main, stratum, stratum_sizes


def row(sha: str, kind: str, message: str = "Migrate from gpt-4 to gpt-5.6-sol") -> dict[str, Any]:
    return {
        "sha": sha,
        "url": f"https://github.com/acme/app/commit/{sha}",
        "matched_ids": ["gpt-4"],
        "committed_at": "2026-05-01T12:00:00Z",
        "message": message,
        "direction": "away" if kind == "strict" else "unclear",
        "after_notice_start": True,
        "migration_strict": kind == "strict",
        "migration": kind in ("strict", "broad_only"),
        "migration_with_ai": kind == "with_ai",
    }


ROWS = [row(f"{kind[:2]}{i:03}", kind) for kind in STRATA for i in range(120)]


def test_stratum() -> None:
    assert [stratum(row("a", kind)) for kind in STRATA] == list(STRATA)


def test_draw_takes_the_planned_number_from_each_stratum() -> None:
    picked = draw(ROWS)
    counts = {name: sum(1 for s, _ in picked if s == name) for name in STRATA}
    assert counts == STRATA
    assert len({r["sha"] for _, r in picked}) == sum(STRATA.values())


def test_draw_is_reproducible_whatever_the_input_order() -> None:
    first = [r["sha"] for _, r in draw(ROWS, seed=7)]
    again = [r["sha"] for _, r in draw(list(reversed(ROWS)), seed=7)]
    assert first == again
    assert first != [r["sha"] for _, r in draw(ROWS, seed=8)]


def test_draw_takes_everything_from_a_small_stratum() -> None:
    picked = draw([row("only", "with_ai")])
    assert [s for s, _ in picked] == ["with_ai"]


def test_stratum_sizes() -> None:
    assert stratum_sizes(ROWS) == dict.fromkeys(STRATA, 120)


def write_labeled(tmp_path: Path, rows: list[dict[str, Any]]) -> Path:
    path = tmp_path / "labeled.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def test_main_writes_a_blind_sample_and_a_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rows = [*ROWS, row("long", "strict", message="x" * 2000)]
    out = tmp_path / "validation"
    assert main(["--labeled", str(write_labeled(tmp_path, rows)), "--out", str(out)]) == 0
    with (out / "sample.csv").open(encoding="utf-8") as f:
        sample = list(csv.DictReader(f))
    with (out / "sample_key.csv").open(encoding="utf-8") as f:
        key = list(csv.DictReader(f))
    assert len(sample) == len(key) == 300
    assert "stratum" not in sample[0]  # blind
    assert sample[0]["is_migration"] == ""
    assert {k["stratum"] for k in key} == set(STRATA)
    assert all(len(s["message"]) <= 1506 for s in sample)
    strata = json.loads((out / "strata.json").read_text())
    assert strata["population"]["strict"] == 121
    assert "Sampled 300 commits" in capsys.readouterr().out


def test_main_never_overwrites_labels(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "validation"
    out.mkdir()
    (out / "sample.csv").write_text("my labels", encoding="utf-8")
    assert main(["--labeled", str(write_labeled(tmp_path, ROWS)), "--out", str(out)]) == 1
    assert (out / "sample.csv").read_text() == "my labels"
    assert "not overwritten" in capsys.readouterr().err


def test_main_needs_labeled(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--labeled", str(tmp_path / "missing.jsonl")]) == 1
    assert "Run research.filtering.filter first" in capsys.readouterr().err
