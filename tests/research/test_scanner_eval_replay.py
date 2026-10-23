"""Tests for replaying the scanner on the evaluation snapshots. No network is used."""

import json
from datetime import date
from pathlib import Path

import pytest

from modelbump.registry import load_registry
from research.filtering.filter import write_jsonl
from research.scanner_eval.replay import (
    detected,
    first_failure,
    first_warning,
    main,
    replay_rows,
    spread,
    summarise,
)
from research.scanner_eval.rescore import rescan

REGISTRY = load_registry()
# claude-3-haiku-20240307: notice 2026-02-19, shutdown 2026-04-20.
# gpt-3.5-turbo-0613: notice 2023-11-06, shutdown 2024-09-13.
# gemini-3-pro-preview: no notice date, shutdown 2026-03-09.
SNAPSHOTS = {
    "aaa": {"app.py": 'MODEL = "claude-3-haiku-20240307"\n'},
    "bbb": {
        "app.py": "# was gpt-3.5-turbo-0613\n",
        "tests/test_x.py": 'M = "gpt-3.5-turbo-0613"\n',
    },
    "ccc": {"app.py": 'MODEL = "gpt-4o"\n'},
    "ddd": {"svc.py": 'MODEL = "gemini-3-pro-preview"\n'},
}
COMMITS = [
    {"sha": "aaa", "repo": "a/a", "model_id": "claude-3-haiku-20240307"},
    {"sha": "bbb", "repo": "b/b", "model_id": "gpt-3.5-turbo-0613"},
    {"sha": "ccc", "repo": "c/c", "model_id": "gpt-3.5-turbo-0613"},
    {"sha": "ddd", "repo": "d/d", "model_id": "gemini-3-pro-preview"},
    {"sha": "eee", "repo": "e/e", "model_id": "not-a-model"},
]
COMMITTED = {
    "aaa": date(2026, 5, 1),  # 11 days after the shutdown
    "bbb": date(2024, 1, 5),  # 60 days after the notice
    "ccc": date(2024, 1, 5),
    "ddd": date(2026, 3, 1),
    "eee": date(2026, 1, 1),
}


def make_snapshots(folder: Path) -> None:
    for sha, files in SNAPSHOTS.items():
        for path, text in files.items():
            target = folder / "snapshots" / sha / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)


def test_first_warning_is_the_notice_day() -> None:
    assert first_warning(
        "claude-3-haiku-20240307", REGISTRY, date(2024, 1, 1), date(2026, 5, 1)
    ) == date(2026, 2, 19)
    # Not announced yet on the end day.
    assert (
        first_warning("claude-3-haiku-20240307", REGISTRY, date(2024, 1, 1), date(2026, 1, 1))
        is None
    )
    # Known from the start.
    start = date(2026, 3, 1)
    assert first_warning("claude-3-haiku-20240307", REGISTRY, start, date(2026, 5, 1)) == start
    assert first_warning("gpt-4o", REGISTRY, start, date(2026, 5, 1)) is None


def test_first_failure() -> None:
    assert first_failure("claude-3-haiku-20240307", REGISTRY, 30) == date(2026, 3, 21)
    assert first_failure("gpt-4o", REGISTRY, 30) is None


def test_detected_follows_the_settings(tmp_path: Path) -> None:
    make_snapshots(tmp_path)
    findings = rescan(COMMITS[:2], tmp_path / "snapshots", REGISTRY)
    assert detected("gpt-3.5-turbo-0613", "bbb", findings, REGISTRY, "all")
    assert detected("gpt-3.5-turbo-0613", "bbb", findings, REGISTRY, "skip_comments")
    assert detected("gpt-3.5-turbo-0613", "bbb", findings, REGISTRY, "skip_tests")
    assert not detected("gpt-3.5-turbo-0613", "bbb", findings, REGISTRY, "both")
    assert not detected("gpt-3.5-turbo-0613", "aaa", findings, REGISTRY, "all")
    assert not detected("not-a-model", "bbb", findings, REGISTRY, "all")


def test_replay_rows_and_summary(tmp_path: Path) -> None:
    make_snapshots(tmp_path)
    findings = rescan(COMMITS, tmp_path / "snapshots", REGISTRY)
    rows = replay_rows(COMMITS, COMMITTED, findings, REGISTRY)
    by_sha = {r["sha"]: r for r in rows}
    assert set(by_sha) == {"aaa", "bbb", "ccc", "ddd"}  # eee's model is not in the registry
    a = by_sha["aaa"]
    assert a["migrated_after_shutdown"] is True
    assert a["first_warning"] == "2026-02-19"
    assert a["warning_days_before_migration"] == 71
    assert a["failure_days_before_migration"] == 41
    assert by_sha["bbb"]["warning_days_before_migration"] == 60
    assert by_sha["ccc"]["detected_all"] is False
    # No notice date: flagged, but no first warning day to count from.
    assert by_sha["ddd"]["detected_all"] is True
    assert by_sha["ddd"]["first_warning"] is None
    result = summarise(rows)
    everything = result["settings"]["all"]
    assert everything["flagged"] == 3
    assert everything["with_notice"] == 2
    assert everything["warning_days_before_migration"]["median"] == pytest.approx(65.5)
    assert everything["migrated_after_shutdown"] == 1
    assert everything["failure_days_before_late_migration"]["median"] == 41
    assert result["settings"]["both"]["flagged"] == 2


def test_spread_of_nothing() -> None:
    assert spread([])["median"] is None
    assert spread([5])["median"] == 5


def test_main(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "eval"
    timing = tmp_path / "timing.jsonl"
    assert main(["--dir", str(out), "--timing", str(timing)]) == 1
    assert "not found" in capsys.readouterr().err
    make_snapshots(out)
    write_jsonl(COMMITS, out / "commits.jsonl")
    write_jsonl(
        [{"sha": sha, "committed": day.isoformat()} for sha, day in COMMITTED.items()], timing
    )
    # A file fetched for a missed site counts too.
    (out / "extra" / "ccc").mkdir(parents=True)
    (out / "extra" / "ccc" / "index.html").write_text('<script>m = "gpt-3.5-turbo-0613"</script>\n')
    assert main(["--dir", str(out), "--timing", str(timing)]) == 0
    printed = capsys.readouterr().out
    assert "Commits replayed: 4" in printed
    assert "--fail-within 30 would have failed CI a median of 41 days" in printed
    written = json.loads((out / "replay.json").read_text())
    assert written["settings"]["all"]["flagged"] == 4
    assert (out / "replay.jsonl").exists()
