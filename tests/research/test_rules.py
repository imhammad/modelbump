"""Tests for the migration rules, mostly with real commit messages from the mining run."""

from datetime import date

import pytest

from research.filtering.rules import (
    after_notice_start,
    commit_direction,
    direction,
    has_ai_style,
    has_ai_trailer,
    has_migration_word,
    is_bot,
)


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Migrated to the new model", True),
        ("replacing the model", True),
        ("Shut down old endpoint", True),
        ("model shutdown next week", True),
        ("Deprecation notice", True),
        ("add a dropdown for models", False),
        ("feat: add quick model selection commands", False),
    ],
)
def test_migration_word_in_any_form(message: str, expected: bool) -> None:
    assert has_migration_word(message) is expected


@pytest.mark.parametrize(
    ("message", "model_id", "expected"),
    [
        # Real messages from the candidates (Step 10 run).
        (
            "fix: update gemini model from deprecated gemini-2.0-flash to gemini-2.5-flash",
            "gemini-2.0-flash",
            "away",
        ),
        ("docs: update OpenAI model name from o3-mini to o4-mini", "o3-mini", "away"),
        ("chore: revert to gemini-2.0-flash", "gemini-2.0-flash", "into"),
        ("fix(agent): update Gemini model to gemini-2.0-flash", "gemini-2.0-flash", "into"),
        ("switch embeddings to Gemini text-embedding-004", "text-embedding-004", "into"),
        (
            "Update model configuration to use 'gpt-4.1-nano' for improved performance",
            "gpt-4.1-nano",
            "into",
        ),
        (
            "fix: migrate4.php - correct gemini_model default to gemini-2.0-flash on production",
            "gemini-2.0-flash",
            "into",
        ),
        (
            "feat: enhance Gemini AI client with multi-model fallback (gemini-2.0-flash)",
            "gemini-2.0-flash",
            "unclear",
        ),
        # Other common shapes.
        ("Replace gpt-4 with gpt-5.6-sol", "gpt-4", "away"),
        ("Replace `claude-2.1` with claude-sonnet-4-5", "claude-2.1", "away"),
        ("remove claude-2.1 support", "claude-2.1", "away"),
        ("Drop support for gpt-4-32k", "gpt-4-32k", "away"),
        ("gpt-4 -> gpt-4o", "gpt-4", "away"),
        ("model: gpt-4 → gpt-5.6-sol", "gpt-4", "away"),
        ("claude-3-opus-20240229 is deprecated, moving on", "claude-3-opus-20240229", "away"),
        ("Bump default model gpt-4 to gpt-4o", "gpt-4", "away"),
        ("set model to gpt-4 to save cost", "gpt-4", "into"),
        ("gpt-4o -> gpt-4", "gpt-4", "into"),
        ("Replace the summariser with gpt-4", "gpt-4", "into"),
        ("Use gpt-4o instead", "gpt-4", "unclear"),  # not the same ID
    ],
)
def test_direction(message: str, model_id: str, expected: str) -> None:
    assert direction(message, model_id) == expected


def test_commit_direction_prefers_away() -> None:
    # Both are retired: the commit moves away from gpt-4 and into gpt-4-turbo.
    message = "Migrate from gpt-4 to gpt-4-turbo"
    assert direction(message, "gpt-4-turbo") == "into"
    assert commit_direction(message, ["gpt-4", "gpt-4-turbo"]) == "away"
    assert commit_direction("use gpt-4", ["gpt-4"]) == "into"
    assert commit_direction("about gpt-4", ["gpt-4"]) == "unclear"


def test_after_notice_start() -> None:
    starts = {"gpt-4": date(2026, 3, 23), "gpt-4-turbo": date(2025, 1, 1)}
    assert after_notice_start(date(2026, 3, 23), ["gpt-4"], starts) is True
    assert after_notice_start(date(2026, 3, 22), ["gpt-4"], starts) is False
    # The earliest start among the commit's IDs counts.
    assert after_notice_start(date(2025, 6, 1), ["gpt-4", "gpt-4-turbo"], starts) is True
    assert after_notice_start(date(2025, 6, 1), ["gemini-2.0-flash"], starts) is None


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("fix\n\nCo-Authored-By: Claude Opus <noreply@anthropic.com>", True),
        ("fix\n\nCo-authored-by: Copilot <copilot@github.com>", True),
        ("fix\n\n🤖 Generated with [Claude Code](https://claude.com/claude-code)", True),
        ("fix\n\nCo-authored-by: Jane Doe <jane@example.com>", False),
        ("Generated the docs", False),
    ],
)
def test_ai_trailer(message: str, expected: bool) -> None:
    assert has_ai_trailer(message) is expected


def test_ai_style() -> None:
    # Real case: a chat reply pasted as the commit message.
    assert has_ai_style("I'll help you implement the changes. The diffs look comprehensive")
    assert not has_ai_style("fix: I'll do it later")


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Bump openai from 1.0.0 to 1.2.0", True),
        ("chore(deps): update dependency x (#12)\n\nSigned-off-by: renovate[bot]", True),
        ("Bumps [openai] ... dependabot", True),
        ("Bump default model gpt-4 to gpt-4o", False),
    ],
)
def test_bot(message: str, expected: bool) -> None:
    assert is_bot(message) is expected
