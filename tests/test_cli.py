"""Smoke tests for the command-line interface."""

from pathlib import Path

from typer.testing import CliRunner

from modelbump import __version__
from modelbump.cli import app

runner = CliRunner()


def test_version_flag_prints_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == f"modelbump {__version__}"


def test_scan_lists_findings_with_their_severity(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(
        'A = "claude-3-haiku-20240307"\n'
        'B = "gpt-9-turbo"\n'
        'C = "anthropic.claude-3-haiku-20240307-v1:0"\n'
        'D = "gpt-5.1"\n'
        'E = "gemini-3.1-flash-lite"\n'
    )
    result = runner.invoke(app, ["scan", str(tmp_path), "--today", "2026-10-22"])
    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    assert lines == [
        "app.py:1:6  claude-3-haiku-20240307  RETIRED  shut down on 2026-04-20; "
        "suggested replacement claude-haiku-4-5-20251001",
        "app.py:2:6  gpt-9-turbo  UNKNOWN  no retirement announced",
        "app.py:3:16  claude-3-haiku-20240307-v1 (= claude-3-haiku-20240307)  RETIRED  "
        "shut down on 2026-04-20; suggested replacement claude-haiku-4-5-20251001",
        "app.py:4:6  gpt-5.1  DEPRECATED  shuts down on 2027-04-01 (in 161 days); "
        "suggested replacement gpt-6-sol",
        "app.py:5:6  gemini-3.1-flash-lite  DEPRECATED  shuts down no earlier than 2027-05-07 "
        "(in 197 days); suggested replacement gemini-3.5-flash-lite",
        "Found 5 model IDs in 1 file (scanned 1 file): 2 RETIRED, 2 DEPRECATED, 1 UNKNOWN.",
    ]


def test_scan_soon_days_sets_the_warning_window(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text('D = "gpt-5.1"\n')
    result = runner.invoke(
        app, ["scan", str(tmp_path), "--today", "2026-10-22", "--soon-days", "200"]
    )
    assert result.exit_code == 0
    assert "gpt-5.1  RETIRING_SOON  shuts down on 2027-04-01 (in 161 days)" in result.stdout


def test_scan_fail_within_sets_the_exit_code(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text('A = "claude-3-haiku-20240307"\nD = "gpt-5.1"\n')
    args = ["scan", str(tmp_path), "--today", "2026-10-22", "--fail-within"]
    retired_only = runner.invoke(app, [*args, "30"])
    assert retired_only.exit_code == 1
    assert "Failed: 1 model ID is retired or shut down within 30 days." in retired_only.stdout
    both = runner.invoke(app, [*args, "161"])
    assert both.exit_code == 1
    assert "Failed: 2 model IDs are retired or shut down within 161 days." in both.stdout
    before_notices = ["scan", str(tmp_path), "--today", "2026-01-01", "--fail-within", "30"]
    clean = runner.invoke(app, before_notices)
    assert clean.exit_code == 0


def test_scan_before_the_notice_is_unknown(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text('A = "claude-3-haiku-20240307"\n')
    result = runner.invoke(
        app, ["scan", str(tmp_path), "--today", "2026-02-18", "--fail-within", "0"]
    )
    assert result.exit_code == 0
    assert "claude-3-haiku-20240307  UNKNOWN  no retirement announced" in result.stdout


def test_scan_rejects_a_bad_date(tmp_path: Path) -> None:
    result = runner.invoke(app, ["scan", str(tmp_path), "--today", "22/10/2026"])
    assert result.exit_code == 2


def test_scan_reports_when_nothing_is_found(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("print('hello')\n")
    (tmp_path / "big.json").write_text("x" * 1_000_001)
    result = runner.invoke(app, ["scan", str(tmp_path)])
    assert result.exit_code == 0
    assert "No model IDs found (scanned 1 file, skipped 1 too big or binary)." in result.stdout


def test_scan_rejects_a_missing_path(tmp_path: Path) -> None:
    result = runner.invoke(app, ["scan", str(tmp_path / "nope")])
    assert result.exit_code == 2


def test_check_known_retired_model() -> None:
    result = runner.invoke(app, ["check", "claude-3-haiku-20240307"])
    assert result.exit_code == 0
    assert "(anthropic): RETIRED since 2026-04-20." in result.stdout
    assert "Suggested replacement: claude-haiku-4-5-20251001" in result.stdout


def test_check_unknown_model() -> None:
    result = runner.invoke(app, ["check", "not-a-real-model"])
    assert result.exit_code == 0
    assert "not in the registry" in result.stdout


def test_check_rescheduled_model() -> None:
    result = runner.invoke(app, ["check", "gpt-4-0314"])
    assert result.exit_code == 0
    assert "(openai): RETIRED since 2026-03-26." in result.stdout
    assert "Rescheduled: 1 earlier plan(s) were replaced." in result.stdout


def test_check_earliest_possible_date() -> None:
    result = runner.invoke(app, ["check", "gemini-2.0-flash"])
    assert result.exit_code == 0
    assert "RETIRED since 2026-06-01 (the earliest possible date" in result.stdout
