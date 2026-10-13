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
import re
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from modelbump.registry import Registry, load_registry
from research.enrichment.targets import (
    base,
    clean,
    extract_target,
    family,
    model_tokens,
    provider_of,
    same_entry,
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
    "hand_not_model",
)
VERDICT_NAMES = {
    "match": "same model",
    "agree_none": "both say no target",
    "wrong_same_provider": "other model, same provider",
    "wrong_other_provider": "other model, other provider",
    "missed": "hand has a target, code found none",
    "extra": "hand says none, code found one",
    "hand_not_model": "hand label names no model ID (left out)",
}


def hand_target(text: str) -> str | None:
    """The model in a hand-written ``to_model`` cell, or None for "none"."""
    text = text.strip()
    if text.lower() in NO_TARGET:
        return None
    tokens = model_tokens(text)
    return tokens[0] if tokens else clean(text).replace(" ", "-")


def less_specific(hand: str, found: str) -> bool:
    """True if the hand label wrote only a version that the found ID extends.

    "gemini-2.5" for "gemini-2.5-flash", "llama-3.3-70b" for
    "llama-3.3-70b-versatile". Not for GPT names, where "gpt-4" and
    "gpt-4-turbo" are different models.
    """
    return (
        base(found).startswith(base(hand) + "-")
        and re.search(r"\d+b?$", hand) is not None
        and family(hand) != "gpt"
    )


def verdict(hand: str | None, found: str | None, registry: Registry) -> str:
    """How the extracted target compares with the hand label.

    A hand label that is less specific than the code's target ("gemini-2.5" for
    "gemini-2.5-flash") counts as the same model. A hand label with no model ID
    in it ("current haiku alias") cannot be compared and is left out.
    """
    if hand is not None and not model_tokens(hand):
        return "hand_not_model"
    if hand is None:
        return "agree_none" if found is None else "extra"
    if found is None:
        return "missed"
    if same_model(hand, found, registry) or less_specific(hand, found):
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
    left_id = left[0] if left else ""
    # The check measures the target for a given model left. When the commit
    # leaves several models and the hand label picked another one, use that one.
    hand_left = clean(row.get("from_model", ""))
    from_hand = bool(hand_left) and registry.get(hand_left) is not None
    from_hand = from_hand and not (left_id and same_entry(left_id, hand_left, registry))
    if from_hand or not left_id:
        left_id = hand_left
    found, method = extract_target(message, left_id, registry) if left_id else (None, None)
    hand = hand_target(row["to_model"])
    return {
        "n": row["n"],
        "url": row["url"],
        "from_model": row.get("from_model", ""),
        "left": left_id,
        "left_from_hand": from_hand,
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

    counts = Counter(r["verdict"] for r in checked)
    n = len(checked) - counts["hand_not_model"]
    print(f"Sample: {sample}")
    print(f"  rows labelled yes: {yes_rows}, with to_model filled in: {n}")
    print(f"  full messages found in {args.labeled}: {len(messages)} of {rows} rows")
    print(f"  hand label names no model ID (left out): {counts['hand_not_model']}")
    print(f"  rows compared: {n}")
    print(f"  model left taken from the hand label: {sum(r['left_from_hand'] for r in checked)}")
    print("\nCode vs hand label:")
    for v in VERDICTS[:-1]:
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
    named = counts["match"] + counts["wrong_same_provider"] + counts["wrong_other_provider"]
    named += counts["extra"]
    print("\nAgreement:")
    line("same target (or both none)", right, n)
    line("same provider (or both none)", providers, n)
    line("hand has a target: code finds it", counts["match"], with_target)
    line("code names a target: it is right", counts["match"], named)
    line(
        "code names a target: right provider",
        counts["match"] + counts["wrong_same_provider"],
        named,
    )

    out = args.dir / "targets_check.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(checked[0]))
        writer.writeheader()
        writer.writerows(checked)
    print(f"\nWritten: {out} (sort by the verdict column to read the disagreements)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
