"""Tests for the script that builds the paper's numbers, tables and figures."""

import csv
import json
import math
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from modelbump.registry import load_registry
from research.analysis import lag
from research.analysis.paper import Paper, build, main, numbers_tex, pct, short_window, tt
from research.enrichment import files, targets
from research.validation.score import wilson


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def timing_row(n: int, provider: str, days: int) -> dict[str, Any]:
    shutdown = date(2026, 1, 1)
    return {
        "sha": f"t{n}",
        "repo": f"r/{n % 7}",
        "committed": (shutdown + timedelta(days=days)).isoformat(),
        "model_id": f"{provider}-old",
        "provider": provider,
        "notice": None if provider == "google" else "2025-07-01",
        "shutdown": shutdown.isoformat(),
        "phase": "after_shutdown" if days >= 0 else "after_notice",
        "days_from_shutdown": days,
    }


def file_row(n: int, test: bool, evals: bool) -> dict[str, Any]:
    return {
        "sha": f"f{n}",
        "url": f"https://github.com/a/b/commit/f{n}",
        "found": True,
        "files": [{"path": "src/app.py", "status": "modified"}],
        "file_count": 1,
        "truncated": False,
        "kinds": {"code": 1, **({"test": 1} if test else {}), **({"eval": 1} if evals else {})},
        "touches_test": test,
        "adds_test": False,
        "test_mentions_model": test,
        "touches_eval": evals,
        "adds_eval": False,
        "touches_prompt": False,
        "touches_code": True,
        "id_swap_only": not test,
        "ai_assisted": n % 2 == 0,
    }


def summary(after: int, rows: int, median: float) -> dict[str, Any]:
    """One robustness summary, as research.analysis.robustness writes it."""
    low, high = wilson(after, rows)
    share = after / rows if rows else None
    return {
        "rows": rows,
        "repos": rows // 2,
        "after": after,
        "share": share,
        "low": low,
        "high": high,
        "median_days": median,
        "median_low": median - 2,
        "median_high": median + 2,
    }


def robustness_result() -> dict[str, Any]:
    """A robustness.json that matches the timing_90d headline below."""
    test = {"n1": 7_000, "n2": 5_244, "u": 1.0, "z": -3.5, "p": 0.0004, "delta": -0.06}
    return {
        "retired_by": "2026-07-11",
        "seed": 2029,
        "labels": {
            "headline": summary(7_619, 12_244, 11),
            "kim_label": summary(7_000, 11_000, 9),
            "strict": summary(5_000, 8_000, 10),
            "no_ai": summary(7_100, 11_500, 12),
        },
        "first_per_repo": summary(6_742, 10_947, 8),
        "google": summary(50, 100, 3),
        "truncation": {
            "models": {
                "gpt-4-0613": ["day over 1,000 results", "searched from the notice"],
                "o1-mini": ["day over 1,000 results"],
            },
            "late_searched_rows": 0,
            "days": 61,
            "days_without_total": 0,
            "days_after_shutdown": 10,
            "days_before_shutdown": 51,
            "missing_results": 120_000,
            "largest_total": 9_000,
            "exact": {
                **summary(7_619, 12_244, 11),
                "share": 0.615,
                "low": 0.60,
                "high": 0.63,
                "reweighted": 300,
                "weighted_rows": 13_000.0,
            },
            "google": {**summary(0, 0, math.nan), "low": None, "high": None},
        },
        "repo_bootstrap": {
            "reps": 2_000,
            "seed": 2029,
            "repos": 9_000,
            "share_low": 0.60,
            "share_high": 0.64,
            "median_low": 7.0,
            "median_high": 15.0,
        },
        "hand": {
            "rows": 196,
            "unplaced": 2,
            "precision_after": {"yes": 40, "rows": 45, "share": 0.89, "low": 0.76, "high": 0.95},
            "precision_before": {"yes": 40, "rows": 52, "share": 0.77, "low": 0.64, "high": 0.86},
            "label_after": {"after": 45, "rows": 97, "share": 0.46},
            "missed_after": {"after": 9, "rows": 20, "share": 0.45},
            "true_after": {"share": 0.47, "low": 0.38, "high": 0.56},
        },
        "providers": {
            "all": {**test, "size": "negligible"},
            "after_shutdown": {**test, "p": 0.2, "delta": 0.2, "size": "small"},
            "first_per_repo": {**test, "p": None, "delta": None, "size": ""},
        },
    }


def make_data(data: Path) -> None:
    """A small but complete set of inputs."""
    data.mkdir()
    write_json(
        data / "candidates.stats.json",
        {
            "start": "2023-01-01",
            "end": "2026-10-08",
            "model_ids": 139,
            "queries": 11_003,
            "items_seen": 851_580,
            "truncated_windows": ["w"] * 61,
            "failed_windows": [],
        },
    )
    write_json(
        data / "labeled.stats.json",
        {
            "candidates": 254_765,
            "with_migration_word": 90_000,
            "not_into": 80_000,
            "not_before_notice": 70_000,
            "not_bot": 60_000,
            "migration": 40_483,
            "migration_with_ai": 36_048,
            "migration_away": 40_876,
        },
    )
    headline = {
        "exact_dates": {"after": 7_619, "total": 12_244},
        "exact_dates_kim_window": {"after": 7_619, "total": 11_006},
        "exact_dates_first_per_repo": {"after": 6_742, "total": 10_947},
        "google_earliest_dates": {"after": 50, "total": 100},
    }
    write_json(data / "timing_90d.stats.json", {"retired_by": "2026-07-11", "headline": headline})
    write_json(
        data / "timing.stats.json",
        {
            "retired_by": "2026-10-08",
            "headline": {**headline, "exact_dates": {"after": 7_955, "total": 13_754}},
        },
    )
    rows = [
        timing_row(i, provider, days)
        for i, (provider, days) in enumerate(
            (p, d) for p in ("openai", "anthropic", "google") for d in range(-60, 120, 10)
        )
    ]
    (data / "timing.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    stats = lag.run(rows, retired_by=date(2026, 7, 11), minimum=1)
    write_json(data / "lag.stats.json", lag.finite(asdict(stats)))

    def commit(message: str) -> dict[str, Any]:
        return {
            "sha": message,
            "repo": "a/b",
            "url": "https://github.com/a/b/commit/x",
            "committed_at": "2026-07-01T12:00:00Z",
            "message": message,
            "matched_ids": ["gpt-4"],
            "migration_away": True,
        }

    commits = [
        commit("switch from gpt-4 to gpt-4o"),
        commit("Replace gpt-4 with claude-sonnet-4-5"),
        commit("remove deprecated gpt-4"),
    ]
    _, target_stats = targets.run(commits, load_registry())
    write_json(data / "targets.stats.json", asdict(target_stats))

    found = [file_row(n, test=n < 3, evals=n == 0) for n in range(10)]
    (data / "files.jsonl").write_text("".join(json.dumps(r) + "\n" for r in found))
    write_json(data / "files.stats.json", asdict(files.summarise(found, 500, 2028)))

    v2 = data / "validation_v2_adjudicated"
    answers = ["yes", "yes", "yes", "no", "yes", "no", "yes", "no"]
    strata = ["away"] * 4 + ["other_kept"] * 2 + ["rejected"] * 2
    write_csv(v2 / "sample.csv", [{"n": i, "is_migration": a} for i, a in enumerate(answers)])
    write_csv(v2 / "sample_b.csv", [{"n": i, "is_migration": a} for i, a in enumerate(answers)])
    write_csv(v2 / "sample_key.csv", [{"n": i, "stratum": s} for i, s in enumerate(strata)])
    write_json(
        v2 / "strata.json",
        {"design": "v2", "population": {"away": 40_876, "other_kept": 5_000, "rejected": 9_000}},
    )
    verdicts = ["match"] * 7 + ["agree_none", "missed", "extra", "hand_not_model"]
    write_csv(v2 / "targets_check.csv", [{"n": i, "verdict": v} for i, v in enumerate(verdicts)])

    write_json(data / "robustness.json", robustness_result())

    sheet = data / "validation_files"
    write_csv(
        sheet / "sample.csv",
        [
            {"n": n, "has_test": "yes" if n < 4 else "no", "has_eval": "yes" if n < 2 else "no"}
            for n in range(10)
        ],
    )
    write_csv(
        sheet / "sample_key.csv",
        [{"n": n, "sha": f"f{n}", "touches_test": n < 2, "touches_eval": False} for n in range(10)],
    )


def test_paper_put_checks_names() -> None:
    paper = Paper()
    paper.count("Commits", 40_876)
    assert paper.numbers["Commits"] == "40,876"
    with pytest.raises(ValueError, match="letters only"):
        paper.put("Rq4", "x")
    with pytest.raises(ValueError, match="twice"):
        paper.count("Commits", 1)
    paper.share("Half", 1, 2)
    assert (paper.numbers["Half"], paper.raw["Half"]) == ("50.0", 0.5)
    assert paper.raw["HalfLow"] < 0.5 < paper.raw["HalfHigh"]
    paper.share("Nothing", 0, 0, ci=False)
    assert paper.numbers["Nothing"] == "--"
    assert "\\newcommand{\\Commits}{40,876}" in numbers_tex(paper)


def test_helpers() -> None:
    assert pct(0.5781) == "57.8"
    assert short_window("more than 180 days before") == ">180"
    assert short_window("91 to 180 days before") == "91\u2013180"
    assert short_window("0 to 30 days after") == "0\u201330"
    assert tt("gpt_4&co") == "gpt\\_4\\&co"


def test_build(tmp_path: Path) -> None:
    make_data(tmp_path / "data")
    paper = build(tmp_path / "data")
    n = paper.numbers
    assert n["MigrationsAway"] == "40,876"
    assert n["TruncatedWindows"] == "61"
    assert (n["AfterAll"], n["AfterLate"], n["AfterWindow"]) == ("57.8", "62.2", "69.2")
    assert n["KimAfterShutdown"] == "82"
    assert n["Precision"] == "75.0"  # 3 of the 4 "away" rows
    assert n["FilterKappa"] == "1.00"
    assert n["TargetCheck"] == "80.0"  # match 7 + agree_none 1, of 10 compared
    assert n["TargetNamedRight"] == "87.5"  # 7 of match 7 + extra 1
    assert n["TargetCheckBefore"] == "72.2"
    assert (n["FileCheckTestBefore"], n["FileCheckTestAfter"]) == ("80.0", "90.0")
    assert n["FileCheckTestAfterFound"] == "3"
    assert n["FileHandEval"] == "20.0"
    assert n["TouchTest"] == "30.0"
    assert n["KimTouchTest"] == "16"
    assert n["TargetRows"] == "3"
    assert n["ExactDays"] != "--"
    assert (n["AfterLateRepoLow"], n["AfterLateRepoHigh"]) == ("60.0", "64.0")
    assert n["AfterKimLabel"] == "63.6"
    assert (n["AfterReweighted"], n["AfterReweightedLow"]) == ("61.5", "60.0")
    assert (n["CutDays"], n["CutModels"], n["CutMissing"]) == ("61", "2", "120,000")
    assert n["AfterGoogleReweighted"] == "--"
    assert n["PrecisionAfter"] == "88.9"
    assert n["SampleTrueAfter"] == "47.0"
    assert (n["CliffAll"], n["CliffAllP"], n["CliffAllSize"]) == (
        "$-$0.06",
        "$<0.001$",
        "negligible",
    )
    assert (n["CliffLateP"], n["CliffFirst"], n["CliffFirstP"]) == ("$=0.200$", "--", "--")
    assert set(paper.tables) == {
        "dataset.tex",
        "validation.tex",
        "timing.tex",
        "lag.tex",
        "targets.tex",
        "top-switches.tex",
        "changed-files.tex",
        "robustness.tex",
    }
    assert set(paper.figures) == {
        "lag-windows.pdf",
        "lag-ecdf.pdf",
        "targets.pdf",
        "changed-files.pdf",
    }
    assert "Google, cut days" not in paper.tables["robustness.tex"]  # no rows
    for table in paper.tables.values():
        assert table.startswith("\\begin{tabular}") and "\\bottomrule" in table


def test_build_stops_on_old_robustness(tmp_path: Path) -> None:
    make_data(tmp_path / "data")
    old = robustness_result()
    old["labels"]["headline"] = summary(7_000, 12_000, 11)
    write_json(tmp_path / "data" / "robustness.json", old)
    assert main(["--data", str(tmp_path / "data"), "--out", str(tmp_path / "out")]) == 1


def test_main(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data, out = tmp_path / "data", tmp_path / "out"
    assert main(["--data", str(data), "--out", str(out)]) == 1
    assert "lag.stats.json  <- research.analysis.lag" in capsys.readouterr().err
    make_data(data)
    assert main(["--data", str(data), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "\\MigrationsAway" in printed
    numbers = json.loads((out / "numbers.json").read_text())
    assert numbers["MigrationsAway"] == 40_876
    assert (out / "tables" / "timing.tex").read_text().count("\\\\") >= 6
    pdf = (out / "figures" / "lag-ecdf.pdf").read_bytes()
    assert pdf.startswith(b"%PDF")
    # Same data, same files: the figures carry no creation date.
    assert main(["--data", str(data), "--out", str(out)]) == 0
    assert (out / "figures" / "lag-ecdf.pdf").read_bytes() == pdf
