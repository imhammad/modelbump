"""Draw a stratified random sample of labelled candidates for hand-labelling.

The sample is blind: ``sample.csv`` shows only the commit, never what the
filter decided. What the filter decided is in ``sample_key.csv``, which the
person labelling should not open until they have finished (ADR 0013).

Run from the repo root:
    uv run python -m research.validation.sample
"""

import argparse
import csv
import json
import random
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

# How many commits to draw from each stratum. Each stratum answers one question:
STRATA: dict[str, int] = {
    "strict": 100,  # how often is a "clearly away" migration really a migration?
    "broad_only": 100,  # and one where the direction was unclear?
    "with_ai": 50,  # are AI-assisted ones as accurate?
    "rejected": 50,  # how many real migrations did the filter miss?
}
SEED = 2026
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


def draw(
    rows: Iterable[Mapping[str, Any]], sizes: Mapping[str, int] = STRATA, seed: int = SEED
) -> list[tuple[str, Mapping[str, Any]]]:
    """Return (stratum, row) pairs: a random sample of each stratum, then shuffled.

    Rows are sorted by SHA before sampling, so the same input and seed always
    give the same sample, whatever order the file was written in.
    """
    groups: dict[str, list[Mapping[str, Any]]] = {name: [] for name in sizes}
    for row in rows:
        groups[stratum(row)].append(row)
    rng = random.Random(seed)
    picked: list[tuple[str, Mapping[str, Any]]] = []
    for name, size in sizes.items():
        group = sorted(groups[name], key=lambda r: r["sha"])
        picked += [(name, row) for row in rng.sample(group, min(size, len(group)))]
    rng.shuffle(picked)  # mixed order, so the strata cannot be guessed from position
    return picked


def stratum_sizes(rows: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """How many candidates each stratum has in total (for weighting the estimates)."""
    sizes = dict.fromkeys(STRATA, 0)
    for row in rows:
        sizes[stratum(row)] += 1
    return sizes


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
    parser.add_argument("--out", type=Path, default=Path("research/data/validation"))
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args(argv)
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

    with args.labeled.open(encoding="utf-8") as f:
        rows = [json.loads(line) for line in f]
    picked = draw(rows, seed=args.seed)
    write_sample(picked, args.out)
    sizes = stratum_sizes(rows)
    (args.out / "strata.json").write_text(
        json.dumps({"seed": args.seed, "population": sizes, "sample": STRATA}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Sampled {len(picked)} commits (seed {args.seed}) from {len(rows):,} candidates.")
    for name, size in STRATA.items():
        print(f"  {name:<11} {size:>4} of {sizes[name]:>9,}")
    print(f"To label:  {args.out / 'sample.csv'}")
    print(f"Key:       {args.out / 'sample_key.csv'}  (do not open until you have finished)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
