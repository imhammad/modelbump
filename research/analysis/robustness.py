"""Do the RQ1 and RQ2 results survive the objections a reviewer would raise?

Reads research/data and writes research/data/robustness.json (ADR 0021). Each
check repeats the headline (OpenAI and Anthropic migrations away from models
shut down by 2026-07-11, so every model has at least 90 days of data after its
shutdown) with one thing changed:

1. With the days GitHub cut at 1,000 results weighted up: each migration
   found on such a day counts total/1,000 times, using the total GitHub
   reported for that day (from the miner's cache). Also counts how many
   headline migrations leave the five IDs searched only from shortly before
   their notice (ADR 0011).
2. With 95% intervals from resampling whole repositories, because commits
   from the same repository are not independent.
3. With other labels: Kim's rules (``migration``), the strict rules, and
   ``migration_away`` without AI-assisted commits.
4. With the hand labels: precision before and after the shutdown, and the
   share after the shutdown among the real migrations in the hand sample,
   counting those the label missed.
5. OpenAI against Anthropic: a Mann-Whitney U test and Cliff's delta on the
   days from the shutdown.

Run from the repo root, after research.enrichment.targets:
    uv run python -m research.analysis.robustness
"""

import argparse
import csv
import json
import math
import random
import re
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from modelbump.registry import Registry, load_registry
from research.analysis.lag import Spread
from research.enrichment import timing
from research.enrichment.timing import EXACT, first_per_repo
from research.filtering.filter import read_jsonl
from research.mining.github_search import MAX_RESULTS, _cache_key
from research.validation import score as filter_score
from research.validation.score import wilson

RETIRED_BY = date(2026, 7, 11)
SEED = 2029
REPS = 2000
SAMPLE = "validation_v2_adjudicated"
# Labels compared in check 3, as (name, label, drop AI-assisted commits).
LABELS: tuple[tuple[str, str, bool], ...] = (
    ("headline", "migration_away", False),
    ("kim_label", "migration", False),
    ("strict", "migration_strict", False),
    ("no_ai", "migration_away", True),
)
# Cliff's delta size names (Romano et al., 2006).
CLIFF_SIZES = ((0.147, "negligible"), (0.33, "small"), (0.474, "medium"), (math.inf, "large"))


class MissingInputs(Exception):
    """Some input files are not there yet."""


def retired_exact(rows: Iterable[dict[str, Any]], retired_by: date) -> list[dict[str, Any]]:
    """OpenAI and Anthropic rows whose model was shut down by ``retired_by``."""
    end = retired_by.isoformat()
    return [r for r in rows if r["provider"] in EXACT and r["shutdown"] <= end]


def summary(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Share after the shutdown with its Wilson interval, and the median days."""
    after = sum(r["phase"] == "after_shutdown" for r in rows)
    low, high = wilson(after, len(rows))
    spread = Spread.of(r["days_from_shutdown"] for r in rows)
    return {
        "rows": len(rows),
        "repos": len({r["repo"] for r in rows}),
        "after": after,
        "share": after / len(rows) if rows else math.nan,
        "low": low,
        "high": high,
        "median_days": spread.median,
        "median_low": spread.median_low,
        "median_high": spread.median_high,
    }


# ---------------------------------------------------- 1. incomplete searches


def incomplete_searches(
    candidate_stats: Mapping[str, Any], registry: Registry
) -> dict[str, list[str]]:
    """Models whose search may have missed commits, with why, by registry ID.

    Two reasons: the ID was searched only from 30 days before its notice, or
    found too big to narrow (ADR 0011); or one of its days had more than
    1,000 results, of which GitHub shows only the first 1,000.
    """
    reasons: dict[str, set[str]] = {}

    def add(model_id: str, reason: str) -> None:
        entry = registry.get(model_id)
        reasons.setdefault(entry[1].id if entry else model_id, set()).add(reason)

    for model_id in candidate_stats.get("focused_starts", {}):
        add(model_id, "searched from the notice")
    for model_id in candidate_stats.get("too_big_without_notice", []):
        add(model_id, "too big, no notice date")
    for query in candidate_stats.get("truncated_windows", []):
        parts = query.split('"')
        if len(parts) >= 3:
            add(parts[1], "day over 1,000 results")
    return {model_id: sorted(why) for model_id, why in sorted(reasons.items())}


def canonical(model_id: str, registry: Registry) -> str:
    """The registry ID that ``model_id`` (an ID or alias) points to."""
    entry = registry.get(model_id)
    return entry[1].id if entry else model_id


def late_searched_rows(
    rows: Iterable[dict[str, Any]], candidate_stats: Mapping[str, Any], registry: Registry
) -> int:
    """How many rows leave a model searched only from its notice, or too big to narrow."""
    late = {
        canonical(m, registry)
        for m in [
            *candidate_stats.get("focused_starts", {}),
            *candidate_stats.get("too_big_without_notice", []),
        ]
    }
    return sum(canonical(r["model_id"], registry) in late for r in rows)


WINDOW = re.compile(r"committer-date:(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})")


def truncated_days(
    candidate_stats: Mapping[str, Any], cache: Path, registry: Registry
) -> list[dict[str, Any]]:
    """Every search window GitHub cut at 1,000 results, with the total it reported.

    The total comes from the first page of the search in the miner's cache,
    so no request is made. It is None when that page is not in the cache.
    """
    out = []
    for query in candidate_stats.get("truncated_windows", []):
        parts = query.split('"')
        window = WINDOW.search(query)
        if len(parts) < 3 or window is None:
            continue
        path = cache / f"{_cache_key(query, 1)}.json"
        total = None
        if path.exists():
            record = json.loads(path.read_text(encoding="utf-8"))
            total = int(record["response"]["total_count"])
        entry = registry.get(parts[1])
        out.append(
            {
                "model": canonical(parts[1], registry),
                "start": window.group(1),
                "end": window.group(2),
                "total": total,
                "after_shutdown": None
                if entry is None
                else window.group(1) >= entry[1].shutdown.isoformat(),
            }
        )
    return out


def weights(
    rows: Sequence[dict[str, Any]], days: Sequence[dict[str, Any]], registry: Registry
) -> list[float]:
    """One weight per row: total/1,000 if it was found on a cut day of its model, else 1."""
    cut: dict[str, list[tuple[str, str, float]]] = {}
    for d in days:
        if d["total"]:
            weight = max(1.0, d["total"] / MAX_RESULTS)
            cut.setdefault(d["model"], []).append((d["start"], d["end"], weight))
    out = []
    for r in rows:
        day = r["committed"]
        found = [
            w
            for start, end, w in cut.get(canonical(r["model_id"], registry), [])
            if start <= day <= end
        ]
        out.append(max(found, default=1.0))
    return out


def weighted_median(days: Sequence[float], weights: Sequence[float]) -> float:
    """The smallest value at which the cumulative weight reaches half the total."""
    pairs = sorted(zip(days, weights, strict=True))
    if not pairs:
        return math.nan
    half = sum(weights) / 2
    running = 0.0
    for value, weight in pairs:
        running += weight
        if running >= half:
            return value
    return pairs[-1][0]


def weighted_summary(
    rows: Sequence[dict[str, Any]], row_weights: Sequence[float], reps: int = REPS, seed: int = SEED
) -> dict[str, Any]:
    """Weighted share after the shutdown and median days, with repository-bootstrap intervals."""
    by_repo: dict[str, list[tuple[int, float]]] = {}
    for r, w in zip(rows, row_weights, strict=True):
        by_repo.setdefault(r["repo"], []).append((r["days_from_shutdown"], w))
    clusters = [by_repo[repo] for repo in sorted(by_repo)]

    def stats(pairs: Sequence[tuple[int, float]]) -> tuple[float, float]:
        total = sum(w for _, w in pairs)
        after = sum(w for d, w in pairs if d >= 0)
        median = weighted_median([d for d, _ in pairs], [w for _, w in pairs])
        return (after / total if total else math.nan), median

    pairs = [p for cluster in clusters for p in cluster]
    share, median = stats(pairs)
    out: dict[str, Any] = {
        "rows": len(rows),
        "reweighted": sum(w > 1 for w in row_weights),
        "weighted_rows": sum(row_weights),
        "share": share,
        "median_days": median,
        "low": math.nan,
        "high": math.nan,
        "median_low": math.nan,
        "median_high": math.nan,
    }
    if not clusters:
        return out
    rng = random.Random(seed)
    shares, medians = [], []
    for _ in range(reps):
        drawn = [p for cluster in rng.choices(clusters, k=len(clusters)) for p in cluster]
        s, m = stats(drawn)
        shares.append(s)
        medians.append(m)
    shares.sort()
    medians.sort()
    out.update(
        low=percentile(shares, 0.025),
        high=percentile(shares, 0.975),
        median_low=percentile(medians, 0.025),
        median_high=percentile(medians, 0.975),
    )
    return out


# ------------------------------------------------- 2. repository bootstrap


def repo_bootstrap(
    rows: Sequence[dict[str, Any]], reps: int = REPS, seed: int = SEED
) -> dict[str, float]:
    """95% percentile intervals from resampling whole repositories with replacement.

    Every repository keeps all its rows, so a repository with many migrations
    counts as one unit (a cluster bootstrap), which widens the intervals when
    commits from the same repository are alike.
    """
    by_repo: dict[str, list[int]] = {}
    for r in rows:
        by_repo.setdefault(r["repo"], []).append(r["days_from_shutdown"])
    clusters = [by_repo[repo] for repo in sorted(by_repo)]
    if not clusters:
        return {"share_low": math.nan, "share_high": math.nan}
    rng = random.Random(seed)
    shares, medians = [], []
    for _ in range(reps):
        days: list[int] = []
        for cluster in rng.choices(clusters, k=len(clusters)):
            days.extend(cluster)
        days.sort()
        shares.append(sum(d >= 0 for d in days) / len(days))
        medians.append(float(percentile(days, 0.5)))
    shares.sort()
    medians.sort()
    return {
        "reps": reps,
        "seed": seed,
        "repos": len(clusters),
        "share_low": percentile(shares, 0.025),
        "share_high": percentile(shares, 0.975),
        "median_low": percentile(medians, 0.025),
        "median_high": percentile(medians, 0.975),
    }


def percentile(values: Sequence[float], q: float) -> float:
    """The q-th quantile of sorted ``values``, by linear interpolation."""
    position = (len(values) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    return values[low] + (values[high] - values[low]) * (position - low)


# ------------------------------------------------------------- 3. labels


def label_rows(
    labeled: Sequence[dict[str, Any]],
    registry: Registry,
    label: str,
    ai_assisted: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Timing rows for one label, optionally without the AI-assisted commits."""
    rows, _ = timing.run(labeled, registry, label=label)
    if ai_assisted is not None:
        rows = [r for r in rows if r["sha"] not in ai_assisted]
    return rows


# ------------------------------------------------------- 4. hand labels


def read_sample(sample_dir: Path) -> list[dict[str, Any]]:
    """The hand-labelled rows: n, sha, stratum and the yes/no answer."""
    answers = filter_score.read_labels(sample_dir / "sample.csv")
    with (sample_dir / "sample_key.csv").open(newline="", encoding="utf-8") as f:
        key = list(csv.DictReader(f))
    return [
        {
            "n": int(k["n"]),
            "sha": k["sha"],
            "stratum": k["stratum"],
            "yes": answers[int(k["n"])] == "yes",
        }
        for k in key
        if answers.get(int(k["n"])) in ("yes", "no")
    ]


def sample_phases(
    sample: Sequence[dict[str, Any]], labeled: Mapping[str, dict[str, Any]], registry: Registry
) -> list[dict[str, Any]]:
    """Each hand-labelled row with ``after`` (made after its model's shutdown) or None."""
    out = []
    for row in sample:
        commit = labeled.get(row["sha"])
        placed = timing.timing_row(commit, registry) if commit else None
        after = None if placed is None else placed["phase"] == "after_shutdown"
        out.append({**row, "after": after})
    return out


def true_after_share(rows: Sequence[dict[str, Any]], population: Mapping[str, int]) -> float:
    """Share after the shutdown among the real migrations, weighted by stratum size.

    Each stratum's hand-labelled rows stand for all its candidates, so the
    estimate counts the migrations the label missed (``yes`` in the other
    strata) as well as the ones it found.
    """
    after = total = 0.0
    for stratum, size in population.items():
        chosen = [r for r in rows if r["stratum"] == stratum and r["after"] is not None]
        if not chosen:
            continue
        after += size * sum(r["yes"] and r["after"] for r in chosen) / len(chosen)
        total += size * sum(r["yes"] for r in chosen) / len(chosen)
    return after / total if total else math.nan


def stratified_bootstrap(
    rows: Sequence[dict[str, Any]],
    statistic: Callable[[Sequence[dict[str, Any]]], float],
    reps: int = REPS,
    seed: int = SEED,
) -> tuple[float, float]:
    """95% percentile interval, resampling rows within each stratum."""
    strata: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        strata.setdefault(r["stratum"], []).append(r)
    rng = random.Random(seed)
    values = []
    for _ in range(reps):
        drawn = [r for group in strata.values() for r in rng.choices(group, k=len(group))]
        value = statistic(drawn)
        if not math.isnan(value):
            values.append(value)
    if not values:
        return math.nan, math.nan
    values.sort()
    return percentile(values, 0.025), percentile(values, 0.975)


def hand_check(sample: Sequence[dict[str, Any]], population: Mapping[str, int]) -> dict[str, Any]:
    """Precision by phase, and the label's after-shutdown share against the truth."""
    known = [r for r in sample if r["after"] is not None]
    away = [r for r in known if r["stratum"] == "away"]
    out: dict[str, Any] = {"rows": len(sample), "unplaced": len(sample) - len(known)}
    for name, when in (("precision_after", True), ("precision_before", False)):
        chosen = [r for r in away if r["after"] == when]
        yes = sum(r["yes"] for r in chosen)
        low, high = wilson(yes, len(chosen))
        out[name] = {
            "yes": yes,
            "rows": len(chosen),
            "share": ratio(yes, len(chosen)),
            "low": low,
            "high": high,
        }
    label_after = sum(r["after"] for r in away)
    out["label_after"] = {
        "after": label_after,
        "rows": len(away),
        "share": ratio(label_after, len(away)),
    }
    missed = [r for r in known if r["stratum"] != "away" and r["yes"]]
    missed_after = sum(r["after"] for r in missed)
    out["missed_after"] = {
        "after": missed_after,
        "rows": len(missed),
        "share": ratio(missed_after, len(missed)),
    }
    low, high = stratified_bootstrap(known, lambda rows: true_after_share(rows, population))
    out["true_after"] = {"share": true_after_share(known, population), "low": low, "high": high}
    return out


def ratio(part: float, whole: float) -> float:
    return part / whole if whole else math.nan


# ------------------------------------------------- 5. OpenAI vs Anthropic


def mann_whitney(first: Sequence[float], second: Sequence[float]) -> dict[str, float]:
    """Two-sided Mann-Whitney U test (normal approximation, tie-corrected) and Cliff's delta.

    Cliff's delta is P(first > second) - P(first < second): positive when the
    first group tends to migrate later.
    """
    n1, n2 = len(first), len(second)
    if not n1 or not n2:
        return {"n1": n1, "n2": n2, "u": math.nan, "z": math.nan, "p": math.nan, "delta": math.nan}
    pooled = sorted([(v, 0) for v in first] + [(v, 1) for v in second])
    n = n1 + n2
    rank_sum = 0.0
    ties = 0.0
    i = 0
    while i < n:
        j = i
        while j < n and pooled[j][0] == pooled[i][0]:
            j += 1
        rank = (i + 1 + j) / 2  # mean of ranks i+1 .. j
        rank_sum += rank * sum(1 for k in range(i, j) if pooled[k][1] == 0)
        t = j - i
        ties += t**3 - t
        i = j
    u = rank_sum - n1 * (n1 + 1) / 2
    variance = n1 * n2 / 12 * ((n + 1) - ties / (n * (n - 1))) if n > 1 else 0.0
    z = (u - n1 * n2 / 2) / math.sqrt(variance) if variance > 0 else 0.0
    return {
        "n1": n1,
        "n2": n2,
        "u": u,
        "z": z,
        "p": math.erfc(abs(z) / math.sqrt(2)),
        "delta": 2 * u / (n1 * n2) - 1,
    }


def cliff_size(delta: float) -> str:
    """The size name for a Cliff's delta."""
    return next(name for limit, name in CLIFF_SIZES if abs(delta) < limit)


def providers_test(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """OpenAI against Anthropic: all migrations, those after the shutdown, first per repository."""
    out = {}
    for name, chosen in (
        ("all", rows),
        ("after_shutdown", [r for r in rows if r["days_from_shutdown"] >= 0]),
        ("first_per_repo", first_per_repo(rows)),
    ):
        days = {p: [r["days_from_shutdown"] for r in chosen if r["provider"] == p] for p in EXACT}
        result: dict[str, Any] = mann_whitney(days["openai"], days["anthropic"])
        result["size"] = "" if math.isnan(result["delta"]) else cliff_size(result["delta"])
        out[name] = result
    return out


# ------------------------------------------------------------------- run


def load(data: Path, cache: Path | None = None) -> dict[str, Any]:
    """Every input. Raises MissingInputs naming each missing file."""
    needed = {
        "labeled.jsonl": "research.filtering.filter",
        "candidates.stats.json": "research.mining.miner",
        "targets.jsonl": "research.enrichment.targets",
        f"{SAMPLE}/sample.csv": "the labelled second sample (Step 15)",
        f"{SAMPLE}/sample_key.csv": "research.validation.sample (Step 15)",
        f"{SAMPLE}/strata.json": "research.validation.sample (Step 15)",
    }
    missing = [
        f"  {data / name}  <- {made_by}"
        for name, made_by in needed.items()
        if not (data / name).exists()
    ]
    if missing:
        raise MissingInputs("\n".join(missing))
    sample = read_sample(data / SAMPLE)
    wanted = {r["sha"] for r in sample}
    labels = {label for _, label, _ in LABELS}
    # Keep only the rows any check needs, so the messages of 250,000 commits
    # are not all held in memory.
    labeled = [
        r
        for r in read_jsonl(data / "labeled.jsonl")
        if r["sha"] in wanted or any(r.get(lb) for lb in labels)
    ]
    return {
        "labeled": labeled,
        "candidate_stats": json.loads((data / "candidates.stats.json").read_text("utf-8")),
        "ai_assisted": {
            r["sha"] for r in read_jsonl(data / "targets.jsonl") if r.get("ai_assisted")
        },
        "sample": sample,
        "cache": cache or data / "cache",
        "population": json.loads((data / SAMPLE / "strata.json").read_text("utf-8"))["population"],
    }


def run(
    inputs: Mapping[str, Any], retired_by: date = RETIRED_BY, reps: int = REPS
) -> dict[str, Any]:
    """Every check, as one JSON-ready dict."""
    registry = load_registry()
    labeled = inputs["labeled"]
    out: dict[str, Any] = {"retired_by": retired_by.isoformat(), "seed": SEED}

    variants = {}
    away: list[dict[str, Any]] = []
    for name, label, drop_ai in LABELS:
        rows = label_rows(labeled, registry, label, inputs["ai_assisted"] if drop_ai else None)
        variants[name] = retired_exact(rows, retired_by)
        if name == "headline":
            away = rows
    headline = variants["headline"]
    out["labels"] = {
        name: {"label": label, "drop_ai_assisted": drop, **summary(variants[name])}
        for name, label, drop in LABELS
    }
    out["first_per_repo"] = summary(first_per_repo(headline))

    google = [
        r for r in away if r["provider"] not in EXACT and r["shutdown"] <= retired_by.isoformat()
    ]
    out["google"] = summary(google)
    stats = inputs["candidate_stats"]
    cut = truncated_days(stats, inputs["cache"], registry)
    out["truncation"] = {
        "models": incomplete_searches(stats, registry),
        "late_searched_rows": late_searched_rows(headline, stats, registry),
        "days": len(cut),
        "days_without_total": sum(d["total"] is None for d in cut),
        "days_after_shutdown": sum(d["after_shutdown"] is True for d in cut),
        "days_before_shutdown": sum(d["after_shutdown"] is False for d in cut),
        "missing_results": sum(d["total"] - MAX_RESULTS for d in cut if d["total"]),
        "largest_total": max((d["total"] for d in cut if d["total"]), default=None),
        "exact": weighted_summary(headline, weights(headline, cut, registry), reps),
        "google": weighted_summary(google, weights(google, cut, registry), reps),
    }

    out["repo_bootstrap"] = repo_bootstrap(headline, reps)

    by_sha = {r["sha"]: r for r in labeled}
    out["hand"] = hand_check(
        sample_phases(inputs["sample"], by_sha, registry), inputs["population"]
    )

    out["providers"] = providers_test(headline)
    return out


def finite(value: Any) -> Any:
    """``value`` with every NaN replaced by None, so the file is standard JSON."""
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, dict):
        return {k: finite(v) for k, v in value.items()}
    if isinstance(value, list):
        return [finite(v) for v in value]
    return value


def number(value: float | None, scale: float = 1.0, digits: int = 1) -> str:
    """``value`` times ``scale``, or "-" when it is unknown."""
    if value is None or math.isnan(value):
        return "-"
    return f"{scale * value:.{digits}f}"


def pvalue(value: float | None) -> str:
    """A p-value with two significant digits."""
    return "-" if value is None else f"{value:.2g}"


def share_text(s: Mapping[str, Any]) -> str:
    """A share with its interval, such as "62.2% (61.3 to 63.0)"."""
    if s["share"] is None:
        return "-"
    return f"{number(s['share'], 100)}% ({number(s['low'], 100)} to {number(s['high'], 100)})"


def report(result: Mapping[str, Any]) -> None:
    """Print every check."""
    labels, boot, hand = result["labels"], result["repo_bootstrap"], result["hand"]
    cut = result["truncation"]
    head = labels["headline"]
    print(f"OpenAI and Anthropic, models shut down by {result['retired_by']}")
    print(f"\n  {'':<46}{'migrations':>11}{'after the shutdown (95% CI)':>30}{'median days':>13}")
    for text, s in (
        ("Headline (migration_away)", head),
        ("First per repository and model", result["first_per_repo"]),
        ("Cut days weighted up (CI by repository)", cut["exact"]),
        ("Kim's rules (migration)", labels["kim_label"]),
        ("Strict rules (migration_strict)", labels["strict"]),
        ("migration_away without AI-assisted", labels["no_ai"]),
        ("Google (earliest dates)", result["google"]),
        ("Google, cut days weighted up", cut["google"]),
    ):
        median = number(s["median_days"], digits=0)
        print(f"  {text:<46}{s['rows']:>11,}{share_text(s):>30}{median:>13}")

    print(f"\nDays GitHub cut at 1,000 results: {cut['days']}")
    before, after = cut["days_before_shutdown"], cut["days_after_shutdown"]
    print(f"  before / after the model's shutdown: {before} / {after}")
    print(f"  without a total in the cache: {cut['days_without_total']}")
    largest = cut["largest_total"]
    print(
        f"  results not seen: {cut['missing_results']:,} "
        f"(largest day: {'-' if largest is None else f'{largest:,}'} results)"
    )
    print(
        f"  headline migrations weighted up: {cut['exact']['reweighted']:,} "
        f"(they now count as {number(cut['exact']['weighted_rows'], digits=0)} in all)"
    )
    print(
        "  headline migrations from IDs searched only from their notice: "
        f"{cut['late_searched_rows']:,}"
    )

    print(
        f"\nResampling whole repositories ({boot['repos']:,} repositories, "
        f"{boot['reps']:,} times, seed {boot['seed']}):"
    )
    print(
        f"  after the shutdown: 95% CI {number(boot['share_low'], 100)} to "
        f"{number(boot['share_high'], 100)} (by commit: {number(head['low'], 100)} to "
        f"{number(head['high'], 100)})"
    )
    print(
        f"  median days: 95% CI {number(boot['median_low'], digits=0)} to "
        f"{number(boot['median_high'], digits=0)} (by commit: "
        f"{number(head['median_low'], digits=0)} to {number(head['median_high'], digits=0)})"
    )

    print(f"\nHand sample ({hand['rows']} rows, {hand['unplaced']} not placed on a timeline):")
    for key, text in (
        ("precision_after", "precision, commits after the shutdown"),
        ("precision_before", "precision, commits before the shutdown"),
    ):
        p = hand[key]
        print(f"  {text:<42}{p['yes']:>4} of {p['rows']:<4}  {share_text(p)}")
    for key, text in (
        ("label_after", "label's migrations after the shutdown"),
        ("missed_after", "missed migrations after the shutdown"),
    ):
        p = hand[key]
        print(f"  {text:<42}{p['after']:>4} of {p['rows']:<4}  {number(p['share'], 100)}%")
    weighted = share_text(hand["true_after"])
    print(f"  {'real migrations after the shutdown':<42}{'(weighted)':>12}  {weighted}")

    print("\nOpenAI against Anthropic, days from the shutdown (Mann-Whitney U, Cliff's delta):")
    for key, text in (
        ("all", "all migrations"),
        ("after_shutdown", "after the shutdown"),
        ("first_per_repo", "first per repository"),
    ):
        t = result["providers"][key]
        print(
            f"  {text:<22}n = {t['n1']:,} / {t['n2']:,}  z = {number(t['z'], digits=2)}  "
            f"p = {pvalue(t['p'])}  "
            f"delta = {number(t['delta'], digits=3)} ({t['size']})"
        )


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=Path, default=Path("research/data"))
    parser.add_argument("--out", type=Path, default=Path("research/data/robustness.json"))
    parser.add_argument("--retired-by", type=date.fromisoformat, default=RETIRED_BY)
    parser.add_argument("--reps", type=int, default=REPS, help="Bootstrap resamples.")
    parser.add_argument(
        "--cache", type=Path, help="The miner's cache (default: research/data/cache)."
    )
    args = parser.parse_args(argv)
    try:
        inputs = load(args.data, args.cache)
    except MissingInputs as missing:
        print(f"Missing inputs (file <- what makes it):\n{missing}", file=sys.stderr)
        return 1
    result = finite(run(inputs, args.retired_by, args.reps))
    if not result["labels"]["headline"]["rows"]:
        print("No migrations away from a model that was already shut down.", file=sys.stderr)
        return 1
    report(result)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"\nWritten: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
