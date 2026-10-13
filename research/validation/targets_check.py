"""Check the target extraction against the hand-labelled samples.

For every row labelled ``yes`` whose ``to_model`` was filled in by hand, this
runs research.enrichment.targets on the same commit and compares the model it
finds with the hand label. It prints how often they agree, with a 95% Wilson
interval, and writes every row to ``targets_check.csv`` in the sample folder
so the disagreements can be read one by one (ADR 0017).

Run from the repo root:
    uv run python -m research.validation.targets_check
    uv run python -m research.validation.targets_check --dir research/data/validation_adjudicated
"""

import argparse
import csv
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from modelbump.registry import Registry, load_registry
from research.enrichment.targets import (
    clean,
    extract_target,
    model_tokens,
    provider_of,
    same_model,
)
from research.enrichment.timing import left_model
from research.filtering.filter import read_jsonl
from research.validation.score import ANSWERS, wilson

NO_TARGET = {"none", "n/a", "na", "-", "removed", "remove", "nothing", "no model"}
VERDICTS = (
    "match",
    "agree_none",
    "wrong_same_provider",
    "wrong_other_provider",
    "missed",
    "extra",
)
VERDICT_NAMES = {
    "match": "same model",
    "agree_none": "both say no target",
    "wrong_same_provider": "other model, same provider",
    "wrong_other_provider": "other model, other provider",
    "missed": "hand has a target, code found none",
    "extra": "hand says none, code found one",
}


def hand_target(text: str) -> str | None:
    """The model in a hand-written ``to_model`` cell, or None for "none"."""
    text = text.strip()
    if text.lower() in NO_TARGET:
        return None
    tokens = model_tokens(text)
    return tokens[0] if tokens else clean(text).replace(" ", "-")


def verdict(hand: str | None, found: str | None, registry: Registry) -> str:
    """How the extracted target compares with the hand label."""
    if hand is None:
        return "agree_none" if found is None else "extra"
    if found is None:
        return "missed"
    if same_model(hand, found, registry):
        return "match"
    same = provider_of(hand, registry) == provider_of(found, registry)
    return "wrong_same_provider" if same else "wrong_other_provider"


def check_row(row: Mapping[str, str], message: str, registry: Registry) -> dict[str, Any] | None:
    """Compare one labelled row; None if it is not a ``yes`` with ``to_model`` filled in."""
    if ANSWERS.get(row["is_migration"].strip().lower()) != "yes":
        return None
    if not row.get("to_model", "").strip():
        return None
    commit = {"matched_ids": row["model_ids"].split(), "message": message}
    left = left_model(commit, registry)
    left_id = left[0] if left else clean(row.get("from_model", ""))
    found, method = extract_target(message, left_id, registry) if left_id else (None, None)
    hand = hand_target(row["to_model"])
    return {
        "n": row["n"],
        "url": row["url"],
        "from_model": row.get("from_model", ""),
        "left": left_id,
        "to_model": row["to_model"],
        "hand": hand,
        "found": found,
        "method": method,
        "verdict": verdict(hand, found, registry),
    }


def full_messages(sample_dir: Path, labeled: Path) -> dict[str, str]:
    """{n: full message} from labeled.jsonl; sample.csv cuts long messages."""
    key = sample_dir / "sample_key.csv"
    if not key.exists() or not labeled.exists():
        return {}
    with key.open(newline="", encoding="utf-8") as f:
        sha_to_n = {r["sha"]: r["n"] for r in csv.DictReader(f)}
    return {sha_to_n[r["sha"]]: r["message"] for r in read_jsonl(labeled) if r["sha"] in sha_to_n}


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", type=Path, default=Path("research/data/validation_v2_adjudicated"))
    parser.add_argument("--labeled", type=Path, default=Path("research/data/labeled.jsonl"))
    args = parser.parse_args(argv)
    sample = args.dir / "sample.csv"
    if not sample.exists():
        print(f"{sample} not found.", file=sys.stderr)
        return 1

    registry = load_registry()
    messages = full_messages(args.dir, args.labeled)
    checked, yes_rows, rows = [], 0, 0
    with sample.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            rows += 1
            yes_rows += ANSWERS.get(row["is_migration"].strip().lower()) == "yes"
            out = check_row(row, messages.get(row["n"], row["message"]), registry)
            if out is not None:
                checked.append(out)
    if not checked:
        print(f"No 'yes' row in {sample} has to_model filled in.", file=sys.stderr)
        return 1

    n = len(checked)
    counts = Counter(r["verdict"] for r in checked)
    print(f"Sample: {sample}")
    print(f"  rows labelled yes: {yes_rows}, with to_model filled in: {n}")
    print(f"  full messages found in {args.labeled}: {len(messages)} of {rows} rows")
    print("\nCode vs hand label:")
    for v in VERDICTS:
        print(f"  {VERDICT_NAMES[v]:<38}{counts[v]:>5}  {100 * counts[v] / n:5.1f}%")

    def line(text: str, good: int, total: int) -> None:
        low, high = wilson(good, total)
        share = 100 * good / total if total else 0.0
        print(
            f"  {text:<38}{good:>4} of {total:<4}{share:5.1f}%"
            f"  (95% CI {100 * low:.1f} to {100 * high:.1f})"
        )

    right = counts["match"] + counts["agree_none"]
    providers = right + counts["wrong_same_provider"]
    with_target = n - counts["agree_none"] - counts["extra"]
    print("\nAgreement:")
    line("same target (or both none)", right, n)
    line("same provider (or both none)", providers, n)
    line("hand has a target: code finds it", counts["match"], with_target)

    out = args.dir / "targets_check.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(checked[0]))
        writer.writeheader()
        writer.writerows(checked)
    print(f"\nWritten: {out} (sort by the verdict column to read the disagreements)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
