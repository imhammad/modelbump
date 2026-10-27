"""Smoke and unit tests for the stats simulation study (ADR 0044)."""

import json
from pathlib import Path

import pytest

from modelbump.stats import Verdict
from research.stats_sim.run import (
    Settings,
    fixed_k_chances,
    main,
    peeking_experiment,
    suite_experiment,
    summary,
    verdict_table,
)


def test_fixed_k_chances_add_up_to_one_and_match_p4_1() -> None:
    table = verdict_table(10, 0.05, 0.1)
    chances = fixed_k_chances(table, 0.9, 0.9)
    assert sum(chances.values()) == pytest.approx(1.0)
    assert table[9][4] is Verdict.REGRESSED
    assert chances[Verdict.REGRESSED] < 0.05


def test_fixed_k_chance_is_certain_for_models_that_never_vary() -> None:
    chances = fixed_k_chances(verdict_table(30, 0.05, 0.1), 1.0, 0.0)
    assert chances[Verdict.REGRESSED] == pytest.approx(1.0)


def test_quick_settings_scale_the_scenarios() -> None:
    quick = Settings.quick()
    assert quick.scaled(30) == 3
    assert Settings().scaled(30) == 30


def test_quick_run_writes_every_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--quick", "--out", str(tmp_path)]) == 0
    for name in ("item.csv", "peeking.csv", "suite.csv", "stopping.csv", "results.json"):
        assert (tmp_path / name).is_file()
    assert (tmp_path / "figures" / "power.png").is_file()
    assert (tmp_path / "figures" / "answers.png").is_file()
    results = json.loads((tmp_path / "results.json").read_text())
    assert {"settings", "item", "peeking", "suite", "stopping"} <= results.keys()
    single = [r for r in results["item"] if r["method"] == "single run" and r["drop"] == 0]
    assert max(r["p_regressed"] for r in single) == pytest.approx(0.24)
    printed = capsys.readouterr().out
    assert "single run 24.0%" in printed
    assert printed.splitlines() == [*summary(results), *printed.splitlines()[-2:]]


def test_the_same_settings_give_the_same_numbers() -> None:
    tiny = Settings(reps=10, seeds=1, stopping_seeds=1, suite_size=20, max_runs=40)
    assert suite_experiment(tiny) == suite_experiment(tiny)
    assert peeking_experiment(tiny) == peeking_experiment(tiny)
