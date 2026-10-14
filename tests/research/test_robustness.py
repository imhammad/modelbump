"""Tests for the robustness checks of RQ1 and RQ2."""

import csv
import json
import math
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from modelbump.registry import load_registry
from research.analysis.robustness import (
    cliff_size,
    incomplete_searches,
    main,
    mann_whitney,
    repo_bootstrap,
    true_after_share,
    without_models,
)

# Models shut down before 2026-07-11, one per provider.
MODELS = {"openai": "o1-mini", "anthropic": "claude-3-5-sonnet-20241022", "google": None}


def commit(n: int, model_id: str, days: int, **labels: bool) -> dict[str, Any]:
    """A labelled candidate moving away from ``model_id``, ``days`` after its shutdown."""
    entry = load_registry().get(model_id)
    assert entry is not None
    when = entry[1].shutdown + timedelta(days=days)
    flags = {"migration": True, "migration_strict": True, "migration_away": True, **labels}
    return {
        "sha": f"s{n}",
        "repo": f"o/r{n % 5}",
        "url": f"https://github.com/o/r/commit/s{n}",
        "committed_at": f"{when.isoformat()}T12:00:00Z",
        "message": f"switch from {model_id} to a newer model",
        "matched_ids": [model_id],
        **flags,
    }


def make_data(data: Path) -> None:
    data.mkdir()
    rows = []
    for n in range(40):
        model_id = "o1-mini" if n % 2 else "claude-3-5-sonnet-20241022"
        days = (n * 7) % 90 - 30 + (20 if model_id == "o1-mini" else 0)
        rows.append(commit(n, model_id, days, migration_strict=n % 3 != 0))
    rows.append(commit(40, "gemini-2.0-flash", 5))
    rows.append(
        commit(41, "o1-mini", 10, migration=False, migration_strict=False, migration_away=False)
    )
    with (data / "labeled.jsonl").open("w", encoding="utf-8") as f:
        f.writelines(json.dumps(r) + "\n" for r in rows)
    (data / "targets.jsonl").write_text(
        "".join(json.dumps({"sha": f"s{n}", "ai_assisted": n < 4}) + "\n" for n in range(40)),
        encoding="utf-8",
    )
    stats = {
        "focused_starts": {"gpt-4": "2026-03-23"},
        "too_big_without_notice": ["gemini-2.0-flash"],
        "truncated_windows": ['"o1-mini" committer-date:2025-01-01..2025-01-01'],
    }
    (data / "candidates.stats.json").write_text(json.dumps(stats), encoding="utf-8")
    sample = data / "validation_v2_adjudicated"
    sample.mkdir()
    key = [(1, "s0", "away", "yes"), (2, "s1", "away", "no"), (3, "s2", "away", "yes")]
    key += [(4, "s41", "rejected", "yes"), (5, "s3", "other_kept", "no"), (6, "zz", "away", "?")]
    with (sample / "sample.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["n", "url", "message", "is_migration"])
        writer.writerows([n, "u", "m", answer] for n, _, _, answer in key)
    with (sample / "sample_key.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["n", "sha", "stratum", "direction", "after_notice_start"])
        writer.writerows([n, sha, stratum, "away", "True"] for n, sha, stratum, _ in key)
    population = {"away": 1000, "other_kept": 100, "rejected": 400}
    (sample / "strata.json").write_text(
        json.dumps({"design": "v2", "population": population}), encoding="utf-8"
    )


def test_incomplete_searches_by_registry_id() -> None:
    stats = {
        "focused_starts": {"gpt-4": "2026-03-23"},
        "too_big_without_notice": ["gemini-2.0-flash"],
        "truncated_windows": ['"gpt-4" committer-date:2026-05-01..2026-05-01', "bad"],
    }
    found = incomplete_searches(stats, load_registry())
    assert found == {
        "gemini-2.0-flash": ["too big, no notice date"],
        "gpt-4-0613": ["day over 1,000 results", "searched from the notice"],
    }
    rows = [{"model_id": "gpt-4-0613"}, {"model_id": "gpt-4"}, {"model_id": "o1-mini"}]
    assert without_models(rows, found, load_registry()) == [{"model_id": "o1-mini"}]


def test_mann_whitney() -> None:
    t = mann_whitney([1, 2, 3], [4, 5, 6])
    assert (t["u"], t["delta"]) == (0, -1)
    assert t["z"] == pytest.approx(-1.964, abs=1e-3)
    assert t["p"] == pytest.approx(0.0495, abs=1e-4)
    same = mann_whitney([1, 1, 2], [1, 1, 2])
    assert (same["delta"], same["z"], same["p"]) == (0, 0, 1)
    ties = mann_whitney([1, 2, 2, 3], [2, 3, 3, 4])
    assert ties["delta"] == pytest.approx(-0.625)  # (1 - 11) / 16
    assert math.isnan(mann_whitney([], [1])["p"])


@pytest.mark.parametrize(
    ("delta", "size"), [(0.1, "negligible"), (-0.2, "small"), (0.4, "medium"), (-0.9, "large")]
)
def test_cliff_size(delta: float, size: str) -> None:
    assert cliff_size(delta) == size


def test_repo_bootstrap() -> None:
    one: list[dict[str, Any]] = [{"repo": "a", "days_from_shutdown": d} for d in (-5, 3, 10)]
    boot = repo_bootstrap(one, reps=50)
    assert boot["share_low"] == boot["share_high"] == pytest.approx(2 / 3)
    many = [*one, {"repo": "b", "days_from_shutdown": -20}, {"repo": "c", "days_from_shutdown": 4}]
    boot = repo_bootstrap(many, reps=200)
    assert boot["share_low"] < 3 / 5 < boot["share_high"]
    assert boot == repo_bootstrap(many, reps=200)  # fixed seed


def test_true_after_share_weights_strata() -> None:
    rows = [
        {"stratum": "away", "yes": True, "after": True},
        {"stratum": "away", "yes": True, "after": False},
        {"stratum": "rejected", "yes": True, "after": True},
        {"stratum": "rejected", "yes": False, "after": False},
        {"stratum": "rejected", "yes": True, "after": None},
    ]
    # away: 100 * 1/2 after of 100 * 2/2 real; rejected: 300 * 1/2 after of 300 * 1/2 real.
    assert true_after_share(rows, {"away": 100, "rejected": 300}) == pytest.approx(200 / 250)


def test_main(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data = tmp_path / "data"
    out = tmp_path / "robustness.json"
    assert main(["--data", str(data), "--out", str(out)]) == 1
    assert "labeled.jsonl  <- research.filtering.filter" in capsys.readouterr().err
    make_data(data)
    assert main(["--data", str(data), "--out", str(out), "--reps", "100"]) == 0
    printed = capsys.readouterr().out
    assert "Models searched incompletely" in printed
    result = json.loads(out.read_text())
    labels = result["labels"]
    assert labels["headline"]["rows"] == 40
    assert labels["strict"]["rows"] == 26
    assert labels["no_ai"]["rows"] == 36
    assert result["first_per_repo"]["rows"] == 10  # 5 repositories, 2 models
    incomplete = result["incomplete"]
    assert set(incomplete["models"]) == {"gemini-2.0-flash", "gpt-4-0613", "o1-mini"}
    assert incomplete["exact"]["rows"] == 20  # the Claude rows
    assert (incomplete["google"]["rows"], incomplete["google_without"]["rows"]) == (1, 0)
    boot = result["repo_bootstrap"]
    assert boot["share_low"] <= labels["headline"]["share"] <= boot["share_high"]
    hand = result["hand"]
    assert hand["rows"] == 5  # "?" is left out
    assert hand["unplaced"] == 0
    assert hand["missed_after"] == {"after": 1, "rows": 1, "share": 1.0}
    assert hand["precision_before"]["rows"] + hand["precision_after"]["rows"] == 3
    assert result["providers"]["all"]["n1"] == 20
