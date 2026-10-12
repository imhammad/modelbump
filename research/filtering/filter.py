"""Label every candidate commit with the migration rules and count what survives.

Reads research/data/candidates.jsonl (from research.mining.miner) and writes
research/data/labeled.jsonl: every candidate, plus one field per rule and the
two labels used in the paper:

- ``migration``: Kim's rules. A migration word, not into the model, not made
  more than 30 days before the notice, not a bot, no AI-tool trailer.
- ``migration_strict``: the same, and the message clearly moves *away* from
  the model ("from X", "X to Y", "replace X with", "remove X" ...).
- ``migration_away``: the message clearly moves away from the model and is not
  from a bot, whatever its date, wording or AI trailer (rules v2, ADR 0014).

Run from the repo root:
    uv run python -m research.filtering.filter
"""

import argparse
import json
import sys
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from modelbump.registry import load_registry
from research.filtering.rules import (
    after_notice_start,
    commit_direction,
    has_ai_style,
    has_ai_trailer,
    has_migration_word,
    is_bot,
)
from research.mining.miner import focus_starts

# Version of the rules in research.filtering.rules, written to the stats file
# so every number can be traced to the rules that produced it (ADR 0014).
RULES_VERSION = 2


@dataclass
class FilterStats:
    """The funnel: how many candidates pass each rule, in order."""

    rules_version: int = RULES_VERSION
    candidates: int = 0
    with_migration_word: int = 0
    not_into: int = 0
    not_before_notice: int = 0
    not_bot: int = 0
    migration_with_ai: int = 0
    migration: int = 0
    migration_strict: int = 0
    migration_away: int = 0
    directions: dict[str, int] = field(default_factory=dict)
    no_notice_date: int = 0
    ai_trailer: int = 0
    ai_style: int = 0
    by_provider: dict[str, int] = field(default_factory=dict)


def label(candidate: dict[str, Any], starts: Mapping[str, date]) -> dict[str, Any]:
    """Return the candidate with one field per rule and the two labels."""
    message = candidate["message"]
    ids: Sequence[str] = candidate["matched_ids"]
    committed = date.fromisoformat(candidate["committed_at"][:10])
    word = has_migration_word(message)
    way = commit_direction(message, ids)
    after = after_notice_start(committed, ids, starts)
    bot = is_bot(message)
    ai_trailer = has_ai_trailer(message)
    kim = word and way != "into" and after is not False and not bot
    return {
        **candidate,
        "migration_word": word,
        "direction": way,
        "after_notice_start": after,
        "bot": bot,
        "ai_trailer": ai_trailer,
        "ai_style": has_ai_style(message),
        "migration": kim and not ai_trailer,
        "migration_strict": kim and not ai_trailer and way == "away",
        "migration_with_ai": kim and ai_trailer,
        "migration_away": way == "away" and not bot,
    }


def run(
    candidates: Iterable[dict[str, Any]], starts: Mapping[str, date]
) -> tuple[list[dict[str, Any]], FilterStats]:
    """Label every candidate and count the funnel."""
    stats = FilterStats()
    labeled = []
    for candidate in candidates:
        row = label(candidate, starts)
        labeled.append(row)
        stats.candidates += 1
        stats.directions[row["direction"]] = stats.directions.get(row["direction"], 0) + 1
        stats.no_notice_date += row["after_notice_start"] is None
        stats.ai_trailer += row["ai_trailer"]
        stats.ai_style += row["ai_style"]
        stats.migration_away += row["migration_away"]
        if not row["migration_word"]:
            continue
        stats.with_migration_word += 1
        if row["direction"] == "into":
            continue
        stats.not_into += 1
        if row["after_notice_start"] is False:
            continue
        stats.not_before_notice += 1
        if row["bot"]:
            continue
        stats.not_bot += 1
        stats.migration_with_ai += row["migration_with_ai"]
        stats.migration += row["migration"]
        stats.migration_strict += row["migration_strict"]
        if row["migration"]:
            for provider in row["providers"]:
                stats.by_provider[provider] = stats.by_provider.get(provider, 0) + 1
    return labeled, stats


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


def write_jsonl(rows: Iterable[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--candidates", type=Path, default=Path("research/data/candidates.jsonl"))
    parser.add_argument("--out", type=Path, default=Path("research/data/labeled.jsonl"))
    args = parser.parse_args(argv)
    if not args.candidates.exists():
        print(f"{args.candidates} not found. Run research.mining.miner first.", file=sys.stderr)
        return 1

    labeled, stats = run(read_jsonl(args.candidates), focus_starts(load_registry()))
    write_jsonl(labeled, args.out)
    stats_path = args.out.with_suffix(".stats.json")
    stats_path.write_text(json.dumps(asdict(stats), indent=2) + "\n", encoding="utf-8")

    n = stats.candidates or 1

    def line(text: str, count: int) -> None:
        print(f"{text:<44}{count:>9,}  ({100 * count / n:5.1f}%)")

    line("Candidates", stats.candidates)
    line("  with a migration word", stats.with_migration_word)
    line("  ... and not a move into the model", stats.not_into)
    line("  ... and not before notice minus 30 days", stats.not_before_notice)
    line("  ... and not a dependency bot", stats.not_bot)
    line("  ... and no AI-tool trailer = MIGRATION", stats.migration)
    line("  of which clearly away from it (strict)", stats.migration_strict)
    line("Same rules, with an AI-tool trailer", stats.migration_with_ai)
    line("Clearly away, any date or trailer = AWAY", stats.migration_away)
    print()
    directions = ", ".join(f"{k} {v:,}" for k, v in sorted(stats.directions.items()))
    providers = ", ".join(f"{k} {v:,}" for k, v in sorted(stats.by_provider.items()))
    print(f"Direction of all candidates:  {directions}")
    print(f"Migrations by provider:       {providers}")
    print(f"No notice date (kept):        {stats.no_notice_date:,}")
    print(f"AI-tool trailer / AI style:   {stats.ai_trailer:,} / {stats.ai_style:,}")
    print(f"Rules version:                {stats.rules_version}")
    print(f"Written: {args.out} and {stats_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
