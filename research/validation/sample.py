"""Draw a stratified random sample of labelled candidates for hand-labelling.

The sample is blind: ``sample.csv`` shows only the commit, never what the
filter decided. What the filter decided is in ``sample_key.csv``, which the
person labelling should not open until they have finished (ADR 0013).

Two designs exist. ``v1`` (ADR 0013) checked the rules v1 labels. ``v2``
(ADR 0015) checks the rules v2 label ``migration_away`` on a fresh sample that
leaves out every commit already labelled.

Run from the repo root:
    uv run python -m research.validation.sample
    uv run python -m research.validation.sample --design v2
"""

import argparse
import csv
import json
import random
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

# How many commits to draw from each stratum. Each stratum answers one question:
STRATA: dict[str, int] = {
    "strict": 100,  # how often is a "clearly away" migration really a migration?
    "broad_only": 100,  # and one where the direction was unclear?
    "with_ai": 50,  # are AI-assisted ones as accurate?
    "rejected": 50,  # how many real migrations did the filter miss?
}
# Design v2 (ADR 0015): the rules v2 label, measured on fresh commits.
STRATA_V2: dict[str, int] = {
    "away": 100,  # how often is migration_away really a migration?
    "other_kept": 50,  # kept by Kim's rules (with or without AI trailer) but not "away"
    "rejected": 50,  # neither: how many real migrations are still missed?
}
SEED = 2026
SEED_V2 = 2027
MAX_MESSAGE = 1500  # characters shown per message; the URL has the full commit

LABEL_COLUMNS = ["is_migration", "from_model", "to_model", "note"]


def stratum(row: Mapping[str, Any]) -> str:
    """Which stratum one labelled candidate belongs to."""
    if row["migration_strict"]:
        return "strict"
    if row["migration"]:
        return "broad_only"
    if row["migration_with_ai"]:
        return "with_ai"
    return "rejected"


def stratum_v2(row: Mapping[str, Any]) -> str:
    """Which design-v2 stratum one labelled candidate belongs to."""
    if row["migration_away"]:
        return "away"
    if row["migration"] or row["migration_with_ai"]:
        return "other_kept"
    return "rejected"


DESIGNS: dict[str, tuple[dict[str, int], Callable[[Mapping[str, Any]], str], int, str]] = {
    "v1": (STRATA, stratum, SEED, "research/data/validation"),
    "v2": (STRATA_V2, stratum_v2, SEED_V2, "research/data/validation_v2"),
}


def draw(
    rows: Iterable[Mapping[str, Any]],
    sizes: Mapping[str, int] = STRATA,
    seed: int = SEED,
    which: Callable[[Mapping[str, Any]], str] = stratum,
) -> list[tuple[str, Mapping[str, Any]]]:
    """Return (stratum, row) pairs: a random sample of each stratum, then shuffled.

    Rows are sorted by SHA before sampling, so the same input and seed always
    give the same sample, whatever order the file was written in.
    """
    groups: dict[str, list[Mapping[str, Any]]] = {name: [] for name in sizes}
    for row in rows:
        groups[which(row)].append(row)
    rng = random.Random(seed)
    picked: list[tuple[str, Mapping[str, Any]]] = []
    for name, size in sizes.items():
        group = sorted(groups[name], key=lambda r: r["sha"])
        picked += [(name, row) for row in rng.sample(group, min(size, len(group)))]
    rng.shuffle(picked)  # mixed order, so the strata cannot be guessed from position
    return picked


def stratum_sizes(
    rows: Iterable[Mapping[str, Any]],
    names: Iterable[str] = STRATA,
    which: Callable[[Mapping[str, Any]], str] = stratum,
) -> dict[str, int]:
    """How many candidates each stratum has in total (for weighting the estimates)."""
    sizes = dict.fromkeys(names, 0)
    for row in rows:
        sizes[which(row)] += 1
    return sizes


def read_shas(path: Path) -> set[str]:
    """The SHAs in an earlier sample_key.csv."""
    with path.open(newline="", encoding="utf-8") as f:
        return {row["sha"] for row in csv.DictReader(f)}


def write_sample(picked: Sequence[tuple[str, Mapping[str, Any]]], out_dir: Path) -> None:
    """Write sample.csv (to label) and sample_key.csv (the filter's answers)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "sample.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["n", "url", "model_ids", "date", "message", *LABEL_COLUMNS])
        for n, (_, row) in enumerate(picked, start=1):
            message = row["message"]
            if len(message) > MAX_MESSAGE:
                message = message[:MAX_MESSAGE] + " [...]"
            writer.writerow(
                [
                    n,
                    row["url"],
                    " ".join(row["matched_ids"]),
                    row["committed_at"][:10],
                    message,
                    *([""] * len(LABEL_COLUMNS)),
                ]
            )
    with (out_dir / "sample_key.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["n", "sha", "stratum", "direction", "after_notice_start"])
        for n, (name, row) in enumerate(picked, start=1):
            writer.writerow([n, row["sha"], name, row["direction"], row["after_notice_start"]])


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--labeled", type=Path, default=Path("research/data/labeled.jsonl"))
    parser.add_argument("--design", choices=sorted(DESIGNS), default="v1")
    parser.add_argument("--out", type=Path, help="Default: the design's folder.")
    parser.add_argument("--seed", type=int, help="Default: the design's seed.")
    parser.add_argument(
        "--exclude",
        type=Path,
        action="append",
        default=[],
        help="An earlier sample_key.csv whose commits are left out (v2 leaves out v1's).",
    )
    args = parser.parse_args(argv)
    sizes_wanted, which, seed, folder = DESIGNS[args.design]
    args.out = args.out or Path(folder)
    args.seed = args.seed if args.seed is not None else seed
    if args.design == "v2" and not args.exclude:
        args.exclude = [Path("research/data/validation/sample_key.csv")]
    if not args.labeled.exists():
        print(f"{args.labeled} not found. Run research.filtering.filter first.", file=sys.stderr)
        return 1
    if (args.out / "sample.csv").exists():
        print(
            f"{args.out / 'sample.csv'} already exists. It may hold your labels, so it is "
            "not overwritten. Move it away first if you really want a new sample.",
            file=sys.stderr,
        )
        return 1

    excluded: set[str] = set()
    for path in args.exclude:
        if not path.exists():
            print(f"{path} not found (needed to leave out labelled commits).", file=sys.stderr)
            return 1
        excluded |= read_shas(path)

    with args.labeled.open(encoding="utf-8") as f:
        rows = [json.loads(line) for line in f]
    if args.design == "v2" and rows and "migration_away" not in rows[0]:
        print("These labels are from rules v1. Rerun research.filtering.filter.", file=sys.stderr)
        return 1
    sizes = stratum_sizes(rows, sizes_wanted, which)
    fresh = [row for row in rows if row["sha"] not in excluded]
    picked = draw(fresh, sizes_wanted, args.seed, which)
    write_sample(picked, args.out)
    (args.out / "strata.json").write_text(
        json.dumps(
            {
                "design": args.design,
                "seed": args.seed,
                "population": sizes,
                "sample": sizes_wanted,
                "excluded": len(excluded),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Sampled {len(picked)} commits (seed {args.seed}) from {len(rows):,} candidates.")
    if excluded:
        print(f"Left out {len(excluded)} commits that were already labelled.")
    for name, size in sizes_wanted.items():
        print(f"  {name:<11} {size:>4} of {sizes[name]:>9,}")
    print(f"To label:  {args.out / 'sample.csv'}")
    print(f"Key:       {args.out / 'sample_key.csv'}  (do not open until you have finished)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
