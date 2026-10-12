"""Check the current filter rules against the hand-labelled sample (development only).

Reruns the rules in research.filtering.rules on every labelled row and shows,
for each label, how many rows it flags, how many of those a person labelled
``yes``, and how many of the person's ``yes`` rows it catches. It also lists
the rows where rule and person disagree, so they can be read.

These numbers are **in-sample**: the rules were tuned on these same rows, and
the sample is stratified, so they overstate quality and are not estimates for
the full set. Honest estimates need a fresh sample (ADR 0014).

Run from the repo root:
    uv run python -m research.validation.dev_check
"""

import argparse
import csv
import sys
from collections.abc import Sequence
from pathlib import Path

from research.filtering.rules import (
    commit_direction,
    has_ai_trailer,
    has_migration_word,
    is_bot,
)
from research.validation.score import read_labels

LABELS = ("migration", "migration_strict", "migration_away")


def relabel(message: str, model_ids: Sequence[str], after: bool | None) -> dict[str, bool]:
    """The three labels of research.filtering.filter.label, from the message alone."""
    way = commit_direction(message, model_ids)
    bot = is_bot(message)
    kim = has_migration_word(message) and way != "into" and after is not False and not bot
    ai = has_ai_trailer(message)
    return {
        "migration": kim and not ai,
        "migration_strict": kim and not ai and way == "away",
        "migration_away": way == "away" and not bot,
    }


def read_after(path: Path) -> dict[int, bool | None]:
    """after_notice_start per row, from sample_key.csv."""
    values = {"True": True, "False": False}
    with path.open(newline="", encoding="utf-8") as f:
        return {int(row["n"]): values.get(row["after_notice_start"]) for row in csv.DictReader(f)}


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--labels", type=Path, default=Path("research/data/validation_adjudicated/sample.csv")
    )
    parser.add_argument("--key", type=Path, default=Path("research/data/validation/sample_key.csv"))
    args = parser.parse_args(argv)
    if not args.labels.exists() or not args.key.exists():
        print(f"Need {args.labels} and {args.key}.", file=sys.stderr)
        return 1

    answers = read_labels(args.labels)
    after = read_after(args.key)
    with args.labels.open(newline="", encoding="utf-8-sig") as f:
        rows = {int(row["n"]): row for row in csv.DictReader(f)}

    flags = {
        n: relabel(rows[n]["message"], rows[n]["model_ids"].split(), after.get(n))
        for n in answers
        if answers[n] != "unsure"
    }
    yes = {n for n in flags if answers[n] == "yes"}
    print(f"Labelled rows: {len(flags)}, of which yes: {len(yes)}  (in-sample, not estimates)\n")
    print(f"{'Label':<18}{'flags':>7}{'yes':>6}{'precision':>11}{'catches':>10}")
    for name in LABELS:
        flagged = {n for n in flags if flags[n][name]}
        hits = flagged & yes
        precision = len(hits) / len(flagged) if flagged else 0.0
        print(
            f"{name:<18}{len(flagged):>7}{len(hits):>6}{precision:>11.1%}"
            f"{len(hits) / len(yes) if yes else 0:>10.1%}"
        )
    away = {n for n in flags if flags[n]["migration_away"]}
    print(f"\nFlagged away but labelled no:  {', '.join(map(str, sorted(away - yes))) or '-'}")
    print(f"Labelled yes but not away:     {', '.join(map(str, sorted(yes - away))) or '-'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
