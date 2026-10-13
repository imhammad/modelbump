"""Tests for packaging the dataset for publication."""

import csv
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest

from research.release.export import (
    STATS,
    VALIDATION_DIRS,
    cell,
    changed_files,
    header,
    main,
    migrations,
)


def jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def make_data(data: Path) -> None:
    data.mkdir()
    candidate = {
        "sha": "a1",
        "repo": "o/r",
        "repos": ["o/r", "o/fork"],
        "url": "https://github.com/o/r/commit/a1",
        "committed_at": "2026-07-01T12:00:00Z",
        "message": "Switch from gpt-4 to gpt-4o\n\nCo-Authored-By: Someone <me@example.com>",
        "matched_ids": ["gpt-4"],
        "providers": ["openai"],
        "migration_word": True,
        "direction": "away",
        "after_notice_start": None,
        "bot": False,
        "ai_trailer": False,
        "ai_style": False,
        "migration": True,
        "migration_strict": True,
        "migration_with_ai": False,
        "migration_away": True,
    }
    jsonl(data / "labeled.jsonl", [candidate, {**candidate, "sha": "b2", "migration_away": False}])
    jsonl(
        data / "timing.jsonl",
        [{"sha": "a1", "repo": "o/r", "model_id": "gpt-4", "days_from_shutdown": 12}],
    )
    jsonl(data / "targets.jsonl", [{"sha": "a1", "target": "gpt-4o", "ai_assisted": False}])
    jsonl(
        data / "files.jsonl",
        [
            {
                "sha": "a1",
                "found": True,
                "touches_test": True,
                "files": [
                    {"path": "src/a.py", "status": "modified", "kind": "code"},
                    {"path": "tests/test_a.py", "status": "added", "kind": "test"},
                ],
            },
            {"sha": "c3", "found": False, "http_status": 404},
        ],
    )
    for name in STATS:
        (data / f"{name}.stats.json").write_text("{}", encoding="utf-8")
    for name in VALIDATION_DIRS:
        (data / name).mkdir()
        (data / name / "sample.csv").write_text(
            'n,url,message,is_migration\n1,https://x,"Hello, me@example.com",yes\n',
            encoding="utf-8",
        )
        (data / name / "strata.json").write_text("{}", encoding="utf-8")
        (data / name / "sample.numbers").write_text("not copied", encoding="utf-8")


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, ""), (True, "true"), (False, "false"), (["a", "b"], "a b"), (12, "12"), ("x", "x")],
)
def test_cell(value: Any, expected: str) -> None:
    assert cell(value) == expected


def test_migrations_and_changed_files() -> None:
    rows = migrations([{"sha": "a1", "phase": "after_shutdown"}], [{"sha": "a1", "target": "t"}])
    assert rows[0]["phase"] == "after_shutdown" and rows[0]["target"] == "t"
    assert migrations([{"sha": "z"}], [])[0]["target"] is None
    sample = [{"sha": "a1", "found": True, "files": [{"path": "p"}]}, {"sha": "b", "found": False}]
    assert changed_files(sample) == [{"sha": "a1", "path": "p"}]


def test_main(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data, out = tmp_path / "data", tmp_path / "out"
    assert main(["--data", str(data), "--out", str(out)]) == 1
    assert "labeled.jsonl" in capsys.readouterr().err
    make_data(data)
    assert main(["--data", str(data), "--out", str(out), "--version", "9.9.9"]) == 0
    printed = capsys.readouterr().out
    assert "no file has a commit message column" in printed
    folder = out / "modelbump-migrations-9.9.9"
    with (folder / "candidates.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2
    assert rows[0]["repos"] == "o/r o/fork"
    assert rows[0]["after_notice_start"] == ""
    assert rows[0]["migration_away"] == "true"
    assert "message" not in rows[0]
    assert header(folder / "migrations.csv")[:2] == ["sha", "repo"]
    assert (folder / "changed_files.csv").read_text().count("\n") == 3  # header + 2 files
    assert header(folder / "validation_v2" / "sample.csv") == ["n", "url", "is_migration"]
    assert not (folder / "validation_v2" / "sample.numbers").exists()
    everything = "".join(p.read_text("utf-8") for p in folder.rglob("*") if p.is_file())
    assert "example.com" not in everything
    sums = (folder / "SHA256SUMS").read_text().splitlines()
    assert any(line.endswith("  candidates.csv") for line in sums)
    archive = out / "modelbump-migrations-9.9.9.zip"
    with zipfile.ZipFile(archive) as z:
        assert "modelbump-migrations-9.9.9/README.md" in z.namelist()
    first = archive.read_bytes()
    assert main(["--data", str(data), "--out", str(out), "--version", "9.9.9"]) == 0
    assert archive.read_bytes() == first  # the same data gives the same zip
