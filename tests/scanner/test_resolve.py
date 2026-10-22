"""Tests for mapping cloud forms of a model ID to the registry ID."""

import pytest

from modelbump.registry import load_registry
from modelbump.scanner import resolve


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("claude-3-haiku-20240307", "claude-3-haiku-20240307"),
        ("claude-3-haiku-20240307-v1", "claude-3-haiku-20240307"),
        ("claude-3-haiku-20240307-v2", "claude-3-haiku-20240307"),
        ("claude-3-5-sonnet@20240620", "claude-3-5-sonnet-20240620"),
        ("gpt-4o", None),
        ("gpt-9-v1", None),
        ("claude-9@20990101", None),
    ],
)
def test_resolve(written: str, expected: str | None) -> None:
    assert resolve(written, load_registry()) == expected
