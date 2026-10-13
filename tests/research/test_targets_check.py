"""Tests for checking the target extraction against hand labels."""

import csv
import json
from pathlib import Path

import pytest

from modelbump.registry import load_registry
from research.validation.targets_check import (
    check_row,
    hand_target,
    less_specific,
    main,
    verdict,
)

COLUMNS = ["n", "url", "model_ids", "date", "message", "is_migration", "from_model", "to_model"]


def sample_row(n: int, message: str, ids: str, answer: str, to_model: str) -> dict[str, str]:
    return {
        "n": str(n),
        "url": f"https://github.com/a/b/commit/{n}",
        "model_ids": ids,
        "date": "2026-07-01",
        "message": message,
        "is_migration": answer,
        "from_model": ids.split()[0],
        "to_model": to_model,
    }


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("gpt-4o", "gpt-4o"),
        (" GPT-4o-mini (via env) ", "gpt-4o-mini"),
        ("none", None),
        ("None", None),
        ("-", None),
        ("Some Local Model", "some-local-model"),
    ],
)
def test_hand_target(text: str, expected: str | None) -> None:
    assert hand_target(text) == expected


def test_verdict() -> None:
    reg = load_registry()
    assert verdict(None, None, reg) == "agree_none"
    assert verdict(None, "gpt-4o", reg) == "extra"
    assert verdict("gpt-4o", None, reg) == "missed"
    assert verdict("gpt-4o", "gpt-4o-2024-08-06", reg) == "match"
    assert verdict("gpt-4o", "gpt-4o-mini", reg) == "wrong_same_provider"
    assert verdict("gpt-4o", "claude-sonnet-4-5", reg) == "wrong_other_provider"


def test_check_row() -> None:
    reg = load_registry()
    row = sample_row(1, "Replace text-davinci-003 with gpt-4o", "text-davinci-003", "yes", "gpt-4o")
    out = check_row(row, row["message"], reg)
    assert out is not None
    assert out["left"] == "text-davinci-003"
    assert out["found"] == "gpt-4o"
    assert out["method"] == "replace_with"
    assert out["verdict"] == "match"
    assert check_row({**row, "is_migration": "no"}, row["message"], reg) is None
    assert check_row({**row, "to_model": " "}, row["message"], reg) is None


def test_main(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rows = [
        sample_row(1, "Replace text-davinci-003 with gpt-4o", "text-davinci-003", "yes", "gpt-4o"),
        sample_row(2, "Remove deprecated text-davinci-003", "text-davinci-003", "yes", "none"),
        sample_row(3, "Switch from text-davinci-003", "text-davinci-003", "y", "gpt-4o-mini"),
        sample_row(4, "Unrelated", "text-davinci-003", "no", ""),
        sample_row(5, "Replace text-davinci-003", "text-davinci-003", "yes", ""),
    ]
    with (tmp_path / "sample.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    # The full message of row 3 names the target; sample.csv cut it off.
    with (tmp_path / "sample_key.csv").open("w", newline="", encoding="utf-8") as f:
        f.write("n,sha,stratum,direction,after_notice_start\n3,sha3,away,away,True\n")
    labeled = tmp_path / "labeled.jsonl"
    full = {"sha": "sha3", "message": "Switch from text-davinci-003 to gpt-4o-mini"}
    labeled.write_text(json.dumps(full) + "\n")

    assert main(["--dir", str(tmp_path), "--labeled", str(labeled)]) == 0
    printed = capsys.readouterr().out
    assert "rows labelled yes: 4, with to_model filled in: 3" in printed
    assert "3 of 3" in printed
    with (tmp_path / "targets_check.csv").open(newline="", encoding="utf-8") as f:
        verdicts = [r["verdict"] for r in csv.DictReader(f)]
    assert verdicts == ["match", "agree_none", "match"]


def test_main_without_labels(tmp_path: Path) -> None:
    assert main(["--dir", str(tmp_path)]) == 1
    with (tmp_path / "sample.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerow(sample_row(1, "x", "gpt-4", "no", ""))
    assert main(["--dir", str(tmp_path), "--labeled", str(tmp_path / "none.jsonl")]) == 1


def test_less_specific_and_hand_not_model() -> None:
    reg = load_registry()
    assert less_specific("gemini-2.5", "gemini-2.5-flash")
    assert less_specific("llama-3.3-70b", "llama-3.3-70b-versatile")
    assert not less_specific("gpt-4", "gpt-4-turbo")
    assert not less_specific("gpt-4o", "gpt-4o-mini")
    assert verdict("gemini-2.5", "gemini-2.5-flash", reg) == "match"
    assert verdict("current-haiku-alias", "claude-haiku-4-5", reg) == "hand_not_model"


def test_check_row_uses_the_hand_left_model() -> None:
    reg = load_registry()
    message = (
        "- Main: claude-sonnet-4-20250514 -> claude-sonnet-4-5\n"
        "- Synthesis: claude-3-5-haiku-20241022 -> claude-haiku-4-5"
    )
    row = sample_row(
        1, message, "claude-sonnet-4-20250514 claude-3-5-haiku-20241022", "yes", "claude-sonnet-4-5"
    )
    out = check_row(row, message, reg)
    assert out is not None
    assert out["left_from_hand"] is True
    assert out["found"] == "claude-sonnet-4-5"
    assert out["verdict"] == "match"
