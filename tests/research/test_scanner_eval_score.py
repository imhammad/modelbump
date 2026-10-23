"""Tests for scoring the scanner's labelled findings. No network is used."""

import csv
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from research.scanner_eval.build import SHEET_COLUMNS
from research.scanner_eval.score import (
    SheetError,
    check_rows,
    interval,
    main,
    read_labels,
    score,
)

# row -> (group, context, answer)
ROWS: dict[int, tuple[str, str, str]] = {
    1: ("code_use", "call_argument", "yes"),
    2: ("code_use", "assignment", "yes"),
    3: ("code_use", "call_argument", "no"),
    4: ("documentation", "comment", "no"),
    5: ("documentation", "docstring", "no"),
    6: ("config", "config", "Yes "),
    7: ("config", "config", "unclear"),
    8: ("text", "text", "n"),
}
STATS: dict[str, Any] = {
    "group_population": {
        "code_use": 300,
        "code_string": 0,
        "documentation": 100,
        "config": 100,
        "text": 0,
    },
    "recall": {"yes": 9, "n": 10, "share": 0.9, "low": 0.6, "high": 0.98},
    "misses_by_reason": {"file type not scanned": 1},
}


def write_case(
    folder: Path,
    answers: Mapping[int, str] | None = None,
    bom: bool = False,
    stats: Mapping[str, Any] = STATS,
) -> None:
    """A labelled sheet, its key and build statistics."""
    folder.mkdir(parents=True, exist_ok=True)
    answers = answers if answers is not None else {n: a for n, (_, _, a) in ROWS.items()}
    with (folder / "sheet.csv").open(
        "w", newline="", encoding="utf-8-sig" if bom else "utf-8"
    ) as f:
        sheet = csv.DictWriter(f, fieldnames=SHEET_COLUMNS)
        sheet.writeheader()
        for n in answers:
            sheet.writerow({c: "" for c in SHEET_COLUMNS} | {"row": n, "dependency": answers[n]})
    with (folder / "sheet_key.csv").open("w", newline="", encoding="utf-8") as f:
        key = csv.writer(f)
        key.writerow(("row", "group", "context", "detail", "sha"))
        for n, (group, context, _) in ROWS.items():
            key.writerow((n, group, context, "", "abc"))
    (folder / "build.stats.json").write_text(json.dumps(stats), encoding="utf-8")


def key_of(rows: Mapping[int, tuple[str, str, str]]) -> dict[int, dict[str, str]]:
    return {
        n: {"group": g, "context": c, "detail": "", "sha": "abc"} for n, (g, c, _) in rows.items()
    }


def test_read_labels_normalises_answers_and_finds_blanks(tmp_path: Path) -> None:
    write_case(tmp_path, {1: "YES", 2: " no", 3: "", 4: "maybe", 5: "?"}, bom=True)
    labels, blank, unknown = read_labels(tmp_path / "sheet.csv")
    assert labels == {1: "yes", 2: "no", 5: "unsure"}
    assert blank == [3]
    assert unknown == [4]


def test_read_labels_accepts_numbers_style_row_numbers(tmp_path: Path) -> None:
    path = tmp_path / "sheet.csv"
    path.write_text("row,dependency\n7.0,yes\n,\n", encoding="utf-8")
    assert read_labels(path) == ({7: "yes"}, [], [])


def test_check_rows() -> None:
    key = key_of(ROWS)
    check_rows([1, 2, 3], key)
    with pytest.raises(SheetError, match="not in sheet_key"):
        check_rows([1, 99], key)
    with pytest.raises(SheetError, match="more than once"):
        check_rows([1, 1], key)


def test_interval_stays_between_zero_and_one() -> None:
    low, high = interval(0.99, 0.1)
    assert low == pytest.approx(0.99 - 0.196, abs=1e-3)
    assert high == 1.0
    assert interval(0.01, 0.1)[0] == 0.0


def test_score_weights_groups_by_size() -> None:
    labels = {1: "yes", 2: "yes", 3: "no", 4: "no", 5: "no", 6: "yes", 7: "unsure", 8: "no"}
    result = score(labels, key_of(ROWS), STATS)
    assert result["groups"]["code_use"]["share"] == pytest.approx(2 / 3)
    assert result["groups"]["config"]["unsure"] == 1
    assert result["groups"]["config"]["labelled"] == 1
    # Text has no findings, so its labelled "no" row carries no weight.
    assert result["precision"]["groups"] == ["code_use", "documentation", "config"]
    assert result["precision"]["estimate"] == pytest.approx(0.6 * 2 / 3 + 0.2 * 0 + 0.2 * 1)
    assert result["precision_skip_comments"]["groups"] == ["code_use", "config"]
    assert result["precision_skip_comments"]["estimate"] == pytest.approx(0.75 * 2 / 3 + 0.25)
    assert result["precision_skip_comments"]["findings"] == 400
    assert result["by_context"]["call_argument"]["share"] == pytest.approx(0.5)
    assert result["by_context"]["assignment"]["yes"] == 1
    assert result["unsure"] == 1
    assert result["recall"]["share"] == 0.9


def test_main_scores_and_writes_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_case(tmp_path)
    assert main(["--dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "Precision, all findings (weighted):   60.0%" in out
    assert "Precision with --skip-comments:       75.0%" in out
    assert "Recall on known sites (from build):   90.0%" in out
    assert "code_string" in out and "     -" in out
    written = json.loads((tmp_path / "scanner_eval.json").read_text(encoding="utf-8"))
    assert written["labelled_rows"] == 8
    assert written["blank_rows"] == 0
    assert "kappa" not in written


def test_main_notes_blank_rows(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_case(tmp_path, {1: "yes", 2: "", 3: "no"})
    assert main(["--dir", str(tmp_path)]) == 0
    assert "Note: 6 of 8 rows have no label yet" in capsys.readouterr().out


def test_main_reports_agreement(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_case(tmp_path)
    write_case(tmp_path / "b", {n: "yes" if n < 7 else "no" for n in ROWS})
    assert main(["--dir", str(tmp_path), "--second", str(tmp_path / "b" / "sheet.csv")]) == 0
    assert "Agreement (Cohen's kappa) over 8 rows" in capsys.readouterr().out
    written = json.loads((tmp_path / "scanner_eval.json").read_text(encoding="utf-8"))
    assert written["kappa_rows"] == 8


@pytest.mark.parametrize(
    ("answers", "message"),
    [
        ({1: "yes", 2: "maybe"}, "not yes, no or unclear: [2]"),
        ({1: "yes", 42: "no"}, "rows not in sheet_key.csv: [42]"),
    ],
)
def test_main_rejects_bad_sheets(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    answers: Mapping[int, str],
    message: str,
) -> None:
    write_case(tmp_path, answers)
    assert main(["--dir", str(tmp_path)]) == 1
    assert message in capsys.readouterr().err


def test_main_needs_the_sheet(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--dir", str(tmp_path)]) == 1
    assert "Run research.scanner_eval.build first" in capsys.readouterr().err


def test_main_without_recall(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    stats: dict[str, Any] = dict(STATS)
    stats["recall"] = {"yes": 0, "n": 0, "share": None, "low": 0.0, "high": 1.0}
    write_case(tmp_path, stats=stats)
    assert main(["--dir", str(tmp_path)]) == 0
    assert "Recall on known sites" not in capsys.readouterr().out
