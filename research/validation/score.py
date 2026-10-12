"""Score the hand labels: how often the filter is right, and what it misses.

Reads the files written by research.validation.sample after ``sample.csv``
has been labelled, and prints, for each stratum, the share of commits labelled
``yes`` with a 95% Wilson interval. From those it estimates the precision of
the ``migration`` label over the full set, and how many migrations the filter
rejected by mistake. With ``--second`` it also reports agreement between two
people (Cohen's kappa).

Run from the repo root:
    uv run python -m research.validation.score
    uv run python -m research.validation.score --second research/data/validation/sample_b.csv
    uv run python -m research.validation.score --compare research/data/validation/sample.csv
"""

import argparse
import csv
import json
import math
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

ANSWERS = {"yes": "yes", "y": "yes", "no": "no", "n": "no", "unsure": "unsure", "?": "unsure"}
Z = 1.959964  # 95%


@dataclass
class StratumScore:
    """Hand labels for one stratum."""

    population: int
    labelled: int  # yes + no; "unsure" is left out of the share
    yes: int
    unsure: int
    share: float
    low: float
    high: float


def read_labels(path: Path) -> dict[int, str]:
    """Return {n: "yes" | "no" | "unsure"} for every row with a recognised answer."""
    labels = {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            answer = ANSWERS.get(row["is_migration"].strip().lower())
            if answer is not None:
                labels[int(row["n"])] = answer
    return labels


def read_key(path: Path) -> dict[int, str]:
    """Return {n: stratum}."""
    with path.open(newline="", encoding="utf-8") as f:
        return {int(row["n"]): row["stratum"] for row in csv.DictReader(f)}


def wilson(successes: int, n: int) -> tuple[float, float]:
    """95% Wilson score interval for a proportion."""
    if n == 0:
        return 0.0, 1.0
    p = successes / n
    centre = (p + Z**2 / (2 * n)) / (1 + Z**2 / n)
    half = Z * math.sqrt(p * (1 - p) / n + Z**2 / (4 * n**2)) / (1 + Z**2 / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def score_strata(
    labels: Mapping[int, str], key: Mapping[int, str], population: Mapping[str, int]
) -> dict[str, StratumScore]:
    """Score every stratum."""
    scores = {}
    for name, size in population.items():
        answers = Counter(labels[n] for n, s in key.items() if s == name and n in labels)
        labelled = answers["yes"] + answers["no"]
        low, high = wilson(answers["yes"], labelled)
        scores[name] = StratumScore(
            population=size,
            labelled=labelled,
            yes=answers["yes"],
            unsure=answers["unsure"],
            share=answers["yes"] / labelled if labelled else 0.0,
            low=low,
            high=high,
        )
    return scores


def weighted_precision(
    scores: Mapping[str, StratumScore], strata: Sequence[str]
) -> tuple[float, float]:
    """Precision over several strata, weighted by their size; and its standard error."""
    total = sum(scores[s].population for s in strata)
    if total == 0:
        return 0.0, 0.0
    estimate = variance = 0.0
    for s in strata:
        score = scores[s]
        weight = score.population / total
        estimate += weight * score.share
        if score.labelled:
            variance += weight**2 * score.share * (1 - score.share) / score.labelled
    return estimate, math.sqrt(variance)


def cohen_kappa(first: Mapping[int, str], second: Mapping[int, str]) -> tuple[float, int]:
    """Cohen's kappa over the rows both people labelled; and how many rows that is."""
    shared = sorted(set(first) & set(second))
    if not shared:
        return 0.0, 0
    observed = sum(first[n] == second[n] for n in shared) / len(shared)
    a = Counter(first[n] for n in shared)
    b = Counter(second[n] for n in shared)
    expected = sum(a[c] * b[c] for c in set(a) | set(b)) / len(shared) ** 2
    if expected == 1:
        return 1.0, len(shared)
    return (observed - expected) / (1 - expected), len(shared)


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", type=Path, default=Path("research/data/validation"))
    parser.add_argument("--second", type=Path, help="The same sample, labelled by someone else.")
    parser.add_argument(
        "--compare",
        type=Path,
        help="Other labels for the same sample, shown side by side.",
    )
    args = parser.parse_args(argv)
    sample = args.dir / "sample.csv"
    if not sample.exists():
        print(f"{sample} not found. Run research.validation.sample first.", file=sys.stderr)
        return 1

    labels = read_labels(sample)
    key = read_key(args.dir / "sample_key.csv")
    population = json.loads((args.dir / "strata.json").read_text(encoding="utf-8"))["population"]
    scores = score_strata(labels, key, population)

    missing = len(key) - len(labels)
    if missing:
        print(f"Note: {missing} of {len(key)} rows have no yes/no/unsure yet; scoring the rest.\n")
    header = f"{'Stratum':<12}{'in full set':>12}{'labelled':>10}{'yes':>6}{'unsure':>8}"
    print(f"{header}   share yes (95% CI)")
    for name, s in scores.items():
        print(
            f"{name:<12}{s.population:>12,}{s.labelled:>10}{s.yes:>6}{s.unsure:>8}"
            f"   {s.share:6.1%} ({s.low:.1%} to {s.high:.1%})"
        )

    precision, error = weighted_precision(scores, ["strict", "broad_only"])
    kept = scores["strict"].population + scores["broad_only"].population
    true_kept = precision * kept
    missed = scores["rejected"].share * scores["rejected"].population
    recall = true_kept / (true_kept + missed) if true_kept + missed else 0.0
    print()
    print(
        f"Precision of 'migration' (weighted): {precision:.1%} "
        f"(± {Z * error:.1%}) -> about {true_kept:,.0f} real migrations of {kept:,}"
    )
    print(f"Migrations among rejected (estimate): about {missed:,.0f}")
    print(f"Recall of 'migration' (rough estimate): {recall:.1%}")
    print(f"Precision with an AI-tool trailer:     {scores['with_ai'].share:.1%}")

    result = {
        "strata": {name: asdict(s) for name, s in scores.items()},
        "precision": precision,
        "precision_margin": Z * error,
        "estimated_real_migrations": true_kept,
        "estimated_missed": missed,
        "recall": recall,
    }
    if args.second is not None:
        kappa, shared = cohen_kappa(labels, read_labels(args.second))
        print(f"Agreement (Cohen's kappa) over {shared} rows: {kappa:.2f}")
        result["kappa"] = kappa
        result["kappa_rows"] = shared
    if args.compare is not None:
        other = score_strata(read_labels(args.compare), key, population)
        other_precision, _ = weighted_precision(other, ["strict", "broad_only"])
        print(f"\nSide by side: this set vs {args.compare}")
        for name in scores:
            print(f"  {name:<12}{scores[name].share:7.1%}  vs {other[name].share:7.1%}")
        print(f"  {'precision':<12}{precision:7.1%}  vs {other_precision:7.1%}")
        result["compare"] = {
            "labels": str(args.compare),
            "strata": {name: asdict(s) for name, s in other.items()},
            "precision": other_precision,
        }
    (args.dir / "scores.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Written: {args.dir / 'scores.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
