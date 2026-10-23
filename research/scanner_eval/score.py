"""Score the hand labels of the scanner's findings: precision per group and overall.

Reads ``sheet.csv`` after it has been labelled (see the labelling guide in
docs/research/scanner-eval.md), with ``sheet_key.csv`` and ``build.stats.json``
from research.scanner_eval.build. For each group it prints the share of
findings labelled ``yes`` with a 95% Wilson interval. From those it estimates
the scanner's precision over all its findings, weighted by the size of each
group, and the precision with ``--skip-comments`` (documentation left out).
Recall comes from the build and is repeated here so one file holds both.

Run from the repo root:
    uv run python -m research.scanner_eval.score
    uv run python -m research.scanner_eval.score --second research/data/scanner_eval/sheet_b.csv
"""

import argparse
import csv
import json
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from research.scanner_eval.build import GROUPS
from research.validation.score import (
    StratumScore,
    Z,
    cohen_kappa,
    score_strata,
    weighted_precision,
    wilson,
)

# "unclear" is the sheet's word; score_strata calls it "unsure".
ANSWERS = {
    "yes": "yes",
    "y": "yes",
    "no": "no",
    "n": "no",
    "unclear": "unsure",
    "unsure": "unsure",
    "?": "unsure",
}
# What --skip-comments removes from the scanner's output.
SKIPPED_BY_FLAG = ("documentation",)


class SheetError(ValueError):
    """The labelled sheet does not fit its key."""


def read_labels(path: Path) -> tuple[dict[int, str], list[int], list[int]]:
    """Return ({row: "yes" | "no" | "unsure"}, blank rows, rows with an unknown answer)."""
    labels: dict[int, str] = {}
    blank: list[int] = []
    unknown: list[int] = []
    # utf-8-sig: Numbers and Excel may add a byte-order mark when exporting.
    with path.open(newline="", encoding="utf-8-sig") as f:
        for record in csv.DictReader(f):
            if not (record.get("row") or "").strip():
                continue  # an empty line at the end of an export
            row = int(float(record["row"]))  # Numbers may write 7 as 7.0
            answer = (record.get("dependency") or "").strip().lower()
            if not answer:
                blank.append(row)
            elif answer in ANSWERS:
                labels[row] = ANSWERS[answer]
            else:
                unknown.append(row)
    return labels, blank, unknown


def read_key(path: Path) -> dict[int, dict[str, str]]:
    """Return {row: {"group", "context", "detail", "sha"}}."""
    with path.open(newline="", encoding="utf-8") as f:
        return {int(r["row"]): r for r in csv.DictReader(f)}


def check_rows(labelled: Sequence[int], key: Mapping[int, Any]) -> None:
    """Every sheet row must be in the key, and no row may appear twice."""
    extra = sorted(set(labelled) - set(key))
    if extra:
        raise SheetError(f"rows not in sheet_key.csv: {extra[:10]}")
    twice = sorted(n for n, c in Counter(labelled).items() if c > 1)
    if twice:
        raise SheetError(f"rows that appear more than once: {twice[:10]}")


def interval(estimate: float, error: float) -> tuple[float, float]:
    """A normal 95% interval, kept inside 0 to 1."""
    return max(0.0, estimate - Z * error), min(1.0, estimate + Z * error)


def by_context(labels: Mapping[int, str], key: Mapping[int, Mapping[str, str]]) -> dict[str, Any]:
    """Share of yes for each context, unweighted. Shown for interest, not for the estimate."""
    result: dict[str, Any] = {}
    for context in sorted({k["context"] for k in key.values()}):
        answers = Counter(
            labels[n] for n, k in key.items() if k["context"] == context and n in labels
        )
        n = answers["yes"] + answers["no"]
        low, high = wilson(answers["yes"], n)
        result[context] = {
            "labelled": n,
            "yes": answers["yes"],
            "unsure": answers["unsure"],
            "share": answers["yes"] / n if n else None,
            "low": low,
            "high": high,
        }
    return result


def score(
    labels: Mapping[int, str],
    key: Mapping[int, Mapping[str, str]],
    stats: Mapping[str, Any],
) -> dict[str, Any]:
    """Every number of the evaluation."""
    population: dict[str, int] = {g: int(stats["group_population"].get(g, 0)) for g in GROUPS}
    groups = score_strata(labels, {n: k["group"] for n, k in key.items()}, population)
    all_groups = [g for g in GROUPS if population[g]]
    kept_groups = [g for g in all_groups if g not in SKIPPED_BY_FLAG]
    result: dict[str, Any] = {"groups": {g: asdict(s) for g, s in groups.items()}}
    for name, chosen in (("precision", all_groups), ("precision_skip_comments", kept_groups)):
        estimate, error = weighted_precision(groups, chosen)
        low, high = interval(estimate, error)
        result[name] = {
            "estimate": estimate,
            "low": low,
            "high": high,
            "findings": sum(population[g] for g in chosen),
            "groups": chosen,
        }
    result["by_context"] = by_context(labels, key)
    result["recall"] = stats["recall"]
    result["misses_by_reason"] = stats.get("misses_by_reason", {})
    result["unsure"] = sum(1 for a in labels.values() if a == "unsure")
    return result


def report(result: Mapping[str, Any]) -> str:
    """The table and the headline numbers, as printed."""
    lines = [
        f"{'Group':<15}{'findings':>9}{'labelled':>10}{'yes':>6}{'unclear':>9}   precision (95% CI)"
    ]
    for name, fields in result["groups"].items():
        s = StratumScore(**fields)
        share = f"{s.share:6.1%} ({s.low:.1%} to {s.high:.1%})" if s.labelled else "     -"
        lines.append(
            f"{name:<15}{s.population:>9,}{s.labelled:>10}{s.yes:>6}{s.unsure:>9}   {share}"
        )
    lines.append("")
    for name, title in (
        ("precision", "Precision, all findings (weighted)"),
        ("precision_skip_comments", "Precision with --skip-comments"),
    ):
        p = result[name]
        lines.append(
            f"{title + ':':<38}{p['estimate']:.1%} (95% CI {p['low']:.1%} to {p['high']:.1%}),"
            f" {p['findings']:,} findings"
        )
    recall = result["recall"]
    if recall.get("n"):
        lines.append(
            f"{'Recall on known sites (from build):':<38}{recall['share']:.1%} "
            f"(95% CI {recall['low']:.1%} to {recall['high']:.1%}), {recall['n']} sites"
        )
    lines.append("")
    lines.append("By context (unweighted):")
    for context, c in result["by_context"].items():
        share = f"{c['share']:.1%}" if c["labelled"] else "-"
        lines.append(f"  {context:<15}{c['yes']:>4} of {c['labelled']:<4}{share:>7}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--dir", type=Path, default=Path("research/data/scanner_eval"))
    parser.add_argument("--second", type=Path, help="The same sheet, labelled by someone else.")
    args = parser.parse_args(argv)
    sheet = args.dir / "sheet.csv"
    if not sheet.exists():
        print(f"{sheet} not found. Run research.scanner_eval.build first.", file=sys.stderr)
        return 1

    labels, blank, unknown = read_labels(sheet)
    key = read_key(args.dir / "sheet_key.csv")
    stats = json.loads((args.dir / "build.stats.json").read_text(encoding="utf-8"))
    try:
        check_rows([*labels, *blank, *unknown], key)
    except SheetError as error:
        print(f"sheet.csv does not match sheet_key.csv: {error}", file=sys.stderr)
        return 1
    if unknown:
        print(
            f"Rows with an answer that is not yes, no or unclear: {unknown[:20]}. "
            "Fix them and run again.",
            file=sys.stderr,
        )
        return 1
    missing = len(key) - len(labels)
    if missing:
        print(f"Note: {missing} of {len(key)} rows have no label yet; scoring the rest.\n")

    result = score(labels, key, stats)
    print(report(result))
    result["rows"] = len(key)
    result["labelled_rows"] = len(labels)
    result["blank_rows"] = missing
    if args.second is not None:
        second, _, _ = read_labels(args.second)
        kappa, shared = cohen_kappa(labels, second)
        print(f"\nAgreement (Cohen's kappa) over {shared} rows: {kappa:.2f}")
        result["kappa"] = kappa
        result["kappa_rows"] = shared
    out = args.dir / "scanner_eval.json"
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"\nWritten: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
