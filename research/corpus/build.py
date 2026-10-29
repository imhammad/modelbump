"""Build the benchmark corpus: real Python LLM apps, as they were before a migration (ADR 0057).

The apps come from the same random order as the scanner evaluation
(research.scanner_eval.build, seed 2030): migration commits from Paper 1's
data, each downloaded as it was just *before* the migration. The first 100
of those snapshots are already on disk from that evaluation and are reused;
later ones are downloaded and cached under ``--out``.

Each snapshot is screened in that order. An app joins the corpus when:

1. its repository is not in the corpus yet (one snapshot per repository), and
2. ModelBump finds at least one LLM call outside its tests whose prompt has
   written text (a library that only passes prompts through has none), and
3. that call does not pass tools (tool calls are not scored yet).

Screening stops when the corpus has ``--target`` apps. Nothing here calls a
model: this step only measures what the synthesizer finds in each app.

Run from the repo root:
    export GITHUB_TOKEN=$(gh auth token)
    uv run python -m research.corpus.build
"""

import argparse
import json
import os
import random
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from modelbump.oracles import OutputKind, choose_oracle
from modelbump.synth.cases import CaseResult, find_cases
from research.enrichment.files import CommitFilesClient
from research.filtering.filter import read_jsonl, write_jsonl
from research.mining.github_search import RateLimitError
from research.scanner_eval.build import SEED, SnapshotFetcher, eligible_commits

TARGET = 40
MAX_SCREENED = 400
"""Snapshots screened at most, cached or not, so a run always ends."""


class Snapshots:
    """Snapshots from the scanner evaluation when they exist, else new downloads."""

    def __init__(self, reuse_dir: Path, fetcher: SnapshotFetcher) -> None:
        self.reuse_dir = reuse_dir
        self.fetcher = fetcher
        self.reused = 0

    def get(self, repo: str, sha: str) -> tuple[dict[str, Any], Path]:
        """The snapshot's metadata and the folder that holds its files."""
        meta_path = self.reuse_dir / f"{sha}.json"
        if meta_path.exists():
            meta: dict[str, Any] = json.loads(meta_path.read_text(encoding="utf-8"))
            self.reused += 1
            return meta, self.reuse_dir / sha
        return self.fetcher.snapshot(repo, sha), self.fetcher.out_dir / sha


def measure(result: CaseResult) -> dict[str, Any]:
    """What the synthesizer finds in one app: calls, prompts, oracles and test inputs."""
    sites = [entry.site for entry in result.sites]
    kinds = [choose_oracle(site).kind for site in sites]
    with_text = [
        site
        for site, kind in zip(sites, kinds, strict=True)
        if kind is not OutputKind.TOOLS and any(part.has_text for part in site.parts)
    ]
    return {
        "python_files": result.files_read,
        "unparsed": len(result.unparsed),
        "calls": len(sites),
        "calls_by_api": dict(Counter(site.api.value for site in sites)),
        "calls_by_oracle": dict(Counter(kind.value for kind in kinds)),
        "calls_with_text": len(with_text),
        "complete": sum(site.complete for site in sites),
        "fixed": sum(site.complete and not site.slots for site in sites),
        "with_slots": sum(bool(site.slots) for site in sites),
        "calls_with_caller_cases": sum(
            any(case.complete for case in entry.cases) for entry in result.sites
        ),
        "app_models": sorted({site.model for site in sites if site.model}),
    }


def screen(meta: Mapping[str, Any], folder: Path) -> tuple[str, dict[str, Any]]:
    """``("ok", measures)`` for an app that joins the corpus, else the reason and measures."""
    if meta.get("status") != "ok":
        return f"no snapshot: {meta.get('status')}", {}
    if not any(folder.rglob("*.py")):
        return "no Python files", {}
    measures = measure(find_cases(folder, skip_tests=True))
    if not measures["calls"]:
        return "no LLM call found", measures
    if not measures["calls_with_text"]:
        return "no call with written prompt text", measures
    return "ok", measures


def build(
    rows: Iterable[Mapping[str, Any]],
    cache_dir: Path,
    snapshots: Snapshots,
    out_dir: Path,
    *,
    target: int = TARGET,
    seed: int = SEED,
    max_screened: int = MAX_SCREENED,
    progress: Callable[[str], None] = lambda line: None,
) -> dict[str, Any]:
    """Screen snapshots in the scanner evaluation's order and write the corpus files."""
    population = eligible_commits(rows, cache_dir)
    order = random.Random(seed).sample(population, len(population))
    apps: list[dict[str, Any]] = []
    screened: list[dict[str, Any]] = []
    seen: set[str] = set()
    for commit in order[:max_screened]:
        if len(apps) >= target:
            break
        repo, sha = str(commit["repo"]), str(commit["sha"])
        if repo in seen:
            # Checked before downloading, so a second snapshot of a repo costs nothing.
            screened.append({"sha": sha, "repo": repo, "reason": "repository already in corpus"})
            continue
        meta, folder = snapshots.get(repo, sha)
        reason, measures = screen(meta, folder)
        screened.append({"sha": sha, "repo": repo, "reason": reason, **measures})
        if reason == "ok":
            seen.add(repo)
            apps.append(
                {
                    "app": len(apps) + 1,
                    "repo": repo,
                    "sha": sha,
                    "parent": meta["parent"],
                    "retired_model": commit["model_id"],
                    "folder": str(folder),
                    "url": f"https://github.com/{repo}/tree/{meta['parent']}",
                    **measures,
                }
            )
        progress(
            f"{len(screened)} screened, {len(apps)}/{target} apps "
            f"({snapshots.fetcher.downloads} downloaded)"
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(apps, out_dir / "apps.jsonl")
    write_jsonl(screened, out_dir / "screened.jsonl")
    (out_dir / "apps.txt").write_text(
        "".join(f"{app['folder']}\n" for app in apps), encoding="utf-8"
    )
    stats = corpus_stats(apps, screened, len(population), seed, target)
    (out_dir / "corpus.stats.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    return stats


def _total(apps: Sequence[Mapping[str, Any]], key: str) -> int:
    return sum(int(app[key]) for app in apps)


def _merged(apps: Sequence[Mapping[str, Any]], key: str) -> dict[str, int]:
    out: Counter[str] = Counter()
    for app in apps:
        out.update(app[key])
    return dict(out.most_common())


def corpus_stats(
    apps: Sequence[Mapping[str, Any]],
    screened: Sequence[Mapping[str, Any]],
    population: int,
    seed: int,
    target: int,
) -> dict[str, Any]:
    """The numbers for the paper: how the corpus was drawn and what is in it."""
    return {
        "seed": seed,
        "target": target,
        "eligible_commits": population,
        "screened": len(screened),
        "apps": len(apps),
        "left_out": dict(Counter(str(s["reason"]) for s in screened if s["reason"] != "ok")),
        "python_files": _total(apps, "python_files"),
        "calls": _total(apps, "calls"),
        "calls_with_text": _total(apps, "calls_with_text"),
        "complete": _total(apps, "complete"),
        "fixed": _total(apps, "fixed"),
        "with_slots": _total(apps, "with_slots"),
        "calls_with_caller_cases": _total(apps, "calls_with_caller_cases"),
        "apps_with_caller_cases": sum(1 for app in apps if app["calls_with_caller_cases"]),
        "calls_by_api": _merged(apps, "calls_by_api"),
        "calls_by_oracle": _merged(apps, "calls_by_oracle"),
        "apps_by_oracle": dict(
            Counter(kind for app in apps for kind in app["calls_by_oracle"]).most_common()
        ),
        "retired_models": dict(Counter(str(app["retired_model"]) for app in apps).most_common()),
    }


def summary(stats: Mapping[str, Any]) -> str:
    """What to print at the end of a run."""
    return "\n".join(
        [
            f"Corpus: {stats['apps']} {'app' if stats['apps'] == 1 else 'apps'} "
            f"(target {stats['target']}), "
            f"{stats['screened']} snapshots screened of {stats['eligible_commits']} eligible",
            f"Left out: {stats['left_out'] or 'none'}",
            f"Python files: {stats['python_files']:,}; LLM calls: {stats['calls']:,} "
            f"({stats['calls_with_text']} with prompt text, {stats['complete']} complete, "
            f"{stats['fixed']} fixed, {stats['with_slots']} with slots)",
            f"Calls by API: {stats['calls_by_api']}",
            f"Calls by oracle: {stats['calls_by_oracle']}",
            f"Apps with each oracle: {stats['apps_by_oracle']}",
            f"Test inputs from the app's own code: {stats['calls_with_caller_cases']} calls "
            f"in {stats['apps_with_caller_cases']} apps",
        ]
    )


def main(argv: Sequence[str] | None = None, client: CommitFilesClient | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--files", type=Path, default=Path("research/data/files.jsonl"))
    parser.add_argument("--cache", type=Path, default=Path("research/data/cache/commit_files"))
    parser.add_argument(
        "--reuse",
        type=Path,
        default=Path("research/data/scanner_eval/snapshots"),
        help="Snapshots already downloaded by the scanner evaluation.",
    )
    parser.add_argument("--out", type=Path, default=Path("research/data/corpus"))
    parser.add_argument("--target", type=int, default=TARGET, help=f"Apps (default {TARGET}).")
    parser.add_argument(
        "--max-screened",
        type=int,
        default=MAX_SCREENED,
        help=f"Snapshots screened at most (default {MAX_SCREENED}).",
    )
    parser.add_argument(
        "--interval", type=float, default=1.0, help="Seconds between requests (default 1)."
    )
    args = parser.parse_args(argv)
    if not args.files.exists():
        print(f"{args.files} not found. Run research.enrichment.files first.", file=sys.stderr)
        return 1
    if client is None:
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            print("Set GITHUB_TOKEN first:  export GITHUB_TOKEN=$(gh auth token)", file=sys.stderr)
            return 1
        client = CommitFilesClient(args.out / "cache", token, min_interval=args.interval)
    snapshots = Snapshots(args.reuse, SnapshotFetcher(client, args.out / "snapshots"))
    try:
        stats = build(
            read_jsonl(args.files),
            args.cache,
            snapshots,
            args.out,
            target=args.target,
            max_screened=args.max_screened,
            progress=lambda line: print(line, file=sys.stderr),
        )
    except RateLimitError as error:
        print(f"{error}. Everything so far is cached; run the same command again later.")
        return 3
    print(summary(stats))
    print(f"Reused {snapshots.reused} snapshots, downloaded {snapshots.fetcher.downloads}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
