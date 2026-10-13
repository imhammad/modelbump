"""Tests for the hand check of file kinds."""

import csv
import json
from pathlib import Path
from typing import Any

import pytest

from research.validation.files_check import compare, draw, file_list, main


def fetched(sha: str, test: bool, evals: bool = False, n_files: int = 2) -> dict[str, Any]:
    files = [{"path": f"src/f{i}.py", "status": "modified"} for i in range(n_files)]
    if test:
        files.append({"path": "tests/test_x.py", "status": "added"})
    return {
        "sha": sha,
        "url": f"https://github.com/a/b/commit/{sha}",
        "found": True,
        "files": files,
        "touches_test": test,
        "touches_eval": evals,
    }


def test_file_list() -> None:
    row = fetched("a", True)
    assert file_list(row) == "M src/f0.py; M src/f1.py; A tests/test_x.py"
    long = fetched("b", False, n_files=90)
    assert file_list(long).endswith("; ... and 10 more")


def test_draw_skips_missing_commits() -> None:
    rows = [fetched(f"s{i}", False) for i in range(5)] + [{"sha": "gone", "found": False}]
    assert len(draw(rows, 10, 1)) == 5
    assert draw(rows, 3, 1) == draw(list(reversed(rows)), 3, 1)


def test_compare() -> None:
    hand = {1: "yes", 2: "no", 3: "yes", 4: "no"}
    code = {1: "yes", 2: "no", 3: "no", 4: "no", 5: "yes"}
    c = compare(hand, code)
    assert c["n"] == 4
    assert c["agree"] == 3
    assert (c["both_yes"], c["hand_only"], c["code_only"], c["both_no"]) == (1, 1, 0, 2)


def test_draw_then_score(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    files = tmp_path / "files.jsonl"
    rows = [fetched(f"s{i}", i % 2 == 0) for i in range(4)]
    files.write_text("".join(json.dumps(r) + "\n" for r in rows))
    out = tmp_path / "check"
    assert main(["--files", str(files), "--dir", str(out)]) == 0
    assert main(["--files", str(files), "--dir", str(out)]) == 1  # never overwritten
    assert main(["--dir", str(out), "--score"]) == 1  # nothing labelled yet

    with (out / "sample.csv").open(newline="", encoding="utf-8") as f:
        sheet = list(csv.DictReader(f))
    assert "touches_test" not in sheet[0]  # blind
    for row in sheet:
        row["has_test"] = "yes" if "tests/" in row["files"] else "no"
        row["has_eval"] = "no"
    with (out / "sample.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(sheet[0]))
        writer.writeheader()
        writer.writerows(sheet)
    capsys.readouterr()
    assert main(["--dir", str(out), "--score"]) == 0
    printed = capsys.readouterr().out
    assert "has_test (4 commits labelled)" in printed
    assert "agreement      4 of 4 = 100.0%" in printed


def test_main_without_files(tmp_path: Path) -> None:
    assert main(["--files", str(tmp_path / "none.jsonl"), "--dir", str(tmp_path / "x")]) == 1
    assert main(["--dir", str(tmp_path / "x"), "--score"]) == 1
