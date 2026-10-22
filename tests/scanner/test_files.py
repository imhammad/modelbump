"""Tests for choosing and reading the files to scan."""

from pathlib import Path

import pytest

from modelbump.scanner import iter_source_files, read_source
from modelbump.scanner.files import MAX_BYTES, is_scannable


@pytest.mark.parametrize(
    "name",
    ["app.py", "index.ts", "App.tsx", "config.yaml", "settings.toml", ".env", ".env.example"],
)
def test_code_and_config_are_scanned(name: str) -> None:
    assert is_scannable(Path(name))


@pytest.mark.parametrize(
    "name", ["README.md", "notes.txt", "logo.png", "package-lock.json", "uv.lock", "Makefile"]
)
def test_docs_binaries_and_lock_files_are_not(name: str) -> None:
    assert not is_scannable(Path(name))


def test_walk_skips_tool_folders_and_is_sorted(tmp_path: Path) -> None:
    for rel in ["src/b.py", "src/a.py", "node_modules/x/index.js", ".venv/lib/y.py", "README.md"]:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x = 1\n")
    found = [p.relative_to(tmp_path).as_posix() for p in iter_source_files(tmp_path)]
    assert found == ["src/a.py", "src/b.py"]


def test_walk_does_not_follow_symlinks(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.py").write_text("x = 1\n")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "linked").symlink_to(outside, target_is_directory=True)
    (repo / "link.py").symlink_to(outside / "secret.py")
    assert list(iter_source_files(repo)) == []


def test_read_source_skips_big_and_binary_files(tmp_path: Path) -> None:
    big = tmp_path / "big.json"
    big.write_text("x" * (MAX_BYTES + 1))
    binary = tmp_path / "data.json"
    binary.write_bytes(b"\x00\x01gpt-4o")
    text = tmp_path / "ok.py"
    text.write_bytes(b"model = 'gpt-4o' # caf\xe9\n")
    assert read_source(big) is None
    assert read_source(binary) is None
    assert read_source(text) == "model = 'gpt-4o' # caf�\n"
    assert read_source(tmp_path / "missing.py") is None


@pytest.mark.parametrize(
    ("patterns", "expected"),
    [
        ((), ["app.py", "nb/a.ipynb", "src/main.py", "src/fixtures/x.py", "tests/test_a.py"]),
        (("tests",), ["app.py", "nb/a.ipynb", "src/main.py", "src/fixtures/x.py"]),
        (("tests/",), ["app.py", "nb/a.ipynb", "src/main.py", "src/fixtures/x.py"]),
        (("*.ipynb",), ["app.py", "src/main.py", "src/fixtures/x.py", "tests/test_a.py"]),
        (("*/fixtures", "app.py"), ["nb/a.ipynb", "src/main.py", "tests/test_a.py"]),
        (("src/main.py",), ["app.py", "nb/a.ipynb", "src/fixtures/x.py", "tests/test_a.py"]),
    ],
)
def test_walk_skips_excluded_paths(
    tmp_path: Path, patterns: tuple[str, ...], expected: list[str]
) -> None:
    for rel in ["app.py", "nb/a.ipynb", "src/main.py", "src/fixtures/x.py", "tests/test_a.py"]:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x = 1\n")
    found = [p.relative_to(tmp_path).as_posix() for p in iter_source_files(tmp_path, patterns)]
    assert found == expected
