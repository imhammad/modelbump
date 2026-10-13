"""How long before or after the shutdown do projects migrate?

Reads research/data/timing.jsonl (from research.enrichment.timing) and prints,
for each provider, the median number of days between the shutdown and the
migration with a 95% confidence interval, the quartiles, how the migrations
spread over time windows, and how much of the notice period projects used.
The numbers are written to research/data/lag.stats.json (ADR 0017).

Run from the repo root:
    uv run python -m research.analysis.lag --retired-by 2026-07-11
"""

import argparse
import json
import math
import sys
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from research.enrichment.timing import EXACT, first_per_repo
from research.filtering.filter import read_jsonl

Z = 1.959964  # 95%

# Windows of days from the shutdown (negative = before), as (name, first, last).
WINDOWS: tuple[tuple[str, float, float], ...] = (
    ("more than 180 days before", -math.inf, -181),
    ("91 to 180 days before", -180, -91),
    ("31 to 90 days before", -90, -31),
    ("1 to 30 days before", -30, -1),
    ("0 to 30 days after", 0, 30),
    ("31 to 90 days after", 31, 90),
    ("91 to 180 days after", 91, 180),
    ("181 to 365 days after", 181, 365),
    ("more than 365 days after", 366, math.inf),
)
GROUPS = ("openai+anthropic", "anthropic", "openai", "google")


def quantile(values: Sequence[float], q: float) -> float:
    """The q-th quantile of sorted ``values``, by linear interpolation."""
    if not values:
        return math.nan
    position = (len(values) - 1) * q
    low = math.floor(position)
    high = math.ceil(position)
    return values[low] + (values[high] - values[low]) * (position - low)


def median_ci(values: Sequence[float]) -> tuple[float, float]:
    """A distribution-free 95% confidence interval for the median of sorted ``values``.

    Uses the order statistics whose ranks come from the normal approximation
    to the binomial (Conover, Practical Nonparametric Statistics), so no
    resampling and no assumption about the shape of the data.
    """
    n = len(values)
    if n == 0:
        return math.nan, math.nan
    half = Z * math.sqrt(n) / 2
    low = max(1, math.floor(n / 2 - half))
    high = min(n, math.ceil(1 + n / 2 + half))
    return values[low - 1], values[high - 1]


@dataclass
class Spread:
    """Median, its 95% interval, and quartiles of a list of day counts."""

    n: int = 0
    median: float = math.nan
    median_low: float = math.nan
    median_high: float = math.nan
    q1: float = math.nan
    q3: float = math.nan

    @classmethod
    def of(cls, values: Iterable[float]) -> "Spread":
        ordered = sorted(values)
        low, high = median_ci(ordered)
        return cls(
            n=len(ordered),
            median=quantile(ordered, 0.5),
            median_low=low,
            median_high=high,
            q1=quantile(ordered, 0.25),
            q3=quantile(ordered, 0.75),
        )


@dataclass
class GroupLag:
    """The lag numbers for one group of providers."""

    days_from_shutdown: Spread = field(default_factory=Spread)
    first_per_repo: Spread = field(default_factory=Spread)
    after_shutdown: Spread = field(default_factory=Spread)
    windows: dict[str, int] = field(default_factory=dict)
    notice_period: Spread = field(default_factory=Spread)
    notice_used: Spread = field(default_factory=Spread)


@dataclass
class ModelLag:
    """The lag numbers for one retired model."""

    model_id: str
    provider: str
    commits: int
    notice_days: int | None
    median_days: float
    after_shutdown: float


@dataclass
class LagStats:
    """Everything printed, for the paper."""

    retired_by: str = ""
    rows: int = 0
    groups: dict[str, GroupLag] = field(default_factory=dict)
    models: list[ModelLag] = field(default_factory=list)


def in_group(row: dict[str, Any], group: str) -> bool:
    if group == "openai+anthropic":
        return row["provider"] in EXACT
    return bool(row["provider"] == group)


def window(days: int) -> str:
    """The name of the window that ``days`` (from the shutdown) falls in."""
    return next(name for name, first, last in WINDOWS if first <= days <= last)


def notice_days(row: dict[str, Any]) -> int | None:
    """Days from the notice to the shutdown, if the notice is known."""
    if row["notice"] is None:
        return None
    return (date.fromisoformat(row["shutdown"]) - date.fromisoformat(row["notice"])).days


def group_lag(rows: Sequence[dict[str, Any]]) -> GroupLag:
    """The lag numbers for the rows of one group."""
    days = [r["days_from_shutdown"] for r in rows]
    lag = GroupLag(
        days_from_shutdown=Spread.of(days),
        first_per_repo=Spread.of(r["days_from_shutdown"] for r in first_per_repo(rows)),
        after_shutdown=Spread.of(d for d in days if d >= 0),
        windows={name: 0 for name, _, _ in WINDOWS},
    )
    for d in days:
        lag.windows[window(d)] += 1
    periods = {r["model_id"]: notice_days(r) for r in rows}
    lag.notice_period = Spread.of(p for p in periods.values() if p is not None)
    used = []
    for r in rows:
        period = notice_days(r)
        if r["phase"] == "after_notice" and period:
            committed = date.fromisoformat(r["committed"])
            used.append((committed - date.fromisoformat(r["notice"])).days / period)
    lag.notice_used = Spread.of(used)
    return lag


def model_lags(rows: Sequence[dict[str, Any]], minimum: int) -> list[ModelLag]:
    """One line per retired model with at least ``minimum`` migrations."""
    by_model: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_model.setdefault(r["model_id"], []).append(r)
    out = []
    for model_id, chosen in by_model.items():
        if len(chosen) < minimum:
            continue
        days = sorted(r["days_from_shutdown"] for r in chosen)
        out.append(
            ModelLag(
                model_id=model_id,
                provider=chosen[0]["provider"],
                commits=len(chosen),
                notice_days=notice_days(chosen[0]),
                median_days=quantile(days, 0.5),
                after_shutdown=sum(d >= 0 for d in days) / len(days),
            )
        )
    return sorted(out, key=lambda m: (-m.commits, m.model_id))


def run(
    timing: Iterable[dict[str, Any]], retired_by: date | None = None, minimum: int = 100
) -> LagStats:
    """The lag numbers for every migration away from a model shut down by ``retired_by``."""
    rows = list(timing)
    end = retired_by or max((date.fromisoformat(r["committed"]) for r in rows), default=None)
    stats = LagStats(retired_by=end.isoformat() if end else "")
    retired = [r for r in rows if end is not None and r["shutdown"] <= stats.retired_by]
    stats.rows = len(retired)
    for group in GROUPS:
        chosen = [r for r in retired if in_group(r, group)]
        if chosen:
            stats.groups[group] = group_lag(chosen)
    stats.models = model_lags(retired, minimum)
    return stats


def finite(value: Any) -> Any:
    """``value`` with every NaN replaced by None, so the JSON file is standard JSON."""
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, dict):
        return {k: finite(v) for k, v in value.items()}
    if isinstance(value, list):
        return [finite(v) for v in value]
    return value


def days(value: float) -> str:
    return "-" if math.isnan(value) else f"{value:,.0f}"


def report(stats: LagStats) -> None:
    """Print the tables for RQ2."""
    groups = list(stats.groups)
    head = f"  {'':<34}" + "".join(f"{g:>18}" for g in groups)
    print(f"Migrations away from models shut down by {stats.retired_by}: {stats.rows:,}")
    print("Days from the shutdown (negative = before; Google: earliest possible day)")

    def spread_lines(title: str, pick: str) -> None:
        print(f"\n{title}")
        print(head)
        spreads = [getattr(stats.groups[g], pick) for g in groups]
        print(f"  {'commits':<34}" + "".join(f"{s.n:>18,}" for s in spreads))
        print(
            f"  {'median (95% CI)':<34}"
            + "".join(
                f"{f'{days(s.median)} ({days(s.median_low)}..{days(s.median_high)})':>18}"
                for s in spreads
            )
        )
        print(
            f"  {'quartiles':<34}"
            + "".join(f"{days(s.q1) + ' / ' + days(s.q3):>18}" for s in spreads)
        )

    spread_lines("All migrations:", "days_from_shutdown")
    spread_lines("First migration per repository and model:", "first_per_repo")
    spread_lines("Only migrations made after the shutdown:", "after_shutdown")

    print("\nWhen migrations happen:")
    print(head)
    for name, _, _ in WINDOWS:
        cells = []
        for g in groups:
            count = stats.groups[g].windows[name]
            total = stats.groups[g].days_from_shutdown.n
            cells.append(f"{count:,} ({100 * count / total:4.1f}%)")
        print(f"  {name:<34}" + "".join(f"{c:>18}" for c in cells))

    print("\nNotice period (days from notice to shutdown, one value per model):")
    print(head)
    notice = [stats.groups[g].notice_period for g in groups]
    print(f"  {'models with a notice date':<34}" + "".join(f"{s.n:>18,}" for s in notice))
    print(
        f"  {'median (quartiles)':<34}"
        + "".join(
            f"{days(s.median) + ' (' + days(s.q1) + '/' + days(s.q3) + ')':>18}" for s in notice
        )
    )
    used = [stats.groups[g].notice_used for g in groups]
    print(f"  {'migrations during the notice':<34}" + "".join(f"{s.n:>18,}" for s in used))
    print(
        f"  {'share of the notice gone (median)':<34}"
        + "".join(f"{'-' if math.isnan(s.median) else f'{100 * s.median:.0f}%':>18}" for s in used)
    )

    print("\nModels with the most migrations:")
    print(f"  {'model':<34}{'provider':>10}{'commits':>9}{'notice':>8}{'median':>8}{'after':>8}")
    for m in stats.models:
        notice_text = "-" if m.notice_days is None else f"{m.notice_days}"
        print(
            f"  {m.model_id:<34}{m.provider:>10}{m.commits:>9,}{notice_text:>8}"
            f"{days(m.median_days):>8}{100 * m.after_shutdown:>7.0f}%"
        )


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--timing", type=Path, default=Path("research/data/timing.jsonl"))
    parser.add_argument("--out", type=Path, default=Path("research/data/lag.stats.json"))
    parser.add_argument(
        "--retired-by",
        type=date.fromisoformat,
        help="Only models shut down by this day count (default: last commit day).",
    )
    parser.add_argument(
        "--min-commits",
        type=int,
        default=100,
        help="Smallest number of migrations for a model to get its own line.",
    )
    args = parser.parse_args(argv)
    if not args.timing.exists():
        print(f"{args.timing} not found. Run research.enrichment.timing first.", file=sys.stderr)
        return 1
    stats = run(read_jsonl(args.timing), args.retired_by, args.min_commits)
    if not stats.rows:
        print("No migrations away from a model that was already shut down.", file=sys.stderr)
        return 1
    report(stats)
    args.out.write_text(json.dumps(finite(asdict(stats)), indent=2) + "\n", encoding="utf-8")
    print(f"\nWritten: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
