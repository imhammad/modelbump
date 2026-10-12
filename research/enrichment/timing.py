"""Place every migration commit on its model's retirement timeline.

Reads research/data/labeled.jsonl (from research.filtering.filter) and writes
research/data/timing.jsonl: one row per migration commit, with the retired
model it moves away from, that model's notice and shutdown dates, and where
the commit falls between them. It then prints the share of migrations made
after the shutdown, the figure Kim (2026) reports as 82% (ADR 0016).

Run from the repo root:
    uv run python -m research.enrichment.timing
"""

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from modelbump.registry import Registry, RetiredModel, load_registry
from research.filtering.filter import read_jsonl, write_jsonl
from research.filtering.rules import direction
from research.mining.miner import BEFORE_NOTICE

PHASES = ("before_notice", "after_notice", "after_shutdown", "no_notice")
PHASE_NAMES = {
    "before_notice": "before the notice",
    "after_notice": "after the notice, before shutdown",
    "after_shutdown": "after the shutdown",
    "no_notice": "before shutdown, no notice date",
}
# Providers whose pages give exact notice and shutdown dates. Google gives
# only the earliest possible shutdown day and no notice day (ADR 0007).
EXACT = ("anthropic", "openai")
KIM_SHARE = 0.82


@dataclass
class Share:
    """How many of ``total`` migrations were made after the shutdown."""

    after: int = 0
    total: int = 0

    def add(self, after: bool) -> None:
        self.after += after
        self.total += 1

    @property
    def share(self) -> float:
        return self.after / self.total if self.total else 0.0


@dataclass
class TimingStats:
    """Counts for the paper, written next to timing.jsonl."""

    label: str = "migration_away"
    retired_by: str = ""
    commits: int = 0
    not_in_registry: int = 0
    phases: dict[str, dict[str, int]] = field(default_factory=dict)
    phases_retired: dict[str, dict[str, int]] = field(default_factory=dict)
    headline: dict[str, Share] = field(default_factory=dict)


def notice(model: RetiredModel) -> date | None:
    """The earliest deprecation notice, counting rescheduled plans."""
    days = [model.announced, *(plan.announced for plan in model.superseded)]
    known = [day for day in days if day is not None]
    return min(known) if known else None


def phase(committed: date, model: RetiredModel) -> str:
    """Where ``committed`` falls on the model's timeline (one of PHASES)."""
    if committed >= model.shutdown:
        return "after_shutdown"
    first = notice(model)
    if first is None:
        return "no_notice"
    return "after_notice" if committed >= first else "before_notice"


def left_model(row: dict[str, Any], registry: Registry) -> tuple[str, str, RetiredModel] | None:
    """The retired model the commit moves away from, with its ID and provider.

    Only IDs the message moves away from count; if the rules found none, every
    matched ID does. When several qualify, the one shut down first is used,
    since it is the one that forced the change soonest.
    """
    ids: list[str] = row["matched_ids"]
    away = [i for i in ids if direction(row["message"], i) == "away"] or ids
    found = []
    for model_id in away:
        entry = registry.get(model_id)
        if entry is not None:
            found.append((model_id, entry[0].value, entry[1]))
    if not found:
        return None
    return min(found, key=lambda item: (item[2].shutdown, item[0]))


def timing_row(row: dict[str, Any], registry: Registry) -> dict[str, Any] | None:
    """One output row for a labelled commit, or None if its model is unknown."""
    left = left_model(row, registry)
    if left is None:
        return None
    model_id, provider, model = left
    committed = date.fromisoformat(row["committed_at"][:10])
    first = notice(model)
    return {
        "sha": row["sha"],
        "repo": row["repo"],
        "url": row["url"],
        "committed": committed.isoformat(),
        "model_id": model_id,
        "provider": provider,
        "notice": first.isoformat() if first else None,
        "shutdown": model.shutdown.isoformat(),
        "shutdown_is_earliest": model.shutdown_is_earliest,
        "phase": phase(committed, model),
        "days_from_shutdown": (committed - model.shutdown).days,
        "in_kim_window": None if first is None else committed >= first - BEFORE_NOTICE,
    }


def first_per_repo(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep each repository's earliest migration away from each model."""
    first: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row["repo"], row["model_id"])
        if key not in first or row["committed"] < first[key]["committed"]:
            first[key] = row
    return sorted(first.values(), key=lambda r: (r["committed"], r["sha"]))


def count_phases(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Phase counts per provider, plus an "all" column."""
    counts: dict[str, Counter[str]] = {}
    for row in rows:
        for column in (row["provider"], "all"):
            counts.setdefault(column, Counter())[row["phase"]] += 1
    order = sorted(counts, key=lambda column: (column == "all", column))
    return {column: {p: counts[column][p] for p in PHASES} for column in order}


def run(
    labeled: Iterable[dict[str, Any]],
    registry: Registry,
    label: str = "migration_away",
    retired_by: date | None = None,
) -> tuple[list[dict[str, Any]], TimingStats]:
    """Build the timing rows and the counts for one label."""
    stats = TimingStats(label=label)
    rows = []
    for row in labeled:
        if not row.get(label):
            continue
        stats.commits += 1
        out = timing_row(row, registry)
        if out is None:
            stats.not_in_registry += 1
        else:
            rows.append(out)
    end = retired_by or max((date.fromisoformat(r["committed"]) for r in rows), default=None)
    stats.retired_by = end.isoformat() if end else ""
    retired = [r for r in rows if end is not None and r["shutdown"] <= stats.retired_by]
    stats.phases = count_phases(rows)
    stats.phases_retired = count_phases(retired)

    exact = [r for r in retired if r["provider"] in EXACT]
    variants = {
        "exact_dates": exact,
        "exact_dates_kim_window": [r for r in exact if r["in_kim_window"]],
        "exact_dates_first_per_repo": first_per_repo(exact),
        "google_earliest_dates": [r for r in retired if r["provider"] not in EXACT],
    }
    for name, chosen in variants.items():
        share = Share()
        for r in chosen:
            share.add(r["phase"] == "after_shutdown")
        stats.headline[name] = share
    return rows, stats


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--labeled", type=Path, default=Path("research/data/labeled.jsonl"))
    parser.add_argument("--out", type=Path, default=Path("research/data/timing.jsonl"))
    parser.add_argument(
        "--label", default="migration_away", help="The label that marks a migration."
    )
    parser.add_argument(
        "--retired-by",
        type=date.fromisoformat,
        help="Only models shut down by this day count in the headline (default: last commit day).",
    )
    args = parser.parse_args(argv)
    if not args.labeled.exists():
        print(f"{args.labeled} not found. Run research.filtering.filter first.", file=sys.stderr)
        return 1

    rows, stats = run(read_jsonl(args.labeled), load_registry(), args.label, args.retired_by)
    if not rows:
        print(f"No commits are labelled {args.label!r}.", file=sys.stderr)
        return 1
    write_jsonl(rows, args.out)
    stats_path = args.out.with_suffix(".stats.json")
    stats_path.write_text(json.dumps(asdict(stats), indent=2) + "\n", encoding="utf-8")

    print(f"Commits labelled {args.label}: {stats.commits:,}")
    print(f"  moving away from a model in the registry: {len(rows):,}")
    print(f"\nWhere they fall, models shut down by {stats.retired_by}:")
    columns = list(stats.phases_retired)
    print(f"  {'':<36}" + "".join(f"{c:>11}" for c in columns))
    for p in PHASES:
        cells = "".join(f"{stats.phases_retired[c][p]:>11,}" for c in columns)
        print(f"  {PHASE_NAMES[p]:<36}{cells}")
    print("\nShare made after the shutdown:")
    names = {
        "exact_dates": "OpenAI + Anthropic (exact dates)",
        "exact_dates_kim_window": "  same, from notice minus 30 days",
        "exact_dates_first_per_repo": "  same, first migration per repository",
        "google_earliest_dates": "Google (earliest possible dates)",
    }
    for key, text in names.items():
        share = stats.headline[key]
        print(f"  {text:<40}{share.after:>8,} of {share.total:>8,} = {100 * share.share:5.1f}%")
    print(f"  {'Kim (2026)':<40}{100 * KIM_SHARE:>29.1f}%")
    print(f"Written: {args.out} and {stats_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
