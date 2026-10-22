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


def test_scan_lists_findings_with_their_status(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text('MODEL = "claude-3-haiku-20240307"\nOTHER = "gpt-9-turbo"\n')
    result = runner.invoke(app, ["scan", str(tmp_path)])
    assert result.exit_code == 0
    assert "app.py:1:10  claude-3-haiku-20240307  retired" in result.stdout
    assert "app.py:2:10  gpt-9-turbo  not in registry" in result.stdout
    assert "Found 2 model IDs in 1 file (scanned 1 file)." in result.stdout


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
