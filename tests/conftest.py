"""Shared test setup."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _private_cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every test's model-answer cache in its own temporary folder."""
    monkeypatch.setenv("MODELBUMP_CACHE_DIR", str(tmp_path / "modelbump-cache"))
