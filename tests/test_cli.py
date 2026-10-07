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
