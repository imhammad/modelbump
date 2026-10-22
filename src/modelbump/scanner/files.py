"""Choose which files in a repository to scan, and read them as text."""

import os
from collections.abc import Iterator
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

MAX_BYTES = 1_000_000
_BINARY_PROBE = 8192


def is_scannable(path: Path) -> bool:
    """Return True if a file's name says it is code or configuration."""
    name = path.name
    if name in SKIP_NAMES:
        return False
    # .env, .env.example, .env.local, ...
    if name == ".env" or name.startswith(".env."):
        return True
    return path.suffix.lower() in SCAN_SUFFIXES


def iter_source_files(root: Path) -> Iterator[Path]:
    """Yield every scannable file under ``root``, in a stable sorted order.

    Symbolic links are never followed, so a scan cannot leave the repository.
    """
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if not path.is_symlink() and is_scannable(path):
                yield path


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
