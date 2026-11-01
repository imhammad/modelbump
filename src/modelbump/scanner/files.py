"""Choose which files in a repository to scan, and read them as text."""

import fnmatch
import os
import re
from collections.abc import Iterator, Sequence
from pathlib import Path

# Folders that hold tools, caches, build output or other people's code.
SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "node_modules",
        "site-packages",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".nox",
        "dist",
        "build",
        ".next",
        ".nuxt",
        "coverage",
        # ModelBump's own evidence (ADR 0070): it names the old model on purpose.
        ".modelbump",
    }
)

# Source code and configuration. Docs (.md, .rst, .txt) are left out for now:
# a README that mentions a model is not a dependency (ADR 0023).
SCAN_SUFFIXES = frozenset(
    {
        # Python
        ".py",
        ".pyi",
        ".ipynb",
        # JavaScript and TypeScript
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".ts",
        ".tsx",
        ".mts",
        ".cts",
        # Other languages that call LLM APIs
        ".go",
        ".java",
        ".kt",
        ".rb",
        ".rs",
        ".cs",
        ".php",
        ".swift",
        ".sh",
        ".ex",
        ".exs",
        # Web pages often set a model in an inline script.
        ".html",
        ".htm",
        # Configuration
        ".json",
        ".jsonc",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".conf",
        ".env",
    }
)

# Lock files list package names such as gpt-3-encoder, never model choices.
SKIP_NAMES = frozenset(
    {"package-lock.json", "pnpm-lock.yaml", "yarn.lock", "uv.lock", "poetry.lock", "Cargo.lock"}
)

# Example env files without a leading dot (same names as in scanner.context).
ENV_EXAMPLE_NAMES = frozenset({"env.example", "env.sample", "env.template", "example.env"})

# Test folders and test file names in the common languages (ADR 0031).
_TEST_PATH = re.compile(
    r"(^|/)(tests?|__tests__|__mocks__|specs?|testdata|fixtures|e2e)/"
    r"|(^|/)(test_[^/]*\.py|[^/]*_test\.(py|go|rb|exs?)|conftest\.py)$"
    r"|(^|/)[^/]+\.(test|spec)\.[a-z]+$"
    r"|(^|/)[^/]*Tests?\.(java|kt|cs|swift|php)$"
)

MAX_BYTES = 1_000_000
_BINARY_PROBE = 8192


def is_scannable(path: Path) -> bool:
    """Return True if a file's name says it is code or configuration."""
    name = path.name
    if name in SKIP_NAMES:
        return False
    # .env, .env.example, .env.local, ...
    if name == ".env" or name.startswith(".env.") or name in ENV_EXAMPLE_NAMES:
        return True
    return path.suffix.lower() in SCAN_SUFFIXES


def is_test_path(rel_path: str) -> bool:
    """Return True if a ``/``-separated path is a test file or sits in a test folder."""
    return _TEST_PATH.search(rel_path) is not None


def is_excluded(rel_path: str, exclude: Sequence[str]) -> bool:
    """Return True if a path relative to the scan root matches an exclude pattern.

    Patterns use shell wildcards on the whole ``/``-separated path, and ``*``
    also matches ``/``: ``tests`` drops the tests folder, ``*.ipynb`` drops
    every notebook, and ``src/*/fixtures`` drops those folders at any depth.
    """
    return any(fnmatch.fnmatchcase(rel_path, pattern.strip("/")) for pattern in exclude)


def iter_source_files(root: Path, exclude: Sequence[str] = ()) -> Iterator[Path]:
    """Yield every scannable file under ``root``, in a stable sorted order.

    Folders and files matching an ``exclude`` pattern are skipped. Symbolic
    links are never followed, so a scan cannot leave the repository.
    """
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        base = Path(dirpath)
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d not in SKIP_DIRS and not is_excluded(_relative(base / d, root), exclude)
        )
        for name in sorted(filenames):
            path = base / name
            if (
                not path.is_symlink()
                and is_scannable(path)
                and not is_excluded(_relative(path, root), exclude)
            ):
                yield path


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def read_source(path: Path) -> str | None:
    """Return a file's text, or None if it is too big or looks binary."""
    try:
        if path.stat().st_size > MAX_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:_BINARY_PROBE]:
        return None
    return data.decode("utf-8", errors="replace")
