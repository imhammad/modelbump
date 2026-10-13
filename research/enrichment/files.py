"""What else changes in a migration commit: tests, evaluations, prompts, config?

Draws a random sample of migration commits from research/data/targets.jsonl,
fetches each commit's changed files from GitHub's REST API, and sorts every
file into a kind (test, eval, prompt, config, docs, ci, code, other). It then
reports how often a migration touches or adds tests and evaluations, and how
often it is a pure ID swap: every changed line names a model and nothing else
changes. This is RQ4 of the paper (ADR 0018).

Every API response is cached on disk, so a rerun costs no requests and every
number can be traced back to the response it came from.

Run from the repo root:
    export GITHUB_TOKEN=$(gh auth token)
    uv run python -m research.enrichment.files
"""

import argparse
import json
import os
import random
import re
import sys
import time
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from research.enrichment.targets import model_tokens
from research.filtering.filter import read_jsonl, write_jsonl
from research.mining.github_search import (
    USER_AGENT,
    NetworkError,
    RateLimitError,
    ServerError,
    _is_rate_limited,
    _message,
    _wait_seconds,
)
from research.validation.score import wilson

COMMIT_URL = "https://api.github.com/repos/{repo}/commits/{sha}"
PER_PAGE = 100
MAX_PAGES = 3  # up to 300 files per commit, far more than a migration changes
SAMPLE = 400
SEED = 2028

KINDS = ("eval", "test", "prompt", "ci", "docs", "config", "code", "other")
_EVAL = re.compile(
    r"(^|/)(evals?|evaluations?|benchmarks?|golden|goldens|promptfoo)(/|$)"
    r"|(^|[/_.-])(evals?|evaluation|benchmark|golden|promptfoo(config)?)([_.-]|$)"
    r"|(deepeval|ragas|langsmith_eval|lm_eval)",
    re.IGNORECASE,
)
_TEST = re.compile(
    r"(^|/)(tests?|__tests__|specs?|testing|e2e|cypress|playwright)(/)"
    r"|(^|/)test_[^/]+$|_test\.(py|go|rs|exs?)$|\.(test|spec)\.[cm]?[jt]sx?$"
    r"|(Test|Tests|Spec)\.(java|kt|cs|swift|scala)$|_spec\.rb$|(^|/)conftest\.py$",
)
_PROMPT = re.compile(
    r"(^|/)prompts?(/|$)|\.prompt(\.\w+)?$|(^|/)[^/]*prompt[^/]*\.(txt|md|j2|jinja2?|ya?ml|json)$",
    re.IGNORECASE,
)
_CI = re.compile(
    r"(^|/)\.github/workflows/|(^|/)\.gitlab-ci\.ya?ml$|(^|/)\.circleci/|(^|/)azure-pipelines"
    r"|(^|/)Jenkinsfile$|(^|/)\.travis\.ya?ml$",
    re.IGNORECASE,
)
_DOCS = re.compile(
    r"\.(md|mdx|rst|adoc)$|(^|/)docs?/|(^|/)(README|CHANGELOG|CHANGES|HISTORY)[^/]*$", re.IGNORECASE
)
_CONFIG = re.compile(
    r"(^|/)\.env[^/]*$|\.(ya?ml|json|jsonc|toml|ini|cfg|conf|properties|lock|xml|plist)$"
    r"|(^|/)(Dockerfile|docker-compose[^/]*|Makefile|Procfile|requirements[^/]*\.txt)$"
    r"|(^|/)(config|settings)[^/]*\.[^/]+$",
    re.IGNORECASE,
)
_CODE = re.compile(
    r"\.(py|ipynb|[cm]?[jt]sx?|go|rs|java|kt|kts|rb|php|cs|swift|scala|dart|ex|exs|lua|r|jl"
    r"|c|cc|cpp|h|hpp|m|sh|bash|zsh|ps1|sql|vue|svelte|astro|html|css|scss)$",
    re.IGNORECASE,
)


def kind(path: str) -> str:
    """The kind of one changed file, judged from its path (first match wins)."""
    for name, pattern in (
        ("eval", _EVAL),
        ("test", _TEST),
        ("prompt", _PROMPT),
        ("ci", _CI),
        ("docs", _DOCS),
        ("config", _CONFIG),
        ("code", _CODE),
    ):
        if pattern.search(path):
            return name
    return "other"


def changed_lines(patch: str) -> list[str]:
    """The added and removed lines of a unified diff, without the +/- sign."""
    return [
        line[1:]
        for line in patch.splitlines()
        if line[:1] in "+-" and not line.startswith(("+++", "---"))
    ]


def only_ids(lines: Iterable[str]) -> bool:
    """True if every non-blank line names a model ID: the change is an ID swap."""
    chosen = [line for line in lines if line.strip()]
    return bool(chosen) and all(model_tokens(line) for line in chosen)


def describe(commit: dict[str, Any], files: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """One output row: the commit, its files with their kinds, and the flags for RQ4."""
    listed = []
    for f in files:
        patch = f.get("patch")
        listed.append(
            {
                "path": f["filename"],
                "status": f["status"],
                "additions": f.get("additions", 0),
                "deletions": f.get("deletions", 0),
                "kind": kind(f["filename"]),
                "has_patch": patch is not None,
                "mentions_model": bool(patch) and bool(model_tokens(str(patch))),
            }
        )
    kinds = Counter(f["kind"] for f in listed)
    tests = [f for f in listed if f["kind"] == "test"]
    evals = [f for f in listed if f["kind"] == "eval"]
    not_docs = [f for f in files if kind(f["filename"]) != "docs"]
    patches = [f.get("patch") for f in not_docs]
    if not not_docs:
        swap: bool | None = False
    elif any(p is None for p in patches):
        swap = None  # GitHub left out a diff (binary or very large file)
    else:
        swap = only_ids(line for p in patches for line in changed_lines(str(p)))
    return {
        **{k: commit[k] for k in ("sha", "repo", "url", "model_id", "target", "ai_assisted")},
        "found": True,
        "files": listed,
        "file_count": len(listed),
        "truncated": len(files) >= PER_PAGE * MAX_PAGES,
        "kinds": dict(kinds),
        "touches_test": bool(tests),
        "adds_test": any(f["status"] == "added" for f in tests),
        "test_mentions_model": any(f["mentions_model"] for f in tests),
        "touches_eval": bool(evals),
        "adds_eval": any(f["status"] == "added" for f in evals),
        "touches_prompt": kinds["prompt"] > 0,
        "touches_code": kinds["code"] > 0,
        "id_swap_only": swap,
    }


def missing(commit: dict[str, Any], status: int) -> dict[str, Any]:
    """The row for a commit GitHub no longer serves (deleted repository, rewritten history)."""
    return {
        **{k: commit[k] for k in ("sha", "repo", "url", "model_id", "target", "ai_assisted")},
        "found": False,
        "http_status": status,
    }


class CommitFilesClient:
    """Fetch the changed files of one commit, with a disk cache and rate-limit handling."""

    def __init__(
        self,
        cache_dir: Path,
        token: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
        min_interval: float = 1.0,
        max_retries: int = 6,
    ) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": USER_AGENT,
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        # A renamed or transferred repository answers with a 301 to its new
        # address; follow it (same host, so the token is kept).
        self._http = httpx.Client(
            headers=headers, transport=transport, timeout=30.0, follow_redirects=True
        )
        self._sleep = sleep
        self._clock = clock
        self._min_interval = min_interval
        self._max_retries = max_retries
        self._last_request = float("-inf")
        self.requests_made = 0
        self.cache_hits = 0

    def files(self, repo: str, sha: str) -> tuple[int, list[dict[str, Any]]]:
        """(HTTP status, changed files) for one commit; status 200 when found."""
        path = self.cache_dir / f"{sha}.json"
        if path.exists():
            self.cache_hits += 1
            record = json.loads(path.read_text(encoding="utf-8"))
            return int(record["status"]), list(record["files"])
        status = 200
        files: list[dict[str, Any]] = []
        for page in range(1, MAX_PAGES + 1):
            status, data = self._get(COMMIT_URL.format(repo=repo, sha=sha), page)
            if status != 200:
                files = []
                break
            batch = data.get("files", [])
            files.extend(batch)
            if len(batch) < PER_PAGE:
                break
        record = {
            "repo": repo,
            "sha": sha,
            "status": status,
            "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "files": files,
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(record), encoding="utf-8")
        tmp.replace(path)
        return status, files

    def _get(self, url: str, page: int) -> tuple[int, dict[str, Any]]:
        params = {"per_page": PER_PAGE, "page": page}
        server_failures = 0
        last_failure = "rate limit"
        for attempt in range(self._max_retries + 1):
            self._throttle()
            try:
                response = self._http.get(url, params=params)
            except httpx.TransportError as error:
                last_failure = "network"
                wait = 60.0 * 2.0**attempt
                print(
                    f"Network problem ({type(error).__name__}); waiting {wait / 60:.0f} min ...",
                    file=sys.stderr,
                )
                self._sleep(wait)
                continue
            self.requests_made += 1
            if _is_rate_limited(response):
                last_failure = "rate limit"
                wait = _wait_seconds(response, attempt, self._clock())
                reason = _message(response).split(". ")[0]
                print(
                    f"GitHub refused the request ({response.status_code}: {reason}); "
                    f"waiting {wait / 60:.0f} min ...",
                    file=sys.stderr,
                )
                self._sleep(wait)
                continue
            if response.status_code >= 500:
                server_failures += 1
                last_failure = "server"
                if server_failures > 3:
                    raise ServerError(f"GitHub kept failing ({response.status_code}) for {url}")
                self._sleep(30.0 * 2.0 ** (server_failures - 1))
                continue
            if response.status_code in (404, 409, 410, 422, 451):
                # Gone: a deleted or private repository, a rewritten history,
                # or a repository blocked for legal reasons.
                return response.status_code, {}
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            return 200, data
        if last_failure == "server":
            raise ServerError(f"GitHub kept failing for {url}")
        if last_failure == "network":
            raise NetworkError(f"The network kept failing for {url}")
        raise RateLimitError(f"GitHub kept refusing {url}")

    def _throttle(self) -> None:
        wait = self._last_request + self._min_interval - self._clock()
        if wait > 0:
            self._sleep(wait)
        self._last_request = self._clock()


def draw(rows: Iterable[dict[str, Any]], size: int, seed: int) -> list[dict[str, Any]]:
    """A simple random sample of migration commits, the same for the same data and seed."""
    population = sorted(rows, key=lambda r: r["sha"])
    if size >= len(population):
        return population
    return random.Random(seed).sample(population, size)


@dataclass
class Rate:
    """How many of ``n`` commits have a property, with a 95% Wilson interval."""

    yes: int = 0
    n: int = 0
    low: float = 0.0
    high: float = 0.0

    @classmethod
    def of(cls, flags: Sequence[bool]) -> "Rate":
        yes = sum(flags)
        low, high = wilson(yes, len(flags))
        return cls(yes=yes, n=len(flags), low=low, high=high)


@dataclass
class FilesStats:
    """Counts for the paper, written next to files.jsonl."""

    seed: int = SEED
    population: int = 0
    sampled: int = 0
    found: int = 0
    missing: dict[str, int] = field(default_factory=dict)
    truncated: int = 0
    median_files: float = 0.0
    kinds: dict[str, int] = field(default_factory=dict)
    rates: dict[str, Rate] = field(default_factory=dict)
    by_ai: dict[str, dict[str, Rate]] = field(default_factory=dict)


FLAGS = {
    "touches a test file": "touches_test",
    "adds a test file": "adds_test",
    "changes a test that names a model": "test_mentions_model",
    "touches an evaluation file": "touches_eval",
    "adds an evaluation file": "adds_eval",
    "touches a test or evaluation file": "touches_test_or_eval",
    "touches a prompt file": "touches_prompt",
    "pure ID swap (diffs known)": "id_swap_only",
}


def flag(row: dict[str, Any], key: str) -> bool | None:
    if key == "touches_test_or_eval":
        return bool(row["touches_test"] or row["touches_eval"])
    value = row[key]
    return None if value is None else bool(value)


def summarise(rows: Sequence[dict[str, Any]], population: int, seed: int) -> FilesStats:
    """The RQ4 numbers for the fetched sample."""
    found = [r for r in rows if r["found"]]
    stats = FilesStats(seed=seed, population=population, sampled=len(rows), found=len(found))
    stats.missing = dict(Counter(str(r["http_status"]) for r in rows if not r["found"]))
    stats.truncated = sum(r["truncated"] for r in found)
    counts = sorted(r["file_count"] for r in found)
    if counts:
        middle = len(counts) // 2
        stats.median_files = (
            counts[middle] if len(counts) % 2 else (counts[middle - 1] + counts[middle]) / 2
        )
    touched: Counter[str] = Counter()
    for r in found:
        touched.update(set(r["kinds"]))
    stats.kinds = {k: touched[k] for k in KINDS}
    for name, key in FLAGS.items():
        values = [flag(r, key) for r in found]
        stats.rates[name] = Rate.of([v for v in values if v is not None])
    for group, chosen in (
        ("AI-assisted", [r for r in found if r["ai_assisted"]]),
        ("not AI-assisted", [r for r in found if not r["ai_assisted"]]),
    ):
        stats.by_ai[group] = {
            name: Rate.of([v for v in (flag(r, FLAGS[name]) for r in chosen) if v is not None])
            for name in ("touches a test file", "touches a test or evaluation file")
        }
    return stats


def rate_text(rate: Rate) -> str:
    if not rate.n:
        return f"{'-':>18}"
    share = f"{100 * rate.yes / rate.n:.1f}%"
    return (
        f"{rate.yes:>5} of {rate.n:<4}{share:>7}  ({100 * rate.low:.1f} to {100 * rate.high:.1f})"
    )


def report(stats: FilesStats) -> None:
    """Print the tables for RQ4."""
    print(f"Migration commits: {stats.population:,}; sampled {stats.sampled} (seed {stats.seed})")
    gone = ", ".join(f"{n} with HTTP {s}" for s, n in sorted(stats.missing.items())) or "none"
    print(f"  fetched: {stats.found}; no longer on GitHub: {gone}")
    print(
        f"  median changed files: {stats.median_files:g}; lists cut at 300 files: {stats.truncated}"
    )
    print("\nCommits that touch each kind of file:")
    for k, count in stats.kinds.items():
        share = 100 * count / stats.found if stats.found else 0.0
        print(f"  {k:<10}{count:>5}  {share:5.1f}%")
    print("\nRQ4 (95% Wilson intervals):")
    for name, rate in stats.rates.items():
        print(f"  {name:<36}{rate_text(rate)}")
    print("\nBy AI assistance:")
    for group, rates in stats.by_ai.items():
        for name, rate in rates.items():
            print(f"  {group + ', ' + name:<52}{rate_text(rate)}")


def run(
    targets: Iterable[dict[str, Any]],
    client: CommitFilesClient,
    size: int = SAMPLE,
    seed: int = SEED,
    progress: Callable[[str], None] = lambda _: None,
) -> tuple[list[dict[str, Any]], FilesStats]:
    """Draw the sample, fetch every commit's files, and summarise."""
    population = list(targets)
    sample = draw(population, size, seed)
    rows = []
    for i, commit in enumerate(sample, start=1):
        status, files = client.files(commit["repo"], commit["sha"])
        rows.append(describe(commit, files) if status == 200 else missing(commit, status))
        if i % 25 == 0 or i == len(sample):
            progress(f"{i}/{len(sample)} commits ({client.requests_made} requests)")
    return rows, summarise(rows, len(population), seed)


def main(argv: Sequence[str] | None = None, client: CommitFilesClient | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--targets", type=Path, default=Path("research/data/targets.jsonl"))
    parser.add_argument("--out", type=Path, default=Path("research/data/files.jsonl"))
    parser.add_argument("--cache", type=Path, default=Path("research/data/cache/commit_files"))
    parser.add_argument("--sample", type=int, default=SAMPLE, help=f"Commits (default {SAMPLE}).")
    parser.add_argument("--seed", type=int, default=SEED, help=f"Random seed (default {SEED}).")
    parser.add_argument(
        "--interval", type=float, default=1.0, help="Seconds between requests (default 1)."
    )
    args = parser.parse_args(argv)
    if not args.targets.exists():
        print(f"{args.targets} not found. Run research.enrichment.targets first.", file=sys.stderr)
        return 1
    if client is None:
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            print("Set GITHUB_TOKEN first:  export GITHUB_TOKEN=$(gh auth token)", file=sys.stderr)
            return 1
        client = CommitFilesClient(args.cache, token, min_interval=args.interval)

    def progress(line: str) -> None:
        print(line, file=sys.stderr)

    try:
        rows, stats = run(read_jsonl(args.targets), client, args.sample, args.seed, progress)
    except (RateLimitError, NetworkError, ServerError) as error:
        print(f"{error}. Everything fetched so far is cached; run the same command again.")
        return 3
    write_jsonl(rows, args.out)
    stats_path = args.out.with_suffix(".stats.json")
    stats_path.write_text(json.dumps(asdict(stats), indent=2) + "\n", encoding="utf-8")
    report(stats)
    print(f"\nWritten: {args.out} and {stats_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
