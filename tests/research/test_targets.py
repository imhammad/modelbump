"""Tests for finding the model a migration moves to."""

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from modelbump.registry import Provider, ProviderFile, Registry, RetiredModel, load_registry
from research.enrichment.targets import (
    base,
    change,
    destination,
    extract_target,
    family,
    follows,
    line,
    main,
    model_tokens,
    provider_of,
    run,
    same_model,
    target_row,
    tier,
    version,
)

GPT4 = RetiredModel(
    id="gpt-4-0613",
    aliases=("gpt-4",),
    announced=date(2026, 3, 1),
    shutdown=date(2026, 6, 1),
    replacement="gpt-5.6-sol",
)
GPT4O = RetiredModel(id="gpt-4o-2024-05-13", announced=date(2026, 5, 1), shutdown=date(2026, 11, 1))
SONNET = RetiredModel(
    id="claude-3-5-sonnet-20241022",
    announced=date(2025, 8, 13),
    shutdown=date(2025, 10, 28),
    replacement="claude-sonnet-4-6",
)
DAVINCI = RetiredModel(
    id="text-davinci-003",
    announced=date(2023, 7, 6),
    shutdown=date(2024, 1, 4),
    replacement="gpt-3.5-turbo-instruct",
)
FLASH = RetiredModel(id="gemini-2.0-flash", shutdown=date(2026, 3, 1), shutdown_is_earliest=True)


def registry() -> Registry:
    def source(provider: Provider, *models: RetiredModel) -> ProviderFile:
        return ProviderFile(
            provider=provider,
            source_url="https://example.com/deprecations",  # type: ignore[arg-type]
            retrieved=date(2026, 10, 8),
            models=models,
        )

    return Registry(
        [
            source(Provider.OPENAI, GPT4, GPT4O, DAVINCI),
            source(Provider.ANTHROPIC, SONNET),
            source(Provider.GOOGLE, FLASH),
        ]
    )


def commit(
    message: str, ids: tuple[str, ...] = ("gpt-4",), day: str = "2026-07-01", repo: str = "a/b"
) -> dict[str, Any]:
    return {
        "sha": f"{repo}-{day}-{message[:8]}",
        "repo": repo,
        "url": f"https://github.com/{repo}/commit/x",
        "committed_at": f"{day}T12:00:00Z",
        "message": message,
        "matched_ids": list(ids),
        "migration_away": True,
    }


def test_model_tokens_skip_tools_and_keep_order() -> None:
    text = (
        "Use GPT-4o-mini and gemini-pro, not claude-code or gpt-engineer; "
        "o3-mini-2025-01-31, llama3.1, text-embedding-3-small and qwen2.5-coder. gpt-4o-mini."
    )
    assert model_tokens(text) == [
        "gpt-4o-mini",
        "gemini-pro",
        "o3-mini-2025-01-31",
        "llama3.1",
        "text-embedding-3-small",
        "qwen2.5-coder",
    ]


@pytest.mark.parametrize(
    ("model_id", "expected"),
    [
        ("claude-3-5-sonnet-20241022", "claude-3-5-sonnet"),
        ("o3-mini-2025-01-31", "o3-mini"),
        ("gpt-4-0613", "gpt-4"),
        ("gemini-2.5-flash-lite-preview-09-2025", "gemini-2.5-flash-lite"),
        ("gemini-2.5-pro-preview-03-25", "gemini-2.5-pro"),
        ("GPT-4o.", "gpt-4o"),
    ],
)
def test_base(model_id: str, expected: str) -> None:
    assert base(model_id) == expected


@pytest.mark.parametrize(
    ("model_id", "expected"),
    [
        ("claude-3-5-sonnet-20241022", "claude-sonnet"),
        ("claude-sonnet-4-6", "claude-sonnet"),
        ("gpt-4o-mini", "gpt-mini"),
        ("gpt-5-mini-2025-08-07", "gpt-mini"),
        ("o4-mini", "o-mini"),
        ("gemini-2.0-flash-001", "gemini-flash"),
        ("gpt-4-32k", "gpt"),
    ],
)
def test_line(model_id: str, expected: str) -> None:
    assert line(model_id) == expected


@pytest.mark.parametrize(
    ("model_id", "expected"),
    [
        ("gpt-3.5-turbo-0125", 3.5),
        ("gpt-4-32k", 4.0),
        ("gpt-4o", 4.0),
        ("claude-3-5-sonnet-20241022", 3.5),
        ("claude-sonnet-4-5-20250929", 4.5),
        ("claude-opus-4-1-20250805", 4.1),
        ("gemini-2.0-flash", 2.0),
        ("o3-mini", 3.0),
        ("text-davinci", None),
    ],
)
def test_version(model_id: str, expected: float | None) -> None:
    assert version(model_id) == expected


@pytest.mark.parametrize(
    ("model_id", "expected"),
    [
        ("gpt-4o-mini", "small"),
        ("gemini-2.0-flash-lite", "small"),
        ("claude-3-5-haiku-20241022", "small"),
        ("gemini-2.5-pro", "large"),
        ("claude-3-opus-20240229", "large"),
        ("gemini-2.0-flash", "standard"),
        ("gpt-4", "standard"),
    ],
)
def test_tier(model_id: str, expected: str) -> None:
    assert tier(model_id) == expected


def test_family_and_change() -> None:
    assert family("o3-mini") == "o"
    assert family("text-embedding-3-small") == "embedding"
    assert change(3.5, 4.0) == "up"
    assert change(4.0, 4.0) == "same"
    assert change(2.5, 2.0) == "down"
    assert change(None, 2.0) == "unknown"


def test_provider_of() -> None:
    reg = registry()
    assert provider_of("gpt-4", reg) == "openai"
    assert provider_of("claude-sonnet-4-6", reg) == "anthropic"
    assert provider_of("text-embedding-004", reg) == "google"
    assert provider_of("text-embedding-3-small", reg) == "openai"
    assert provider_of("llama3.1", reg) == "meta"
    assert provider_of("qwen2.5-coder", reg) == "alibaba"
    assert provider_of("something-else", reg) is None


def test_same_model() -> None:
    reg = registry()
    assert same_model("gpt-4", "gpt-4-0613", reg)
    assert same_model("claude-sonnet-4-6", "claude-sonnet-4-6-20260101", reg)
    assert not same_model("gpt-4", "gpt-4o", reg)


@pytest.mark.parametrize(
    ("message", "left", "target", "method"),
    [
        ("Migrate from gpt-4 to gpt-4o", "gpt-4", "gpt-4o", "arrow"),
        ("chore: `gpt-4` → `gpt-4o-mini`", "gpt-4", "gpt-4o-mini", "arrow"),
        ("from gpt-4 (deprecated) to the new gpt-4o", "gpt-4", "gpt-4o", "from_to"),
        (
            "Replace text-davinci-003 with gpt-3.5-turbo-instruct",
            "text-davinci-003",
            "gpt-3.5-turbo-instruct",
            "replace_with",
        ),
        (
            "Use gemini-2.5-flash instead of gemini-2.0-flash",
            "gemini-2.0-flash",
            "gemini-2.5-flash",
            "instead_of",
        ),
        ("Switch to gpt-4o since gpt-4 is deprecated", "gpt-4", "gpt-4o", "switch_to"),
        ("model: gpt-4 (old) -> claude-sonnet-4-5", "gpt-4", "claude-sonnet-4-5", "any_arrow"),
        ("Drop gpt-4; we now run llama3.1 locally", "gpt-4", "llama3.1", "now_uses"),
        ("Drop gpt-4 for good; llama3.1 is what we run", "gpt-4", "llama3.1", "only_other"),
        ("Remove deprecated text-davinci-003", "text-davinci-003", None, None),
        ("Drop gpt-4, use gpt-4o or claude-sonnet-4-5", "gpt-4", None, None),
    ],
)
def test_extract_target(message: str, left: str, target: str | None, method: str | None) -> None:
    assert extract_target(message, left, registry()) == (target, method)


def test_extract_target_skips_aliases_and_models_also_left() -> None:
    reg = registry()
    # gpt-4-0613 is an alias of the model being left, not a target.
    assert extract_target("Pin gpt-4 to gpt-4-0613, then to gpt-4o", "gpt-4", reg)[0] == "gpt-4o"
    # gpt-4o-2024-05-13 is also left, so it is not the target.
    message = "Remove gpt-4 and gpt-4o-2024-05-13 (both deprecated); default is o3-mini"
    assert extract_target(message, "gpt-4", reg) == ("o3-mini", "only_other")


def test_follows() -> None:
    reg = registry()
    assert follows("gpt-4", "gpt-5.6-sol", reg) == ("gpt-5.6-sol", "exact")
    assert follows("claude-3-5-sonnet-20241022", "claude-sonnet-4-5", reg) == (
        "claude-sonnet-4-6",
        "same_line",
    )
    assert follows("gpt-4", "gpt-4o", reg)[1] == "other"
    assert follows("gpt-4", None, reg)[1] == "no_target"
    assert follows("gemini-2.0-flash", "gemini-2.5-flash", reg) == (None, "none_listed")


def test_target_row() -> None:
    row = target_row(commit("Migrate from gpt-4 to gpt-4o-2024-05-13"), registry())
    assert row is not None
    assert row["model_id"] == "gpt-4"
    assert row["target"] == "gpt-4o-2024-05-13"
    assert row["target_provider"] == "openai"
    assert row["same_provider"] is True
    assert row["target_retired_list"] is True
    assert row["target_announced_before"] is True  # announced 2026-05-01, commit 2026-07-01
    assert row["generation_change"] == "same"
    assert destination(row) == "same provider"

    other = target_row(commit("switch from gpt-4 to claude-3-5-haiku"), registry())
    assert other is not None
    assert other["same_provider"] is False
    assert other["tier_change"] == "down"
    assert other["generation_change"] == "unknown"
    assert destination(other) == "anthropic"

    none = target_row(commit("remove deprecated gpt-4"), registry())
    assert none is not None and none["target"] is None and destination(none) == "no target"
    assert target_row(commit("x", ("mystery-1",)), registry()) is None


def test_run_counts() -> None:
    labeled = [
        commit("from gpt-4 to gpt-4o"),
        commit("from gpt-4 to gpt-4o", day="2026-07-05"),  # same repo, later
        commit("from gpt-4 to llama3.1", repo="c/d"),
        commit("remove deprecated gpt-4", repo="e/f"),
        commit("from gemini-2.0-flash to gemini-2.5-flash", ("gemini-2.0-flash",), repo="g/h"),
        commit("unknown", ("mystery-1",)),
        {**commit("from gpt-4 to gpt-4o"), "migration_away": False},
    ]
    rows, stats = run(labeled, registry())
    assert stats.commits == 6
    assert stats.not_in_registry == 1
    assert stats.rows == len(rows) == 5
    assert stats.methods == {"arrow": 4, "none": 1}
    assert stats.destinations["openai"]["same provider"] == 2
    assert stats.destinations["openai"]["open or other"] == 1
    assert stats.destinations["all"]["no target"] == 1
    assert stats.follows["google"]["none_listed"] == 1
    assert stats.top_pairs[0] == ("gpt-4", "gpt-4o", 2)

    per_repo, repo_stats = run(labeled, registry(), per_repo=True)
    assert len(per_repo) == 4
    assert repo_stats.per_repo


def test_main_writes_rows_and_stats(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    labeled = tmp_path / "labeled.jsonl"
    rows = [commit("Migrate from gpt-4-0613 to gpt-4o", ("gpt-4-0613",))]
    labeled.write_text("".join(json.dumps(r) + "\n" for r in rows))
    out = tmp_path / "targets.jsonl"
    assert main(["--labeled", str(labeled), "--out", str(out)]) == 0
    written = [json.loads(line) for line in out.read_text().splitlines()]
    assert written[0]["target"] == "gpt-4o"
    stats = json.loads((tmp_path / "targets.stats.json").read_text())
    assert stats["rows"] == 1
    printed = capsys.readouterr().out
    assert "Where migrations go" in printed
    assert "gpt-4-0613" in printed


def test_main_without_input(tmp_path: Path) -> None:
    assert main(["--labeled", str(tmp_path / "missing.jsonl")]) == 1
    empty = tmp_path / "labeled.jsonl"
    empty.write_text(json.dumps({**commit("x"), "migration_away": False}) + "\n")
    assert main(["--labeled", str(empty), "--out", str(tmp_path / "t.jsonl")]) == 1


def test_rules_from_the_first_sample() -> None:
    """Cases from the first sample's disagreements (ADR 0017, revision)."""
    reg = load_registry()
    # A wildcard names a family, not a model.
    assert model_tokens("gemini-2.0-flash and gemini-2.5-* return 404") == ["gemini-2.0-flash"]
    # Google's and Anthropic's "-latest" aliases are models.
    assert model_tokens("use gemini-flash-lite-latest, claude-haiku-latest") == [
        "gemini-flash-lite-latest",
        "claude-haiku-latest",
    ]
    cases = [
        ("Embeddings: text-embedding-004 is gone. Replaced with gemini-embedding-2.", "now_uses"),
        ("Defaults are now gpt-5.5; o4-mini removed as any default.", "now_uses"),
    ]
    assert extract_target(cases[0][0], "text-embedding-004", reg) == (
        "gemini-embedding-2",
        "now_uses",
    )
    assert extract_target(cases[1][0], "o4-mini", reg) == ("gpt-5.5", "now_uses")
    # The new model next to "retired" is still the target.
    message = "embeds via REST (gemini-embedding-001, 768 dims - text-embedding-004 was retired)"
    assert extract_target(message, "text-embedding-004", reg) == (
        "gemini-embedding-001",
        "only_other",
    )
    # A model listed next to the one removed is removed too, not a target.
    message = "docs: sync model table - remove gemini-3.1-flash-lite, gemini-3.5-flash"
    assert extract_target(message, "gemini-3.1-flash-lite", reg) == (None, None)


def test_ai_assisted_and_shut_down_targets() -> None:
    reg = registry()
    row = target_row(
        commit("switch from gpt-4 to text-davinci-003\n\nReplit-Commit-Author: Agent"), reg
    )
    assert row is not None
    assert row["ai_assisted"] is True
    assert row["target_shut_down_before"] is True
    plain = target_row(commit("switch from gpt-4 to gpt-4o-2024-05-13"), reg)
    assert plain is not None
    assert plain["ai_assisted"] is False
    assert plain["target_shut_down_before"] is False
    trailer = target_row({**commit("from gpt-4 to gpt-4o"), "ai_trailer": True}, reg)
    assert trailer is not None and trailer["ai_assisted"] is True
    _, stats = run([commit("from gpt-4 to gpt-4o"), {**commit("x"), "ai_trailer": True}], reg)
    assert stats.ai_assisted["all with a target"] == [0, 1]


def test_targets_shut_down_before_the_registry() -> None:
    reg = registry()
    ids = ("gemini-2.0-flash",)
    late = target_row(commit("switch from gemini-2.0-flash to gemini-1.5-flash-002", ids), reg)
    assert late is not None
    assert late["target"] == "gemini-1.5-flash-002"
    assert late["target_retired_list"] is False
    assert late["target_shut_down_before"] is True
    early = target_row(
        commit("switch from gemini-2.0-flash to gemini-1.5-flash", ids, day="2025-06-01"), reg
    )
    assert early is not None and early["target_shut_down_before"] is False
    _, stats = run([commit("switch from gemini-2.0-flash to gemini-1.5-flash", ids)], reg)
    assert (stats.target_shut_down_before, stats.target_shut_down_earlier) == (1, 1)
