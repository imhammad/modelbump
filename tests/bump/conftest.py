"""Shared helpers for the bump tests: a real git repository with a local remote, and a fake gh."""

import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

OLD = "claude-3-haiku-20240307"


def git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return done.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for key in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(key, "Test")
    for key in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(key, "test@example.com")
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "--quiet", "--bare", str(remote))
    app = tmp_path / "app"
    app.mkdir()
    git(app, "init", "--quiet", "--initial-branch", "main")
    (app / "app.py").write_text(f'MODEL = "{OLD}"\n')
    git(app, "add", "app.py")
    git(app, "commit", "--quiet", "--message", "init")
    git(app, "remote", "add", "origin", str(remote))
    git(app, "push", "--quiet", "origin", "main")
    return app


class FakeGh:
    """Runs git for real; answers gh like the GitHub CLI would."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.body = ""

    def __call__(self, args: Sequence[str], cwd: Path) -> "subprocess.CompletedProcess[str]":
        args = list(args)
        if args[0] != "gh":
            return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)
        self.calls.append(args)
        if "--body-file" in args:
            self.body = Path(args[args.index("--body-file") + 1]).read_text()
        out = "gh version 2.0\n" if args[1] == "--version" else "https://github.com/o/r/pull/7\n"
        return subprocess.CompletedProcess(args, 0, out, "")
