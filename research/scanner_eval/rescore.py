"""Re-score the labelled findings with the current scanner (ADR 0032).

The labels in ``sheet.csv`` belong to findings of the scanner version that
built the set (research.scanner_eval.build). A newer scanner finds the same IDs
at the same places, because the text finder did not change, but it may give
them a new context. This script scans the same snapshots again, gives every
labelled row its new context, and estimates precision and recall for four
settings: all findings, ``--skip-comments``, ``--skip-tests``, and both.

Precision keeps the strata the sheet was drawn from: within each group, the
labelled rows a setting keeps estimate the share of real dependencies among
the group's findings it keeps, and the groups are weighted by those exact
counts. Recall re-checks every known site. Files the old scanner did not read
are fetched one by one from raw.githubusercontent.com for the missed sites
only, so recall shows what the new file types gain. Nothing the build wrote is
changed.

Run from the repo root, after research.scanner_eval.score:
    uv run python -m research.scanner_eval.rescore
"""

import argparse
import csv
import json
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx

from modelbump.registry import Registry, load_registry
from modelbump.scanner import scan_path
from modelbump.scanner.context import DOCUMENTATION
from modelbump.scanner.files import MAX_BYTES, is_scannable, is_test_path
from research.filtering.filter import read_jsonl, write_jsonl
from research.scanner_eval.build import GROUPS, PER_GROUP, SHEET_SEED, draw_sheet
from research.scanner_eval.score import interval, read_labels
from research.validation.score import StratumScore, weighted_precision, wilson

RAW_URL = "https://raw.githubusercontent.com/{repo}/{ref}/{path}"
_DOCUMENTATION = frozenset(c.value for c in DOCUMENTATION)
Key = tuple[str, str, int, int]  # sha, path, line, column


def kept_by(name: str) -> Callable[[Mapping[str, Any]], bool]:
    """Whether a finding stays in the report under one of the four settings."""
    skip_comments = name in {"skip_comments", "both"}
    skip_tests = name in {"skip_tests", "both"}

    def keep(finding: Mapping[str, Any]) -> bool:
        if skip_comments and finding["context"] in _DOCUMENTATION:
            return False
        return not (skip_tests and is_test_path(str(finding["path"])))

    return keep


SETTINGS = ("all", "skip_comments", "skip_tests", "both")


class SheetMismatchError(ValueError):
    """The sheet cannot be matched to the findings it was drawn from."""


def key_of(finding: Mapping[str, Any]) -> Key:
    return (str(finding["sha"]), str(finding["path"]), int(finding["line"]), int(finding["column"]))


def sheet_findings(
    old_findings: Sequence[Mapping[str, Any]], sheet: Path, per_group: int, seed: int
) -> dict[int, dict[str, Any]]:
    """Each sheet row's finding, by drawing the sheet again exactly as the build did."""
    chosen = draw_sheet(old_findings, per_group, seed)
    with sheet.open(newline="", encoding="utf-8-sig") as f:
        rows = {int(float(r["row"])): r for r in csv.DictReader(f) if (r.get("row") or "").strip()}
    if len(rows) != len(chosen):
        raise SheetMismatchError(f"sheet has {len(rows)} rows, the draw has {len(chosen)}")
    result = {}
    for n, finding in enumerate(chosen, start=1):
        row = rows.get(n)
        same = row is not None and (row["path"], int(float(row["line"])), row["model_id"]) == (
            finding["path"],
            int(finding["line"]),
            finding["model_id"],
        )
        if not same:
            raise SheetMismatchError(f"row {n} is not the finding the build drew")
        result[n] = finding
    return result


def rescan(
    commits: Iterable[Mapping[str, Any]], snapshots: Path, registry: Registry
) -> list[dict[str, Any]]:
    """Every finding of the current scanner in every snapshot."""
    rows: list[dict[str, Any]] = []
    for commit in commits:
        result = scan_path(snapshots / str(commit["sha"]), registry)
        rows.extend(
            {
                "sha": commit["sha"],
                "path": f.path,
                "line": f.line,
                "column": f.column,
                "model_id": f.model_id,
                "registry_id": f.registry_id,
                "context": f.context.value,
                "detail": f.detail,
            }
            for f in result.findings
        )
    return rows


def precision(
    labelled: Mapping[int, Mapping[str, Any]],
    labels: Mapping[int, str],
    old_group: Mapping[Key, str],
    new_findings: Sequence[Mapping[str, Any]],
    setting: str,
) -> dict[str, Any]:
    """Weighted precision of one setting, within the strata the sheet was drawn from."""
    keep = kept_by(setting)
    population = Counter(old_group[key_of(f)] for f in new_findings if keep(f))
    by_key = {key_of(f): f for f in new_findings}
    scores = {}
    for group in GROUPS:
        answers = Counter(
            labels[n]
            for n, old in labelled.items()
            if old["group"] == group and n in labels and keep(by_key[key_of(old)])
        )
        n = answers["yes"] + answers["no"]
        low, high = wilson(answers["yes"], n)
        scores[group] = StratumScore(
            population=population[group],
            labelled=n,
            yes=answers["yes"],
            unsure=answers["unsure"],
            share=answers["yes"] / n if n else 0.0,
            low=low,
            high=high,
        )
    used = [g for g in GROUPS if scores[g].population and scores[g].labelled]
    estimate, error = weighted_precision(scores, used)
    low, high = interval(estimate, error)
    return {
        "estimate": estimate,
        "low": low,
        "high": high,
        "findings": sum(population.values()),
        "labelled_kept": sum(scores[g].labelled for g in GROUPS),
        "groups": _as_dicts(scores),
        "unestimated_findings": sum(scores[g].population for g in GROUPS if g not in used),
    }


def _as_dicts(scores: Mapping[str, StratumScore]) -> dict[str, dict[str, Any]]:
    return {
        g: {"population": s.population, "labelled": s.labelled, "yes": s.yes, "share": s.share}
        for g, s in scores.items()
    }


def fetch_missing(
    sites: Iterable[Mapping[str, Any]],
    parents: Mapping[str, str],
    repos: Mapping[str, str],
    extra: Path,
    http: httpx.Client | None,
) -> Counter[str]:
    """Download the files of missed sites that the scanner reads now but did not before."""
    outcome: Counter[str] = Counter()
    wanted = sorted(
        {
            (str(s["sha"]), str(s["path"]))
            for s in sites
            if not s["found"]
            and s["reason"] == "file type not scanned"
            and is_scannable(Path(str(s["path"])))
        }
    )
    for sha, path in wanted:
        target = extra / sha / path
        if target.exists():
            outcome["cached"] += 1
            continue
        if http is None:
            outcome["not fetched"] += 1
            continue
        url = RAW_URL.format(repo=repos[sha], ref=parents[sha], path=path)
        response = http.get(url)
        if response.status_code != 200:
            outcome[f"failed ({response.status_code})"] += 1
            continue
        if len(response.content) > MAX_BYTES:
            outcome["too big to scan"] += 1  # the scanner skips files over 1 MB too
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(response.content)
        outcome["fetched"] += 1
    return outcome


def recall(
    sites: Sequence[Mapping[str, Any]],
    findings: Sequence[Mapping[str, Any]],
    setting: str,
) -> dict[str, Any]:
    """Share of known sites the scanner reports, under one setting."""
    keep = kept_by(setting)
    reported: dict[tuple[str, str, int], set[str]] = {}
    for f in findings:
        if keep(f):
            ids = reported.setdefault((str(f["sha"]), str(f["path"]), int(f["line"])), set())
            ids.add(str(f["model_id"]))
            if f["registry_id"]:
                ids.add(str(f["registry_id"]))
    hits = sum(
        1
        for s in sites
        if str(s["model_id"])
        in reported.get((str(s["sha"]), str(s["path"]), int(s["line"])), set())
    )
    low, high = wilson(hits, len(sites))
    return {
        "yes": hits,
        "n": len(sites),
        "share": hits / len(sites) if sites else None,
        "low": low,
        "high": high,
    }


def rescore(
    out_dir: Path,
    registry: Registry,
    http: httpx.Client | None,
    *,
    per_group: int = PER_GROUP,
    seed: int = SHEET_SEED,
) -> dict[str, Any]:
    """Every number of the re-scoring."""
    commits = list(read_jsonl(out_dir / "commits.jsonl"))
    old_findings = list(read_jsonl(out_dir / "findings.jsonl"))
    sites = list(read_jsonl(out_dir / "sites.jsonl"))
    labels, _, unknown = read_labels(out_dir / "sheet.csv")
    if unknown:
        raise SheetMismatchError(
            f"rows with an answer that is not yes, no or unclear: {unknown[:20]}"
        )
    labelled = sheet_findings(old_findings, out_dir / "sheet.csv", per_group, seed)
    old_group = {
        key_of(f): name
        for f in old_findings
        for name, contexts in GROUPS.items()
        if f["context"] in contexts
    }
    new_findings = rescan(commits, out_dir / "snapshots", registry)
    if {key_of(f) for f in new_findings} != set(old_group):
        raise SheetMismatchError(
            "the scanner now finds IDs at other places; re-scoring needs the same findings"
        )
    write_jsonl(new_findings, out_dir / "rescore.findings.jsonl")

    extra = out_dir / "extra"
    fetched = fetch_missing(
        sites,
        {str(c["sha"]): str(c["parent"]) for c in commits},
        {str(c["sha"]): str(c["repo"]) for c in commits},
        extra,
        http,
    )
    extra_findings = rescan(
        [c for c in commits if (extra / str(c["sha"])).is_dir()], extra, registry
    )
    return {
        "findings_by_context": dict(Counter(str(f["context"]) for f in new_findings)),
        "changed_labelled_rows": _changes(labelled, labels, new_findings),
        "precision": {s: precision(labelled, labels, old_group, new_findings, s) for s in SETTINGS},
        "missing_files": dict(fetched),
        "recall_snapshots": recall(sites, new_findings, "all"),
        "recall": {s: recall(sites, [*new_findings, *extra_findings], s) for s in SETTINGS},
    }


def _changes(
    labelled: Mapping[int, Mapping[str, Any]],
    labels: Mapping[int, str],
    new_findings: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Labelled rows whose context changed, counted by old context, new context and label."""
    by_key = {key_of(f): f for f in new_findings}
    counts = Counter(
        (str(old["context"]), str(by_key[key_of(old)]["context"]), labels.get(n, "blank"))
        for n, old in labelled.items()
        if by_key[key_of(old)]["context"] != old["context"]
    )
    return [
        {"from": a, "to": b, "label": label, "rows": count}
        for (a, b, label), count in sorted(counts.items())
    ]


TITLES = {
    "all": "All findings",
    "skip_comments": "--skip-comments",
    "skip_tests": "--skip-tests",
    "both": "--skip-comments --skip-tests",
}


def summary(result: Mapping[str, Any]) -> str:
    """What to print at the end of a run."""
    lines = [f"{'Setting':<30}{'findings':>9}   precision (95% CI)        recall (95% CI)"]
    for s in SETTINGS:
        p, r = result["precision"][s], result["recall"][s]
        lines.append(
            f"{TITLES[s]:<30}{p['findings']:>9,}   "
            f"{p['estimate']:6.1%} ({p['low']:.1%} to {p['high']:.1%})   "
            f"{r['share']:6.1%} ({r['low']:.1%} to {r['high']:.1%})"
        )
    snap = result["recall_snapshots"]
    lines.append("")
    lines.append(
        f"Recall in the old snapshots only: {snap['share']:.1%} "
        f"({snap['yes']} of {snap['n']} sites)"
    )
    lines.append(f"Missed files fetched: {result['missing_files'] or 'none needed'}")
    lines.append("")
    lines.append("Labelled rows with a new context:")
    for change in result["changed_labelled_rows"]:
        lines.append(
            f"  {change['from']:>13} -> {change['to']:<9} {change['label']:<6} {change['rows']:>3}"
        )
    if not result["changed_labelled_rows"]:
        lines.append("  none")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None, http: httpx.Client | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--dir", type=Path, default=Path("research/data/scanner_eval"))
    parser.add_argument(
        "--no-fetch", action="store_true", help="Do not download the files of missed sites."
    )
    args = parser.parse_args(argv)
    needed = ("commits.jsonl", "findings.jsonl", "sites.jsonl", "sheet.csv")
    missing = [name for name in needed if not (args.dir / name).exists()]
    if missing:
        print(f"Missing in {args.dir}: {', '.join(missing)}. Run the build first.", file=sys.stderr)
        return 1
    client = None if args.no_fetch else (http or httpx.Client(timeout=30, follow_redirects=True))
    try:
        result = rescore(args.dir, load_registry(), client)
    except SheetMismatchError as error:
        print(f"Cannot re-score: {error}", file=sys.stderr)
        return 1
    finally:
        if client is not None and http is None:
            client.close()
    out = args.dir / "rescore.json"
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(summary(result))
    print(f"\nWritten: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
