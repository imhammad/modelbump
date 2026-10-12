"""Tests for the in-sample rule check."""

import csv
from pathlib import Path

import pytest

from research.validation.dev_check import main, relabel


def test_relabel() -> None:
    assert relabel("Migrate from gpt-4 to gpt-4o", ["gpt-4"], None) == {
        "migration": True,
        "migration_strict": True,
        "migration_away": True,
    }
    early = relabel("Migrate from gpt-4 to gpt-4o", ["gpt-4"], False)
    assert not early["migration"] and early["migration_away"]
    assert relabel("Update models (gpt-4)", ["gpt-4"], True) == {
        "migration": True,
        "migration_strict": False,
        "migration_away": False,
    }


def test_main(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    labels = tmp_path / "sample.csv"
    key = tmp_path / "sample_key.csv"
    rows = [
        (1, "gpt-4", "Migrate from gpt-4 to gpt-4o", "yes"),
        (2, "gpt-4", "Update models (gpt-4)", "yes"),
        (3, "gpt-4", "gpt-4 was retired, notes only", "no"),
        (4, "gpt-4", "use gpt-4", "unsure"),
    ]
    with labels.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["n", "model_ids", "message", "is_migration"])
        writer.writerows([(n, ids, message, answer) for n, ids, message, answer in rows])
    with key.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["n", "sha", "stratum", "direction", "after_notice_start"])
        writer.writerows([(n, "s", "strict", "away", "") for n, *_ in rows])
    assert main(["--labels", str(labels), "--key", str(key)]) == 0
    out = capsys.readouterr().out
    assert "Labelled rows: 3, of which yes: 2" in out
    assert "migration_away          2     1      50.0%     50.0%" in out
    assert "Flagged away but labelled no:  3" in out
    assert "Labelled yes but not away:     2" in out


def test_main_needs_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--labels", str(tmp_path / "x.csv"), "--key", str(tmp_path / "k.csv")]) == 1
    assert "Need" in capsys.readouterr().err
