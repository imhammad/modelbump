"""Find the model each migration moves to, and describe the switch.

Reads research/data/labeled.jsonl (from research.filtering.filter) and writes
research/data/targets.jsonl: one row per migration commit, with the retired
model it leaves (as in research.enrichment.timing), the model it moves to, how
that target was found in the message, and what kind of switch it is: same
provider or another, the provider's recommended replacement or not, a smaller
or larger tier, a newer or older generation (ADR 0017).

Run from the repo root:
    uv run python -m research.enrichment.targets
"""

import argparse
import json
import re
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date
from functools import cache
from pathlib import Path
from typing import Any

from modelbump.registry import Registry, load_registry
from research.enrichment.timing import first_per_repo, left_model, notice
from research.filtering.filter import read_jsonl, write_jsonl
from research.filtering.rules import (
    ADJECTIVES,
    END_QUOTE,
    FILLERS,
    QUOTE,
    _direction_patterns,
    _id,
)

# Anything that looks like an LLM model ID, from the three providers in the
# registry and the open models projects most often move to. Names without a
# digit are allowed only from a short list, so tools like "claude-code" or
# "gpt-engineer" are not read as models.
_FAMILIES = (
    r"gpt-[\w.-]+|chatgpt-[\w.-]+|o[134](?:-[a-z0-9][\w.]*)*"
    r"|(?:text|code)-(?:embedding|davinci|curie|babbage|ada|cushman|similarity|search)[\w.-]*"
    r"|(?:davinci|babbage)-\d+|codex-mini[\w.-]*|computer-use-preview[\w.-]*"
    r"|claude-[\w.-]+"
    r"|gemini-[\w.-]+|gemma-?\d[\w.-]*|(?:text)?embedding-(?:gecko-)?\d+[\w.-]*"
    r"|textembedding-gecko[\w.@-]*|(?:text|chat)-bison[\w.@-]*"
    r"|(?:meta-)?llama-?\d[\w.-]*|(?:mistral|mixtral|codestral|ministral|magistral)-[\w.-]+"
    r"|deepseek-[\w.-]+|qwen-?\d[\w.-]*|qwq-[\w.-]+|grok-[\w.-]+|command-[\w.-]+"
)
MODEL_TOKEN = re.compile(rf"(?<![\w.-])(?:{_FAMILIES})(?![\w-]|\.\w)", re.IGNORECASE)
NO_DIGIT_OK = re.compile(
    r"^(gemini-(pro|ultra|flash)(-vision|-lite)?|deepseek-(chat|coder|reasoner)"
    r"|(mistral|codestral)-(large|medium|small|tiny|latest)(-latest)?|command-r(-plus)?"
    r"|(text|chat)-bison|textembedding-gecko|codex-mini-latest|computer-use-preview)$"
)
# A model ID in a capture group, for the patterns below.
MODEL = rf"({_FAMILIES})(?![\w-]|\.\w)"
ARROW = r"(?:->|=>|→|➡)"

# Who makes a model that is not in the registry, by the start of its name.
# Google's old "text-embedding-00N" comes before OpenAI's "text-embedding-...".
PROVIDER_PREFIXES: tuple[tuple[str, str], ...] = (
    ("google", r"gemini-|gemma|text-embedding-0|textembedding-|embedding-|text-bison|chat-bison"),
    ("openai", r"gpt-|chatgpt-|o[134]\b|o[134]-|text-|code-|davinci|babbage|codex-|computer-use"),
    ("anthropic", r"claude-"),
    ("meta", r"llama|meta-llama"),
    ("mistral", r"mistral|mixtral|codestral|ministral|magistral"),
    ("deepseek", r"deepseek"),
    ("alibaba", r"qwen|qwq"),
    ("xai", r"grok"),
    ("cohere", r"command-"),
)
BIG_THREE = ("anthropic", "google", "openai")

# Version and date endings removed to compare two IDs of the same model.
_ENDINGS = re.compile(
    r"(-\d{8}|-\d{4}-\d{2}-\d{2}|-\d{2}-\d{4}|-\d{2}-\d{2}|-\d{3,4}|-latest|-preview|-exp)$"
)
_VERSION = re.compile(r"(?<![\d.])(\d+)(?:[.-](\d)(?![\d]))?")
# Tier words, judged from the name only (ADR 0017). OpenAI's newest names use
# sol (flagship), terra (mini) and luna (nano).
SMALL = {"mini", "nano", "haiku", "lite", "instant", "tiny", "small", "terra", "luna", "8b"}
LARGE = {"opus", "ultra", "pro", "large", "max"}

FOLLOWS = ("exact", "same_line", "other", "none_listed", "no_target")


def clean(model_id: str) -> str:
    """Lower case, without a trailing full stop or hyphen."""
    return model_id.lower().rstrip(".-")


def is_model(token: str) -> bool:
    """True if a matched token is a model ID, not a tool or library name."""
    return any(c.isdigit() for c in token) or NO_DIGIT_OK.match(token) is not None


def model_tokens(text: str) -> list[str]:
    """Every model ID in ``text``, in order, each once."""
    found: list[str] = []
    for match in MODEL_TOKEN.finditer(text):
        token = clean(match.group(0))
        if is_model(token) and token not in found:
            found.append(token)
    return found


def base(model_id: str) -> str:
    """The ID without date, snapshot and preview endings: the model it names."""
    out = clean(model_id)
    while True:
        shorter = _ENDINGS.sub("", out)
        if shorter == out:
            return out
        out = shorter


def line(model_id: str) -> str:
    """The product line, without any version: claude-3-5-sonnet -> claude-sonnet."""
    words = [w for w in re.split(r"[-.]", base(model_id)) if w and not re.fullmatch(r"\d+[ok]?", w)]
    if words and words[0] in {"o1", "o3", "o4"}:
        words[0] = "o"
    return "-".join(words)


def version(model_id: str) -> float | None:
    """The generation number in the ID: gpt-3.5-turbo -> 3.5, claude-sonnet-4-5 -> 4.5."""
    match = _VERSION.search(base(model_id))
    if match is None:
        return None
    major, minor = match.groups()
    return float(f"{major}.{minor or 0}")


def tier(model_id: str) -> str:
    """small, standard or large, from the words in the name."""
    words = set(re.split(r"[-.]", base(model_id)))
    if words & SMALL:
        return "small"
    if words & LARGE:
        return "large"
    return "standard"


def family(model_id: str) -> str:
    """The series a generation number belongs to: gpt, o, claude, gemini, ..."""
    first = line(model_id).split("-")[0]
    return "embedding" if "embedding" in model_id else first


def provider_of(model_id: str, registry: Registry) -> str | None:
    """The provider of a model: from the registry, else from its name."""
    entry = registry.get(model_id)
    if entry is not None:
        return entry[0].value
    for provider, prefix in PROVIDER_PREFIXES:
        if re.match(prefix, model_id, re.IGNORECASE):
            return provider
    return None


def same_entry(a: str, b: str, registry: Registry) -> bool:
    """True if two IDs are equal or aliases of one registry entry."""
    if clean(a) == clean(b):
        return True
    entry_a, entry_b = registry.get(a), registry.get(b)
    return entry_a is not None and entry_b is not None and entry_a[1] is entry_b[1]


def same_model(a: str, b: str, registry: Registry) -> bool:
    """True if two IDs name the same model, also when one has a date or snapshot ending."""
    return same_entry(a, b, registry) or base(a) == base(b)


def moved_away(message: str, model_id: str) -> bool:
    """True if the message leaves ``model_id`` and never moves into it."""
    away, into = _direction_patterns(model_id)
    return away.search(message) is not None and into.search(message) is None


@cache
def _target_patterns(left: str) -> tuple[tuple[str, re.Pattern[str]], ...]:
    """Patterns that name the model a commit moves to, best first, for one left ID."""
    mid = _id(left)
    patterns = {
        # "gpt-4 -> gpt-4o", "gpt-4 to gpt-4o"
        "arrow": rf"{mid}{END_QUOTE}\s*(?:model\s+)?(?:{ARROW}|\bto\b)\s*{FILLERS}{QUOTE}{MODEL}",
        # "from gpt-4 (deprecated) to the new gpt-4o"
        "from_to": rf"\bfrom\s+{ADJECTIVES}{QUOTE}{mid}[^\n]{{0,60}}?(?:{ARROW}|\bto\b)\s*"
        rf"{FILLERS}{QUOTE}{MODEL}",
        # "replace gpt-4 with gpt-4o"
        "replace_with": rf"\b(?:replac|swap|substitut)\w*\b[^\n]{{0,60}}?{mid}[^\n]{{0,60}}?"
        rf"\b(?:with|by|for)\s+{FILLERS}{QUOTE}{MODEL}",
        # "gpt-4o replaces gpt-4", "use gpt-4o instead of gpt-4"
        "instead_of": rf"{QUOTE}{MODEL}{END_QUOTE}[^\n]{{0,40}}?\b(?:replaces|supersedes|"
        rf"instead\s+of|in\s+place\s+of)\s+{ADJECTIVES}{QUOTE}{mid}",
        # "switch default model to gpt-4o" anywhere in the message
        "switch_to": rf"\b(?:switch|migrat|mov|upgrad|updat|chang|bump|set|default|replac)\w*"
        rf"\b[^\n.;]{{0,40}}?\bto\s+{FILLERS}{QUOTE}{MODEL}",
        # "model: gpt-4-0613 (old) -> gpt-4o"
        "any_arrow": rf"{ARROW}\s*{FILLERS}{QUOTE}{MODEL}",
    }
    return tuple((name, re.compile(p, re.IGNORECASE)) for name, p in patterns.items())


def extract_target(message: str, left: str, registry: Registry) -> tuple[str | None, str | None]:
    """The model a commit moves to from ``left``, and the pattern that found it.

    Returns (None, None) when the message names no target, for example when it
    only removes the old model. Another retired model that the message also
    moves away from is never a target, unless the message also moves into it.
    """

    def usable(token: str) -> bool:
        token = clean(token)
        return (
            is_model(token)
            and not same_entry(token, left, registry)
            and not (registry.get(token) is not None and moved_away(message, token))
        )

    for name, pattern in _target_patterns(left):
        for match in pattern.finditer(message):
            token = next(g for g in match.groups() if g)
            if usable(token):
                return clean(token), name
    others = [t for t in model_tokens(message) if usable(t)]
    distinct = {base(t) for t in others}
    if len(distinct) == 1:
        return others[0], "only_other"
    return None, None


def follows(left: str, target: str | None, registry: Registry) -> tuple[str | None, str]:
    """The registry's recommended replacement for ``left``, and how the target compares.

    The registry lists what the provider recommends today, not on the day of
    the commit (ADR 0006), so "same_line" (for example any newer Sonnet for a
    retired Sonnet) is the fairer measure.
    """
    entry = registry.get(left)
    recommended = entry[1].replacement if entry else None
    if recommended is None:
        return None, "none_listed"
    if target is None:
        return recommended, "no_target"
    if same_model(target, recommended, registry):
        return recommended, "exact"
    if line(target) == line(recommended):
        return recommended, "same_line"
    return recommended, "other"


def change(old: float | None, new: float | None) -> str:
    """up, same or down; "unknown" if either side is missing."""
    if old is None or new is None:
        return "unknown"
    return "up" if new > old else "down" if new < old else "same"


TIERS = {"small": 0, "standard": 1, "large": 2}


def target_row(row: dict[str, Any], registry: Registry) -> dict[str, Any] | None:
    """One output row for a labelled commit, or None if its model is unknown."""
    left = left_model(row, registry)
    if left is None:
        return None
    model_id, provider, _ = left
    target, method = extract_target(row["message"], model_id, registry)
    committed = date.fromisoformat(row["committed_at"][:10])
    recommended, follow = follows(model_id, target, registry)
    out: dict[str, Any] = {
        "sha": row["sha"],
        "repo": row["repo"],
        "url": row["url"],
        "committed": committed.isoformat(),
        "model_id": model_id,
        "provider": provider,
        "target": target,
        "target_method": method,
        "target_provider": None,
        "same_provider": None,
        "recommended": recommended,
        "follows": follow,
        "target_retired_list": None,
        "target_announced_before": None,
        "tier_change": "unknown",
        "generation_change": "unknown",
    }
    if target is None:
        return out
    target_provider = provider_of(target, registry)
    out["target_provider"] = target_provider
    out["same_provider"] = target_provider == provider if target_provider else None
    entry = registry.get(target)
    out["target_retired_list"] = entry is not None
    if entry is not None:
        first = notice(entry[1])
        out["target_announced_before"] = first is not None and first <= committed
    out["tier_change"] = change(TIERS[tier(model_id)], TIERS[tier(target)])
    if family(model_id) == family(target):
        out["generation_change"] = change(version(model_id), version(target))
    return out


@dataclass
class TargetStats:
    """Counts for the paper, written next to targets.jsonl."""

    label: str = "migration_away"
    per_repo: bool = False
    commits: int = 0
    not_in_registry: int = 0
    rows: int = 0
    methods: dict[str, int] = field(default_factory=dict)
    destinations: dict[str, dict[str, int]] = field(default_factory=dict)
    follows: dict[str, dict[str, int]] = field(default_factory=dict)
    target_retired_list: int = 0
    target_announced_before: int = 0
    tier_change: dict[str, int] = field(default_factory=dict)
    generation_change: dict[str, int] = field(default_factory=dict)
    top_pairs: list[tuple[str, str, int]] = field(default_factory=list)
    top_targets: list[tuple[str, int]] = field(default_factory=list)


def destination(row: dict[str, Any]) -> str:
    """Where a migration goes, for the provider table."""
    if row["target"] is None:
        return "no target"
    provider = row["target_provider"]
    if provider is None:
        return "unknown"
    if provider == row["provider"]:
        return "same provider"
    return provider if provider in BIG_THREE else "open or other"


DESTINATIONS = ("same provider", "anthropic", "google", "openai", "open or other", "unknown")


def summarise(rows: Sequence[dict[str, Any]], stats: TargetStats, top: int = 15) -> None:
    """Fill the counts in ``stats`` from the output rows."""
    stats.rows = len(rows)
    stats.methods = dict(Counter(r["target_method"] or "none" for r in rows).most_common())
    columns = [*sorted({r["provider"] for r in rows}), "all"]
    stats.destinations = {c: dict.fromkeys((*DESTINATIONS, "no target"), 0) for c in columns}
    stats.follows = {c: dict.fromkeys(FOLLOWS, 0) for c in columns}
    for r in rows:
        for column in (r["provider"], "all"):
            stats.destinations[column][destination(r)] += 1
            stats.follows[column][r["follows"]] += 1
    with_target = [r for r in rows if r["target"] is not None]
    stats.target_retired_list = sum(bool(r["target_retired_list"]) for r in with_target)
    stats.target_announced_before = sum(bool(r["target_announced_before"]) for r in with_target)
    stats.tier_change = dict(Counter(r["tier_change"] for r in with_target).most_common())
    stats.generation_change = dict(
        Counter(r["generation_change"] for r in with_target).most_common()
    )
    pairs = Counter((r["model_id"], r["target"]) for r in with_target)
    stats.top_pairs = [(a, b, n) for (a, b), n in pairs.most_common(top)]
    stats.top_targets = Counter(r["target"] for r in with_target).most_common(top)


def run(
    labeled: Iterable[dict[str, Any]],
    registry: Registry,
    label: str = "migration_away",
    per_repo: bool = False,
) -> tuple[list[dict[str, Any]], TargetStats]:
    """Build the target rows and the counts for one label."""
    stats = TargetStats(label=label, per_repo=per_repo)
    rows = []
    for row in labeled:
        if not row.get(label):
            continue
        stats.commits += 1
        out = target_row(row, registry)
        if out is None:
            stats.not_in_registry += 1
        else:
            rows.append(out)
    if per_repo:
        rows = first_per_repo(rows)
    summarise(rows, stats)
    return rows, stats


def pct(part: int, whole: int) -> str:
    return f"{part:>8,}  {100 * part / whole:5.1f}%" if whole else f"{part:>8,}      -"


def report(stats: TargetStats) -> None:
    """Print the tables for RQ3."""
    n = stats.rows
    print(f"Commits labelled {stats.label}: {stats.commits:,}")
    print(f"  moving away from a model in the registry: {n:,}")
    if stats.per_repo:
        print("  (first migration per repository and model)")
    print("\nHow the target was found:")
    for method, count in stats.methods.items():
        print(f"  {method:<36}{pct(count, n)}")

    columns = list(stats.destinations)
    print("\nWhere migrations go, by the provider of the retired model:")
    print(f"  {'':<24}" + "".join(f"{c:>11}" for c in columns))
    for d in (*DESTINATIONS, "no target"):
        print(f"  {d:<24}" + "".join(f"{stats.destinations[c][d]:>11,}" for c in columns))
    print("\nDoes the target match the provider's recommended replacement (as listed today)?")
    print(f"  {'':<24}" + "".join(f"{c:>11}" for c in columns))
    for f in FOLLOWS:
        print(f"  {f:<24}" + "".join(f"{stats.follows[c][f]:>11,}" for c in columns))

    found = n - stats.destinations["all"]["no target"]
    print(f"\nMigrations with a target: {found:,}")
    print(f"  target is itself on a retirement list today{pct(stats.target_retired_list, found)}")
    print(
        f"  target already announced for retirement   {pct(stats.target_announced_before, found)}"
        "  (on the commit day)"
    )
    print("  tier (small, standard, large):")
    for key, count in stats.tier_change.items():
        print(f"    {key:<40}{pct(count, found)}")
    print("  generation, within the same series:")
    for key, count in stats.generation_change.items():
        print(f"    {key:<40}{pct(count, found)}")
    print("\nMost common switches:")
    for left, target, count in stats.top_pairs:
        print(f"  {left:<34} -> {target:<30}{count:>7,}")
    print("\nMost common targets:")
    for target, count in stats.top_targets:
        print(f"  {target:<38}{pct(count, found)}")


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--labeled", type=Path, default=Path("research/data/labeled.jsonl"))
    parser.add_argument("--out", type=Path, default=Path("research/data/targets.jsonl"))
    parser.add_argument(
        "--label", default="migration_away", help="The label that marks a migration."
    )
    parser.add_argument(
        "--per-repo",
        action="store_true",
        help="Count only each repository's first migration away from each model.",
    )
    args = parser.parse_args(argv)
    if not args.labeled.exists():
        print(f"{args.labeled} not found. Run research.filtering.filter first.", file=sys.stderr)
        return 1

    rows, stats = run(read_jsonl(args.labeled), load_registry(), args.label, args.per_repo)
    if not rows:
        print(f"No commits are labelled {args.label!r}.", file=sys.stderr)
        return 1
    write_jsonl(rows, args.out)
    stats_path = args.out.with_suffix(".stats.json")
    stats_path.write_text(json.dumps(asdict(stats), indent=2) + "\n", encoding="utf-8")
    report(stats)
    print(f"\nWritten: {args.out} and {stats_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
