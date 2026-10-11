"""Find candidate migration commits on GitHub.

For every retired model ID in the registry we search commit messages that
mention it, one time window at a time. When a window has more results than
GitHub will return (1,000), we split it in half and search each half, so
nothing is silently cut off. Forks are dropped and commits are de-duplicated
by SHA: the same commit often lives in many repositories (copies, mirrors,
templates), and we keep it once while recording every repository. Deciding
which candidates are real migrations is a separate step.

Some IDs (gpt-4, gpt-3.5-turbo ...) are mentioned in so many commits that
reading all of them would take days. For an ID with more than ``--focus-above``
results (50,000 by default) we search only from 30 days before the provider's
deprecation notice: Kim (2026) excludes older commits anyway, because they
cannot be reactions to the notice. See ADR 0011.

Run from the repo root:
    export GITHUB_TOKEN=$(gh auth token)
    uv run python -m research.mining.miner --only claude-3-haiku-20240307
    uv run python -m research.mining.miner --counts   # only count results per ID
"""

import argparse
import json
import os
import re
import sys
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from modelbump.registry import Registry, load_registry
from research.mining.github_search import (
    MAX_RESULTS,
    PER_PAGE,
    CommitSearchClient,
    NetworkError,
    RateLimitError,
    ServerError,
)

# IDs that are ordinary English words or too short: searching them would
# return mostly unrelated commits. Their dated snapshots are still searched.
SKIPPED_IDS = frozenset({"ada", "babbage", "curie", "davinci", "o1"})

# An ID with more results than this is searched only from shortly before its
# deprecation notice (ADR 0011).
FOCUS_ABOVE = 50_000

# Kim (2026, Section 3) excludes commits made more than 30 days before the notice.
BEFORE_NOTICE = timedelta(days=30)

Progress = Callable[[str], None]


def mentions(message: str, model_id: str) -> bool:
    """True if ``model_id`` appears in ``message`` as a whole ID.

    GitHub's search is fuzzy: a search for one ID also returns commits that
    only share part of it (even a SHA that starts with the same digits). We
    keep a result only if the exact ID is in the message. Letters, digits,
    "-" and "." count as part of an ID, so "gpt-4" does not match "gpt-4o"
    or "gpt-4-turbo"; a full stop at the end of a sentence is still allowed.
    """
    pattern = rf"(?<![\w.-]){re.escape(model_id)}(?![\w-]|\.\w)"
    return re.search(pattern, message, flags=re.IGNORECASE) is not None


@dataclass(frozen=True)
class Window:
    """An inclusive range of commit dates."""

    start: date
    end: date

    def qualifier(self) -> str:
        return f"committer-date:{self.start.isoformat()}..{self.end.isoformat()}"

    def can_split(self) -> bool:
        return self.start < self.end

    def split(self) -> tuple["Window", "Window"]:
        middle = self.start + (self.end - self.start) // 2
        return Window(self.start, middle), Window(middle + timedelta(days=1), self.end)


@dataclass
class Candidate:
    """One commit whose message mentions a retired model ID."""

    sha: str
    repo: str
    repos: list[str]
    url: str
    committed_at: str
    message: str
    matched_ids: list[str]
    providers: list[str]


@dataclass
class MiningStats:
    """Counts reported at the end of a run and kept for the paper."""

    start: str = ""
    end: str = ""
    model_ids: int = 0
    queries: int = 0
    items_seen: int = 0
    forks_skipped: int = 0
    not_in_message: int = 0
    duplicates: int = 0
    copies_in_other_repos: int = 0
    focus_above: int = FOCUS_ABOVE
    model_totals: dict[str, int] = field(default_factory=dict)
    focused_starts: dict[str, str] = field(default_factory=dict)
    too_big_without_notice: list[str] = field(default_factory=list)
    truncated_windows: list[str] = field(default_factory=list)
    failed_windows: list[str] = field(default_factory=list)


def build_query(model_id: str, window: Window) -> str:
    """Search for the exact model ID in commit messages, inside one window."""
    return f'"{model_id}" {window.qualifier()}'


def search_window(
    client: CommitSearchClient,
    model_id: str,
    window: Window,
    stats: MiningStats,
    progress: Progress | None = None,
    first: dict[str, Any] | None = None,
    requests_before: int | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield every result for ``model_id`` in ``window``, splitting when needed.

    The window is split when it has more than 1,000 results, and also when
    GitHub keeps failing on it: smaller searches are faster for GitHub to answer.
    ``first`` is page 1 of this exact search, when the caller already has it,
    and ``requests_before`` is the client's request count before it was fetched.
    """
    query = build_query(model_id, window)
    if requests_before is None:
        requests_before = client.requests_made
    items: list[dict[str, Any]] = []
    try:
        if first is None:
            first = client.search(query, 1)
            stats.queries += 1
        total = int(first["total_count"])
        split = total > MAX_RESULTS and window.can_split()
        if not split:
            items.extend(first["items"])
            pages = -(-min(total, MAX_RESULTS) // PER_PAGE)  # ceiling division
            for page in range(2, pages + 1):
                stats.queries += 1
                items.extend(client.search(query, page)["items"])
    except ServerError:
        if not window.can_split():
            stats.failed_windows.append(query)
            if progress is not None:
                progress(f"    {window.start}..{window.end}: GitHub kept failing, skipped")
            return
        if progress is not None:
            progress(
                f"    {window.start}..{window.end}: GitHub kept failing, trying smaller windows"
            )
        split = True
    if split:
        for half in window.split():
            yield from search_window(client, model_id, half, stats, progress)
        return
    if total > MAX_RESULTS:
        # A single day with more than 1,000 results: we can only see the first 1,000.
        stats.truncated_windows.append(query)
    yield from items
    if progress is not None and client.requests_made > requests_before:
        # Only windows that needed GitHub are shown; cached ones replay silently.
        progress(f"    {window.start}..{window.end}: {total:,} results")


def focus_starts(registry: Registry) -> dict[str, date]:
    """Return, for every ID with a known deprecation notice, the day to search from.

    That is 30 days before the earliest notice, counting rescheduled plans.
    """
    starts = {}
    for _, model in registry:
        notices = [model.announced, *(plan.announced for plan in model.superseded)]
        known = [day for day in notices if day is not None]
        if known:
            for model_id in model.all_ids():
                starts[model_id] = min(known) - BEFORE_NOTICE
    return starts


def model_ids_to_search(registry: Registry, only: Sequence[str] = ()) -> list[tuple[str, str]]:
    """Return (provider, model_id) pairs for every searchable ID and alias."""
    pairs = []
    for provider, model in registry:
        for model_id in model.all_ids():
            if model_id in SKIPPED_IDS or (only and model_id not in only):
                continue
            pairs.append((provider.value, model_id))
    return pairs


def search_model(
    client: CommitSearchClient,
    model_id: str,
    window: Window,
    stats: MiningStats,
    progress: Progress | None = None,
    start: date | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield the results for one ID; if it is huge, only those from ``start`` on."""
    requests_before = client.requests_made
    first = client.search(build_query(model_id, window), 1)
    stats.queries += 1
    total = int(first["total_count"])
    stats.model_totals[model_id] = total
    if total > stats.focus_above and start is None:
        stats.too_big_without_notice.append(model_id)
        if progress is not None:
            progress(f"    {total:,} results, but no deprecation notice date: searching all")
    if total <= stats.focus_above or start is None:
        yield from search_window(client, model_id, window, stats, progress, first, requests_before)
        return
    focused = Window(max(window.start, start), window.end)
    stats.focused_starts[model_id] = focused.start.isoformat()
    if progress is not None:
        progress(f"    {total:,} results: too many, searching from {focused.start} only")
    if focused.start <= focused.end:
        yield from search_window(client, model_id, focused, stats, progress)


def mine(
    client: CommitSearchClient,
    targets: Sequence[tuple[str, str]],
    window: Window,
    progress: Progress | None = None,
    focus_above: int = FOCUS_ABOVE,
    starts: Mapping[str, date] | None = None,
) -> tuple[list[Candidate], MiningStats]:
    """Search every target ID and return de-duplicated, non-fork candidates."""
    stats = MiningStats(
        start=window.start.isoformat(), end=window.end.isoformat(), focus_above=focus_above
    )
    by_sha: dict[str, Candidate] = {}
    for number, (provider, model_id) in enumerate(targets, start=1):
        stats.model_ids += 1
        if progress is not None:
            progress(f"[{number}/{len(targets)}] {model_id}")
        start = (starts or {}).get(model_id)
        for item in search_model(client, model_id, window, stats, progress, start):
            stats.items_seen += 1
            if item["repository"]["fork"]:
                stats.forks_skipped += 1
                continue
            if not mentions(item["commit"]["message"], model_id):
                stats.not_in_message += 1
                continue
            sha = item["sha"]
            if sha in by_sha:
                stats.duplicates += 1
                existing = by_sha[sha]
                repo = item["repository"]["full_name"]
                if repo not in existing.repos:
                    existing.repos.append(repo)
                    stats.copies_in_other_repos += 1
                if model_id not in existing.matched_ids:
                    existing.matched_ids.append(model_id)
                if provider not in existing.providers:
                    existing.providers.append(provider)
                continue
            by_sha[sha] = Candidate(
                sha=sha,
                repo=item["repository"]["full_name"],
                repos=[item["repository"]["full_name"]],
                url=item["html_url"],
                committed_at=item["commit"]["committer"]["date"],
                message=item["commit"]["message"],
                matched_ids=[model_id],
                providers=[provider],
            )
    candidates = sorted(by_sha.values(), key=lambda c: (c.committed_at, c.sha))
    return candidates, stats


def count_results(
    client: CommitSearchClient,
    targets: Sequence[tuple[str, str]],
    window: Window,
    progress: Progress | None = None,
) -> dict[str, int]:
    """Return how many results GitHub reports for each ID: one search per ID."""
    counts = {}
    for number, (_, model_id) in enumerate(targets, start=1):
        if progress is not None:
            progress(f"[{number}/{len(targets)}] {model_id}")
        counts[model_id] = int(client.search(build_query(model_id, window), 1)["total_count"])
    return counts


def write_jsonl(candidates: Iterable[Candidate], path: Path) -> None:
    """Write one JSON object per line."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for candidate in candidates:
            f.write(json.dumps(asdict(candidate), ensure_ascii=False) + "\n")


def main(argv: Sequence[str] | None = None, client: CommitSearchClient | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--start", type=date.fromisoformat, default=date(2023, 1, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date.today())
    parser.add_argument("--only", action="append", default=[], help="Search only this ID.")
    parser.add_argument("--out", type=Path, default=Path("research/data/candidates.jsonl"))
    parser.add_argument("--cache", type=Path, default=Path("research/data/cache"))
    parser.add_argument(
        "--interval", type=float, default=6.0, help="Seconds between searches (default 6)."
    )
    parser.add_argument(
        "--focus-above",
        type=int,
        default=FOCUS_ABOVE,
        help=f"Search IDs with more results only from their notice (default {FOCUS_ABOVE:,}).",
    )
    parser.add_argument("--counts", action="store_true", help="Only count the results for each ID.")
    args = parser.parse_args(argv)

    if client is None:
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            print("Set GITHUB_TOKEN first:  export GITHUB_TOKEN=$(gh auth token)", file=sys.stderr)
            return 1
        client = CommitSearchClient(args.cache, token, min_interval=args.interval)

    registry = load_registry()
    targets = model_ids_to_search(registry, args.only)
    starts = focus_starts(registry)
    window = Window(args.start, args.end)

    def progress(line: str) -> None:
        print(line, file=sys.stderr)

    try:
        if args.counts:
            counts = count_results(client, targets, window, progress)
        else:
            candidates, stats = mine(client, targets, window, progress, args.focus_above, starts)
    except ServerError:
        print(
            "GitHub's servers kept failing. Everything fetched so far is saved in the cache. "
            "Wait a while, then run the same command to continue.",
            file=sys.stderr,
        )
        return 4
    except NetworkError:
        print(
            "The network kept failing. Everything fetched so far is saved in the cache. "
            "Check your internet connection, then run the same command to continue.",
            file=sys.stderr,
        )
        return 3
    except RateLimitError:
        print(
            "GitHub is still refusing searches. Everything fetched so far is saved in the "
            "cache. Wait an hour or more, then run the same command to continue.",
            file=sys.stderr,
        )
        return 2
    except KeyboardInterrupt:
        print("Stopped. Run the same command to continue from the cache.", file=sys.stderr)
        return 130
    if args.counts:
        return print_counts(counts, args.focus_above, starts, args.out.with_name("counts.json"))
    write_jsonl(candidates, args.out)
    stats_path = args.out.with_suffix(".stats.json")
    stats_path.write_text(json.dumps(asdict(stats), indent=2) + "\n", encoding="utf-8")

    print(f"Model IDs searched:  {stats.model_ids}")
    print(f"Search requests:     {stats.queries} ({client.cache_hits} from cache)")
    print(f"Results seen:        {stats.items_seen}")
    print(f"Forks skipped:       {stats.forks_skipped}")
    print(f"ID not in message:   {stats.not_in_message}")
    print(f"Duplicates merged:   {stats.duplicates}")
    print(f"  same commit, other repo: {stats.copies_in_other_repos}")
    print(f"Truncated windows:   {len(stats.truncated_windows)}")
    print(f"Failed windows:      {len(stats.failed_windows)}")
    print(f"Searched from the notice only: {len(stats.focused_starts)} IDs")
    print(f"Candidates written:  {len(candidates)} -> {args.out}")
    return 0


def print_counts(
    counts: dict[str, int], focus_above: int, starts: Mapping[str, date], path: Path
) -> int:
    """Print the counts, largest first, save them to ``path``, and return 0."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(counts, indent=2) + "\n", encoding="utf-8")
    focused = 0
    for model_id, total in sorted(counts.items(), key=lambda pair: -pair[1]):
        mode = "all"
        if total > focus_above and model_id in starts:
            mode = f"from {starts[model_id]}"
            focused += 1
        print(f"{total:>12,}  {mode:<15}  {model_id}")
    print(f"IDs searched from the notice only: {focused} of {len(counts)} -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
