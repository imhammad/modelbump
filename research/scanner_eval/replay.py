"""Replay the scanner on the evaluation snapshots: would it have warned in time? (ADR 0033)

For each of the 100 migration commits of the scanner's evaluation set, the
snapshot just before the migration is scanned with the current scanner. If it
reports the model the commit moved away from, the project was flagged, and
``modelbump scan --today DAY`` would have warned from the provider's
deprecation notice onwards (``assess`` returns UNKNOWN before it); for models
without a notice date, from RETIRING_SOON, 90 days before the shutdown. This script
reports how often the project was flagged, and how many days the first
warning, and a ``--fail-within 30`` CI failure, came before the developers
actually migrated, with the flagged projects split by why a warning came or
did not (ADR 0034).

It reads the build's outputs and research/data/timing.jsonl (the commit day)
and writes replay.jsonl and replay.json next to them. Nothing else changes.

Run from the repo root, after research.scanner_eval.rescore:
    uv run python -m research.scanner_eval.replay
"""

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from modelbump.registry import Registry, load_registry
from modelbump.scanner.severity import DEFAULT_SOON_DAYS
from research.analysis.lag import median_ci, quantile
from research.filtering.filter import read_jsonl, write_jsonl
from research.scanner_eval.rescore import SETTINGS, TITLES, kept_by, rescan
from research.validation.score import wilson

FAIL_WITHIN = 30  # days, the --fail-within value a CI job would use
WARNED = ("notice", "retiring soon (no notice date)")


def first_warning(
    model_id: str, registry: Registry, committed: date, soon_days: int = DEFAULT_SOON_DAYS
) -> tuple[date | None, str]:
    """When the scanner first warned before ``committed``, and why (or why it did not).

    With a notice date, the warning starts on that day (``assess`` is UNKNOWN
    before it). Without one, as for some Google models, the scanner says
    DEPRECATED on any day, which tells nobody when to act, so the warning that
    counts is RETIRING_SOON, ``soon_days`` before the shutdown.
    """
    found = registry.get(model_id)
    if found is None:
        return None, "unknown model"
    model = found[1]
    if model.announced is not None:
        if committed < model.announced:
            return None, "migrated before the notice"
        return model.announced, "notice"
    soon = model.shutdown - timedelta(days=soon_days)
    if committed < soon:
        return None, "migrated before the warning window"
    return soon, "retiring soon (no notice date)"


def first_failure(model_id: str, registry: Registry, fail_within: int) -> date | None:
    """The first day ``--fail-within`` makes the scan fail for this model."""
    found = registry.get(model_id)
    if found is None:
        return None
    return found[1].shutdown - timedelta(days=fail_within)


def detected(
    model_id: str,
    sha: str,
    findings: Iterable[Mapping[str, Any]],
    registry: Registry,
    setting: str,
) -> bool:
    """True if the scanner reports ``model_id`` (or an alias) in this snapshot."""
    entry = registry.get(model_id)
    if entry is None:
        return False
    keep = kept_by(setting)
    for f in findings:
        if f["sha"] != sha or not f["registry_id"] or not keep(f):
            continue
        found = registry.get(str(f["registry_id"]))
        if found is not None and found[1].id == entry[1].id:
            return True
    return False


def replay_rows(
    commits: Sequence[Mapping[str, Any]],
    committed: Mapping[str, date],
    findings: Sequence[Mapping[str, Any]],
    registry: Registry,
    fail_within: int = FAIL_WITHIN,
) -> list[dict[str, Any]]:
    """One row per commit: was the model flagged, and when would the first warning come."""
    by_sha: dict[str, list[Mapping[str, Any]]] = {}
    for f in findings:
        by_sha.setdefault(str(f["sha"]), []).append(f)
    rows = []
    for commit in commits:
        sha, model_id = str(commit["sha"]), str(commit["model_id"])
        day = committed.get(sha)
        entry = registry.get(model_id)
        if day is None or entry is None:
            continue
        provider, model = entry
        warn, source = first_warning(model_id, registry, day)
        fail = first_failure(model_id, registry, fail_within)
        rows.append(
            {
                "sha": sha,
                "repo": commit["repo"],
                "model_id": model_id,
                "provider": provider.value,
                "committed": day.isoformat(),
                "notice": model.announced.isoformat() if model.announced else None,
                "shutdown": model.shutdown.isoformat(),
                "migrated_after_shutdown": day >= model.shutdown,
                **{
                    f"detected_{s}": detected(model_id, sha, by_sha.get(sha, []), registry, s)
                    for s in SETTINGS
                },
                "first_warning": warn.isoformat() if warn else None,
                "warning": source,
                "warning_days_before_migration": (day - warn).days if warn else None,
                "failure_days_before_migration": (day - fail).days if fail else None,
            }
        )
    return rows


def spread(values: Sequence[int]) -> dict[str, Any]:
    """Median with its 95% interval, and the quartiles."""
    ordered = sorted(values)
    if not ordered:
        return {"n": 0, "median": None, "low": None, "high": None, "q1": None, "q3": None}
    low, high = median_ci(ordered)
    return {
        "n": len(ordered),
        "median": quantile(ordered, 0.5),
        "low": low,
        "high": high,
        "q1": quantile(ordered, 0.25),
        "q3": quantile(ordered, 0.75),
    }


def summarise(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The numbers for the tool paper."""
    result: dict[str, Any] = {"commits": len(rows), "settings": {}}
    for s in SETTINGS:
        flagged = [r for r in rows if r[f"detected_{s}"]]
        low, high = wilson(len(flagged), len(rows))
        late = [r for r in flagged if r["migrated_after_shutdown"]]
        result["settings"][s] = {
            "flagged": len(flagged),
            "share": len(flagged) / len(rows) if rows else None,
            "low": low,
            "high": high,
            "by_warning": dict(Counter(str(r["warning"]) for r in flagged)),
            "warning_days_before_migration": spread(
                [int(r["warning_days_before_migration"]) for r in flagged if r["first_warning"]]
            ),
            "warning_days_by_source": {
                source: spread(
                    [
                        int(r["warning_days_before_migration"])
                        for r in flagged
                        if r["warning"] == source
                    ]
                )
                for source in WARNED
            },
            "migrated_after_shutdown": len(late),
            "failure_days_before_late_migration": spread(
                [int(r["failure_days_before_migration"]) for r in late]
            ),
        }
    return result


def summary(result: Mapping[str, Any]) -> str:
    """What to print at the end of a run."""
    lines = [
        f"Commits replayed: {result['commits']}",
        "",
        f"{'Setting':<30}{'flagged (95% CI)':<26}first warning before migration, median days",
    ]
    for s in SETTINGS:
        r = result["settings"][s]
        w = r["warning_days_before_migration"]
        warn = (
            f"{w['median']:.0f} (95% CI {w['low']} to {w['high']}; n={w['n']})" if w["n"] else "-"
        )
        flagged = f"{r['flagged']} ({r['low']:.0%} to {r['high']:.0%})"
        lines.append(f"{TITLES[s]:<30}{flagged:<26}{warn}")
    r = result["settings"]["all"]
    lines.append("")
    lines.append(f"Flagged projects by first warning ({TITLES['all']}):")
    for source, count in sorted(r["by_warning"].items(), key=lambda item: -item[1]):
        days = r["warning_days_by_source"].get(source)
        extra = (
            f"; median {days['median']:.0f} days before the migration "
            f"(95% CI {days['low']} to {days['high']})"
            if days and days["n"]
            else ""
        )
        lines.append(f"  {source:<36}{count:>4}{extra}")
    f = r["failure_days_before_late_migration"]
    lines.append("")
    lines.append(
        f"Flagged projects that migrated only after the shutdown: {r['migrated_after_shutdown']}"
    )
    if f["n"]:
        lines.append(
            f"For them, --fail-within {FAIL_WITHIN} would have failed CI a median of "
            f"{f['median']:.0f} days (95% CI {f['low']} to {f['high']}) before they migrated."
        )
    return "\n".join(lines)


def committed_days(path: Path) -> dict[str, date]:
    """Commit day by SHA, from research/data/timing.jsonl."""
    return {str(r["sha"]): date.fromisoformat(str(r["committed"])) for r in read_jsonl(path)}


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--dir", type=Path, default=Path("research/data/scanner_eval"))
    parser.add_argument("--timing", type=Path, default=Path("research/data/timing.jsonl"))
    args = parser.parse_args(argv)
    for needed in (args.dir / "commits.jsonl", args.timing):
        if not needed.exists():
            print(f"{needed} not found.", file=sys.stderr)
            return 1
    registry = load_registry()
    commits = list(read_jsonl(args.dir / "commits.jsonl"))
    findings = rescan(commits, args.dir / "snapshots", registry)
    extra = args.dir / "extra"
    findings += rescan([c for c in commits if (extra / str(c["sha"])).is_dir()], extra, registry)
    rows = replay_rows(commits, committed_days(args.timing), findings, registry)
    write_jsonl(rows, args.dir / "replay.jsonl")
    result = summarise(rows)
    (args.dir / "replay.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(summary(result))
    print(f"\nWritten: {args.dir / 'replay.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
