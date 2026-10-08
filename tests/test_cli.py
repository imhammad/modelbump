"""Smoke tests for the command-line interface."""

from typer.testing import CliRunner

from modelbump import __version__
from modelbump.cli import app

runner = CliRunner()


def test_version_flag_prints_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == f"modelbump {__version__}"


def test_scan_command_exists() -> None:
    result = runner.invoke(app, ["scan", "."])
    assert result.exit_code == 0
    assert "not implemented yet" in result.stdout


def test_check_known_retired_model() -> None:
    result = runner.invoke(app, ["check", "claude-3-haiku-20240307"])
    assert result.exit_code == 0
    assert "(anthropic): RETIRED since 2026-04-20." in result.stdout
    assert "Suggested replacement: claude-haiku-4-5-20251001" in result.stdout


def test_check_unknown_model() -> None:
    result = runner.invoke(app, ["check", "not-a-real-model"])
    assert result.exit_code == 0
    assert "not in the registry" in result.stdout
