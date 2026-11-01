"""Tests for finding the models that are due, and for `modelbump bump-all`."""

from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from modelbump.bump import DueModel, due_line, due_models
from modelbump.cli import app
from modelbump.registry import load_registry
from tests.bump.conftest import FakeGh, git

runner = CliRunner()
APP = (
    'SUMMARY = "claude-3-haiku-20240307"\n'
    "# claude-3-5-haiku-20241022 in a comment only\n"
    'FAST = "gpt-3.5-turbo-0613"\n'
    'LATER = "gpt-5.1"\n'
    'OTHER = "gpt-9-turbo"\n'
)


def test_due_models_uses_code_not_comments(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(APP)
    due = due_models(tmp_path, load_registry(), date(2026, 11, 1))
    assert [(m.old, m.new, m.reason) for m in due] == [
        (
            "gpt-3.5-turbo-0613",
            None,
            "the suggested replacement gpt-3.5-turbo is retired too",
        ),
        ("claude-3-haiku-20240307", "claude-haiku-4-5-20251001", None),
    ]


def test_within_sets_the_window(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(APP)
    due = due_models(tmp_path, load_registry(), date(2026, 11, 1), within=200)
    assert [m.old for m in due][-1] == "gpt-5.1"
    assert due[-1].new == "gpt-6-sol"


def test_due_line() -> None:
    model = DueModel("a-1", "b-2", date(2026, 12, 1), 30, 2)
    assert due_line(model) == "a-1 -> b-2 (shuts down 2026-12-01, in 30 days, 2 places)"
    gone = DueModel("a-1", None, date(2026, 1, 1), -5, 1, "no")
    assert due_line(gone) == "a-1 -> ? (shut down 2026-01-01, 1 place)"


def test_bump_all_dry_run(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(APP)
    result = runner.invoke(app, ["bump-all", str(tmp_path), "--today", "2026-11-01"])
    assert result.exit_code == 0
    assert result.stdout.splitlines() == [
        "gpt-3.5-turbo-0613 -> ? (shut down 2024-09-13, 1 place)",
        "  skipped: the suggested replacement gpt-3.5-turbo is retired too",
        "claude-3-haiku-20240307 -> claude-haiku-4-5-20251001 (shut down 2026-04-20, 1 place)",
        "  would change 1 place in 1 file",
        "Nothing was changed. Add --open-pr to open one pull request per model.",
    ]
    assert (tmp_path / "app.py").read_text() == APP


def test_bump_all_with_nothing_due(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text('M = "gpt-9-turbo"\n')
    result = runner.invoke(app, ["bump-all", str(tmp_path)])
    assert result.exit_code == 0
    assert result.stdout == "No model the code uses is retired or shuts down within 90 days.\n"


def test_bump_all_opens_one_pr_per_model_and_never_twice(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gh = FakeGh()
    monkeypatch.setattr("modelbump.bump.pr._run", gh)
    args = ["bump-all", str(repo), "--today", "2026-11-01", "--open-pr"]
    first = runner.invoke(app, args)
    assert first.exit_code == 0, first.output
    assert "  opened https://github.com/o/r/pull/7" in first.stdout
    assert first.stdout.splitlines()[-1] == "Due: 1 model; opened 1 pull request, skipped 0."
    assert git(repo, "branch", "--show-current") == "main"
    assert gh.body.startswith("## Bump `claude-3-haiku-20240307` to `claude-haiku-4-5-20251001`")
    # The next scheduled run finds the branch and opens nothing.
    second = runner.invoke(app, args)
    assert second.exit_code == 0
    assert "already on origin" in second.stdout or "already exists" in second.stdout
    assert second.stdout.splitlines()[-1] == "Due: 1 model; opened 0 pull requests, skipped 1."
    assert sum(call[:3] == ["gh", "pr", "create"] for call in gh.calls) == 1


def test_bump_all_stops_on_a_dirty_tree(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("modelbump.bump.pr._run", FakeGh())
    (repo / "notes.txt").write_text("work in progress\n")
    result = runner.invoke(app, ["bump-all", str(repo), "--today", "2026-11-01", "--open-pr"])
    assert result.exit_code == 1
    assert "working tree has changes" in result.stderr
