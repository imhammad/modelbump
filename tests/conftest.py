"""Shared test setup."""

from pathlib import Path

import pytest

# Demo apps that tests read as data. Their own tests are not ModelBump's tests.
collect_ignore_glob = ["fixtures/*"]


@pytest.fixture(autouse=True)
def _private_cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every test's model-answer cache in its own temporary folder."""
    monkeypatch.setenv("MODELBUMP_CACHE_DIR", str(tmp_path / "modelbump-cache"))
