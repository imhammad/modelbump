"""Tests for scoring the hand labels."""

import csv
import json
from pathlib import Path

import pytest

from research.validation.score import (
    StratumScore,
    cohen_kappa,
    main,
    read_labels,
    score_strata,
    weighted_precision,
    wilson,
)

POPULATION = {"strict": 1000, "broad_only": 3000, "with_ai": 500, "rejected": 10000}


def test_wilson_matches_a_known_value() -> None:
    # 8 of 10: the 95% Wilson interval is about 0.490 to 0.943.
    low, high = wilson(8, 10)
    assert low == pytest.approx(0.490, abs=0.001)
    assert high == pytest.approx(0.943, abs=0.001)
    assert wilson(0, 0) == (0.0, 1.0)


def test_cohen_kappa() -> None:
    first = {1: "yes", 2: "yes", 3: "no", 4: "no"}
    assert cohen_kappa(first, first) == (1.0, 4)
    # Agree on 2 of 4, with each answer equally likely: kappa 0.
    second = {1: "yes", 2: "no", 3: "yes", 4: "no"}
    assert cohen_kappa(first, second) == (0.0, 4)
    assert cohen_kappa(first, {9: "yes"}) == (0.0, 0)
    assert cohen_kappa({1: "yes"}, {1: "yes"}) == (1.0, 1)


def test_score_strata_leaves_unsure_out_of_the_share() -> None:
    labels = {1: "yes", 2: "no", 3: "unsure", 4: "yes"}
    key = {1: "strict", 2: "strict", 3: "strict", 4: "rejected"}
    scores = score_strata(labels, key, POPULATION)
    assert scores["strict"].labelled == 2
    assert scores["strict"].unsure == 1
    assert scores["strict"].share == 0.5
    assert scores["broad_only"].labelled == 0


def score(share: float, labelled: int, population: int) -> StratumScore:
    return StratumScore(population, labelled, round(share * labelled), 0, share, 0.0, 1.0)


def test_weighted_precision() -> None:
    scores = {"strict": score(0.9, 100, 1000), "broad_only": score(0.5, 100, 3000)}
    estimate, error = weighted_precision(scores, ["strict", "broad_only"])
    assert estimate == pytest.approx(0.25 * 0.9 + 0.75 * 0.5)
    assert error > 0
    assert weighted_precision({"strict": score(0, 0, 0)}, ["strict"]) == (0.0, 0.0)


def write_sample(directory: Path, answers: dict[int, str], name: str = "sample.csv") -> Path:
    path = directory / name
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["n", "url", "is_migration", "from_model", "to_model", "note"])
        for n, answer in answers.items():
            writer.writerow([n, "u", answer, "", "", ""])
    return path


def test_read_labels_accepts_short_answers(tmp_path: Path) -> None:
    path = write_sample(tmp_path, {1: "Yes", 2: " n ", 3: "?", 4: "", 5: "maybe"})
    assert read_labels(path) == {1: "yes", 2: "no", 3: "unsure"}


def test_main(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    strata = ["strict"] * 4 + ["broad_only"] * 4 + ["with_ai"] * 2 + ["rejected"] * 2
    answers = ["yes", "yes", "yes", "no", "yes", "no", "no", "no", "yes", "yes", "no", ""]
    write_sample(tmp_path, dict(enumerate(answers, start=1)))
    write_sample(tmp_path, dict(enumerate(answers, start=1)), name="second.csv")
    with (tmp_path / "sample_key.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["n", "sha", "stratum", "direction", "after_notice_start"])
        for n, name in enumerate(strata, start=1):
            writer.writerow([n, f"s{n}", name, "away", "True"])
    (tmp_path / "strata.json").write_text(json.dumps({"population": POPULATION}))
    code = main(["--dir", str(tmp_path), "--second", str(tmp_path / "second.csv")])
    assert code == 0
    out = capsys.readouterr().out
    assert "1 of 12 rows have no yes/no/unsure" in out
    assert "Precision of 'migration' (weighted): 37.5%" in out  # 0.25*0.75 + 0.75*0.25
    assert "Cohen's kappa) over 11 rows: 1.00" in out
    result = json.loads((tmp_path / "scores.json").read_text())
    assert result["strata"]["strict"]["yes"] == 3
    assert result["estimated_missed"] == 0


def test_main_needs_a_sample(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--dir", str(tmp_path)]) == 1
    assert "Run research.validation.sample first" in capsys.readouterr().err
