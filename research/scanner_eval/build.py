"""Build the scanner's evaluation set from real migration commits (ADR 0029).

For a random sample of the migration commits whose changed files we already
fetched for RQ4 (research/data/files.jsonl and its cache), this script:

1. downloads the repository as it was just *before* the migration (the
   commit's parent), keeping only the files the scanner reads;
2. runs the scanner on that snapshot;
3. measures **recall** against ground truth the scanner never saw: every line
   the migration removed that names the old model is a place the project
   depended on it, so the scanner should report it there;
4. draws a blind, stratified sample of the scanner's findings for hand
   labelling, to measure **precision** (scored by research.scanner_eval.score).

Every download is cached, so a rerun costs no requests.

Run from the repo root:
    export GITHUB_TOKEN=$(gh auth token)
    uv run python -m research.scanner_eval.build
"""

import argparse
import csv
import json
import os
import random
import re
import sys
import tarfile
import tempfile
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from modelbump.registry import Registry, load_registry
from modelbump.scanner import Context, scan_path
from modelbump.scanner.files import MAX_BYTES, SKIP_DIRS, is_scannable
from research.enrichment.files import COMMIT_URL, CommitFilesClient, kind
from research.filtering.filter import read_jsonl, write_jsonl
from research.mining.github_search import RateLimitError, _is_rate_limited
from research.validation.score import wilson

SAMPLE = 100
SEED = 2030
SHEET_SEED = 2031
PER_GROUP = 50
MAX_TARBALL = 200_000_000  # bytes; bigger repositories are skipped and counted
TARBALL_URL = "https://api.github.com/repos/{repo}/tarball/{ref}"
LINE_LIMIT = 300  # characters of one line shown in the labelling sheet

# Findings are labelled in five groups, so rare contexts get enough rows.
GROUPS: Mapping[str, frozenset[Context]] = {
    "code_use": frozenset({Context.CALL_ARGUMENT, Context.ASSIGNMENT}),
    "code_string": frozenset({Context.STRING}),
    "documentation": frozenset({Context.COMMENT, Context.DOCSTRING}),
    "config": frozenset({Context.CONFIG}),
    "text": frozenset({Context.TEXT}),
}
SHEET_COLUMNS = (
    "row",
    "repo",
    "path",
    "line",
    "model_id",
    "before",
    "line_text",
    "after",
    "url",
    "dependency",
    "note",
)
_HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@")


def group_of(context: str) -> str:
    """The labelling group of a finding's context."""
    for name, contexts in GROUPS.items():
        if context in contexts:
            return name
    raise ValueError(f"unknown context {context!r}")


def mentions(text: str, model_id: str) -> bool:
    """True if ``text`` names ``model_id`` exactly, independently of the scanner.

    ``gpt-4`` is not found inside ``gpt-4-turbo`` or ``gpt-4.1``, but is found
    after a prefix such as ``openai/`` or ``anthropic.``.
    """
    pattern = rf"(?<![A-Za-z0-9_-]){re.escape(model_id)}(?![A-Za-z0-9_-]|\.[0-9])"
    return re.search(pattern, text) is not None


@dataclass(frozen=True, slots=True)
class Site:
    """A line a migration removed that names the old model: a known dependency."""

    path: str
    line: int
    """Line number in the parent commit."""
    text: str


def removed_sites(patch: str, path: str, model_id: str) -> list[Site]:
    """Removed lines of a unified diff that name ``model_id``, with their old line numbers."""
    sites: list[Site] = []
    old = 0
    for raw in patch.splitlines():
        hunk = _HUNK.match(raw)
        if hunk:
            old = int(hunk.group(1))
            continue
        if raw.startswith("-"):
            if mentions(raw[1:], model_id):
                sites.append(Site(path, old, raw[1:]))
            old += 1
        elif raw.startswith(" ") or raw == "":
            old += 1
        # "+" lines and "\ No newline at end of file" do not move the old side.
    return sites


def commit_sites(files: Sequence[Mapping[str, Any]], model_id: str) -> list[Site]:
    """Known dependency sites of one migration commit, outside documentation files."""
    sites: list[Site] = []
    for f in files:
        patch = f.get("patch")
        if not patch or f.get("status") == "added":
            continue
        path = str(f.get("previous_filename") or f["filename"])
        if kind(path) == "docs":
            continue
        sites.extend(removed_sites(str(patch), path, model_id))
    return sites


def miss_reason(site: Site, big_files: Iterable[str]) -> str:
    """Why the scanner did not report a known site."""
    parts = PurePosixPath(site.path).parts
    if any(part in SKIP_DIRS for part in parts[:-1]):
        return "skipped folder"
    if not is_scannable(Path(site.path)):
        return "file type not scanned"
    if site.path in set(big_files):
        return "too big"
    return "not found by the finder"


def safe_member_path(name: str) -> str | None:
    """The member's path without the tarball's top folder, or None if unsafe or empty."""
    parts = PurePosixPath(name).parts[1:]
    if not parts or any(part in ("..", "") for part in parts) or name.startswith("/"):
        return None
    return "/".join(parts)


def extract_scannable(tar_path: Path, dest: Path) -> tuple[int, list[str]]:
    """Extract only the files the scanner reads. Returns (files written, too-big paths)."""
    written = 0
    big: list[str] = []
    with tarfile.open(tar_path, "r:gz") as archive:
        for member in archive:
            if not member.isfile():
                continue  # directories, and symbolic links, which the scanner skips too
            rel = safe_member_path(member.name)
            if rel is None:
                continue
            parts = PurePosixPath(rel).parts
            if any(part in SKIP_DIRS for part in parts[:-1]):
                continue
            if not is_scannable(Path(rel)):
                continue
            if member.size > MAX_BYTES:
                big.append(rel)
                continue
            source = archive.extractfile(member)
            if source is None:
                continue
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read())
            written += 1
    return written, big


class SnapshotFetcher:
    """Download the parent snapshot of a commit, with a disk cache."""

    def __init__(
        self,
        client: CommitFilesClient,
        out_dir: Path,
        *,
        max_bytes: int = MAX_TARBALL,
    ) -> None:
        self.client = client
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_bytes
        self.downloads = 0

    def snapshot(self, repo: str, sha: str) -> dict[str, Any]:
        """Metadata of the snapshot before ``sha``; its files are in ``out_dir/<sha>/``."""
        meta_path = self.out_dir / f"{sha}.json"
        if meta_path.exists():
            meta: dict[str, Any] = json.loads(meta_path.read_text(encoding="utf-8"))
            return meta
        meta = {"repo": repo, "sha": sha, "parent": None}
        status, commit = self.client._get(COMMIT_URL.format(repo=repo, sha=sha), 1)
        parents = commit.get("parents") or []
        if status != 200:
            meta["status"] = f"commit not found ({status})"
        elif not parents:
            meta["status"] = "no parent commit"
        else:
            meta["parent"] = parents[0]["sha"]
            meta.update(self._download(repo, meta["parent"], self.out_dir / sha))
        tmp = meta_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(meta), encoding="utf-8")
        tmp.replace(meta_path)
        return meta

    def _download(self, repo: str, ref: str, dest: Path) -> dict[str, Any]:
        url = TARBALL_URL.format(repo=repo, ref=ref)
        with tempfile.TemporaryDirectory() as tmp_dir:
            tar_path = Path(tmp_dir) / "snapshot.tar.gz"
            with self.client._http.stream("GET", url) as response:
                if _is_rate_limited(response):
                    response.read()
                    raise RateLimitError("GitHub refused the download (rate limit)")
                if response.status_code != 200:
                    return {"status": f"download failed ({response.status_code})"}
                size = 0
                with tar_path.open("wb") as out:
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > self.max_bytes:
                            return {"status": "repository too large"}
                        out.write(chunk)
            self.downloads += 1
            try:
                written, big = extract_scannable(tar_path, dest)
            except (tarfile.TarError, OSError) as error:
                return {"status": f"bad archive ({type(error).__name__})"}
        return {"status": "ok", "files": written, "big_files": big, "bytes": size}


def eligible_commits(rows: Iterable[Mapping[str, Any]], cache_dir: Path) -> list[dict[str, Any]]:
    """RQ4 commits that GitHub served and that removed at least one line naming the model."""
    out = []
    for row in rows:
        if not row.get("found"):
            continue
        cached = cache_dir / f"{row['sha']}.json"
        if not cached.exists():
            continue
        files = json.loads(cached.read_text(encoding="utf-8"))["files"]
        sites = commit_sites(files, str(row["model_id"]))
        if sites:
            out.append({**{k: row[k] for k in ("sha", "repo", "model_id")}, "sites": sites})
    return sorted(out, key=lambda r: str(r["sha"]))


def finding_rows(
    commit: Mapping[str, Any], snapshot_dir: Path, registry: Registry
) -> list[dict[str, Any]]:
    """Every finding of the scanner in one snapshot, as JSON rows."""
    result = scan_path(snapshot_dir, registry)
    return [
        {
            "sha": commit["sha"],
            "repo": commit["repo"],
            "path": f.path,
            "line": f.line,
            "column": f.column,
            "model_id": f.model_id,
            "registry_id": f.registry_id,
            "context": f.context.value,
            "detail": f.detail,
        }
        for f in result.findings
    ]


def site_rows(
    commit: Mapping[str, Any], findings: Sequence[Mapping[str, Any]], big_files: Sequence[str]
) -> list[dict[str, Any]]:
    """Each known site of one commit, with whether the scanner reported it there."""
    reported: dict[tuple[str, int], set[str]] = {}
    for f in findings:
        ids = reported.setdefault((str(f["path"]), int(f["line"])), set())
        ids.add(str(f["model_id"]))
        if f["registry_id"]:
            ids.add(str(f["registry_id"]))
    rows = []
    model_id = str(commit["model_id"])
    for site in commit["sites"]:
        found = model_id in reported.get((site.path, site.line), set())
        rows.append(
            {
                "sha": commit["sha"],
                "repo": commit["repo"],
                "model_id": model_id,
                "path": site.path,
                "line": site.line,
                "found": found,
                "reason": None if found else miss_reason(site, big_files),
            }
        )
    return rows


def draw_sheet(
    findings: Sequence[Mapping[str, Any]], per_group: int, seed: int
) -> list[dict[str, Any]]:
    """A stratified random sample of findings, in a shuffled (blind) order."""
    rng = random.Random(seed)
    chosen: list[dict[str, Any]] = []
    for name in GROUPS:
        members = sorted(
            (dict(f) for f in findings if group_of(str(f["context"])) == name),
            key=lambda f: (f["sha"], f["path"], f["line"], f["column"]),
        )
        picked = members if len(members) <= per_group else rng.sample(members, per_group)
        chosen.extend({**f, "group": name} for f in picked)
    rng.shuffle(chosen)
    return chosen


def sheet_line(lines: Sequence[str], index: int) -> str:
    """One line for the sheet, cut to a readable length."""
    if index < 0 or index >= len(lines):
        return ""
    text = lines[index].rstrip("\r\n")
    return text if len(text) <= LINE_LIMIT else text[: LINE_LIMIT - 3] + "..."


def write_sheet(
    chosen: Sequence[Mapping[str, Any]],
    snapshots: Path,
    parents: Mapping[str, str],
    sheet_path: Path,
    key_path: Path,
) -> None:
    """The blind labelling sheet (no context shown) and its key."""
    sheet_path.parent.mkdir(parents=True, exist_ok=True)
    with sheet_path.open("w", newline="", encoding="utf-8") as sheet_file:
        sheet = csv.DictWriter(sheet_file, fieldnames=SHEET_COLUMNS)
        sheet.writeheader()
        for row, f in enumerate(chosen, start=1):
            text = (snapshots / str(f["sha"]) / str(f["path"])).read_text(
                encoding="utf-8", errors="replace"
            )
            lines = text.splitlines()
            at = int(f["line"]) - 1
            parent = parents[str(f["sha"])]
            sheet.writerow(
                {
                    "row": row,
                    "repo": f["repo"],
                    "path": f["path"],
                    "line": f["line"],
                    "model_id": f["model_id"],
                    "before": "\n".join(sheet_line(lines, i) for i in range(at - 2, at)),
                    "line_text": sheet_line(lines, at),
                    "after": "\n".join(sheet_line(lines, i) for i in range(at + 1, at + 3)),
                    "url": f"https://github.com/{f['repo']}/blob/{parent}/{f['path']}#L{f['line']}",
                    "dependency": "",
                    "note": "",
                }
            )
    with key_path.open("w", newline="", encoding="utf-8") as key_file:
        key = csv.writer(key_file)
        key.writerow(("row", "group", "context", "detail", "sha"))
        for row, f in enumerate(chosen, start=1):
            key.writerow((row, f["group"], f["context"], f["detail"] or "", f["sha"]))


def rate(yes: int, n: int) -> dict[str, Any]:
    """A share with its 95% Wilson interval."""
    low, high = wilson(yes, n)
    return {"yes": yes, "n": n, "share": yes / n if n else None, "low": low, "high": high}


def build(
    rows: Iterable[Mapping[str, Any]],
    cache_dir: Path,
    fetcher: SnapshotFetcher,
    registry: Registry,
    out_dir: Path,
    *,
    sample: int = SAMPLE,
    seed: int = SEED,
    per_group: int = PER_GROUP,
    sheet_seed: int = SHEET_SEED,
    progress: Callable[[str], None] = lambda line: None,
) -> dict[str, Any]:
    """Build every output file and return the statistics."""
    population = eligible_commits(rows, cache_dir)
    order = random.Random(seed).sample(population, len(population))
    used: list[dict[str, Any]] = []
    skipped: Counter[str] = Counter()
    findings: list[dict[str, Any]] = []
    sites: list[dict[str, Any]] = []
    parents: dict[str, str] = {}
    for commit in order:
        if len(used) >= sample:
            break
        meta = fetcher.snapshot(str(commit["repo"]), str(commit["sha"]))
        if meta["status"] != "ok":
            skipped[str(meta["status"])] += 1
            continue
        parents[str(commit["sha"])] = str(meta["parent"])
        found = finding_rows(commit, fetcher.out_dir / str(commit["sha"]), registry)
        findings.extend(found)
        sites.extend(site_rows(commit, found, meta.get("big_files", [])))
        used.append(
            {
                "sha": commit["sha"],
                "repo": commit["repo"],
                "model_id": commit["model_id"],
                "parent": meta["parent"],
                "snapshot_files": meta["files"],
                "findings": len(found),
                "sites": len(commit["sites"]),
            }
        )
        progress(f"{len(used)}/{sample} snapshots ({fetcher.downloads} downloaded)")

    write_jsonl(used, out_dir / "commits.jsonl")
    write_jsonl(findings, out_dir / "findings.jsonl")
    write_jsonl(sites, out_dir / "sites.jsonl")
    chosen = draw_sheet(findings, per_group, sheet_seed)
    write_sheet(chosen, fetcher.out_dir, parents, out_dir / "sheet.csv", out_dir / "sheet_key.csv")

    hits = sum(1 for s in sites if s["found"])
    stats: dict[str, Any] = {
        "seed": seed,
        "sheet_seed": sheet_seed,
        "eligible_commits": len(population),
        "snapshots": len(used),
        "skipped": dict(skipped),
        "snapshot_files": sum(int(c["snapshot_files"]) for c in used),
        "findings": len(findings),
        "findings_by_context": dict(Counter(str(f["context"]) for f in findings)),
        "group_population": {
            name: sum(1 for f in findings if group_of(str(f["context"])) == name) for name in GROUPS
        },
        "sheet_rows": len(chosen),
        "sites": len(sites),
        "recall": rate(hits, len(sites)),
        "misses_by_reason": dict(Counter(str(s["reason"]) for s in sites if not s["found"])),
    }
    (out_dir / "build.stats.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    return stats


def summary(stats: Mapping[str, Any]) -> str:
    """What to print at the end of a run."""
    recall = stats["recall"]
    lines = [
        f"Snapshots: {stats['snapshots']} of {stats['eligible_commits']} eligible commits "
        f"(skipped: {stats['skipped'] or 'none'})",
        f"Files scanned: {stats['snapshot_files']:,}; findings: {stats['findings']:,}",
        f"Findings by context: {stats['findings_by_context']}",
    ]
    if recall["n"]:
        lines.append(
            f"Recall on {recall['n']} known sites: {100 * recall['share']:.1f}% "
            f"(95% CI {100 * recall['low']:.1f} to {100 * recall['high']:.1f})"
        )
    lines.append(f"Misses by reason: {stats['misses_by_reason'] or 'none'}")
    lines.append(f"Labelling sheet: {stats['sheet_rows']} rows")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None, client: CommitFilesClient | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--files", type=Path, default=Path("research/data/files.jsonl"))
    parser.add_argument("--cache", type=Path, default=Path("research/data/cache/commit_files"))
    parser.add_argument("--out", type=Path, default=Path("research/data/scanner_eval"))
    parser.add_argument("--sample", type=int, default=SAMPLE, help=f"Snapshots (default {SAMPLE}).")
    parser.add_argument("--seed", type=int, default=SEED, help=f"Random seed (default {SEED}).")
    parser.add_argument(
        "--per-group", type=int, default=PER_GROUP, help=f"Sheet rows per group ({PER_GROUP})."
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
    fetcher = SnapshotFetcher(client, args.out / "snapshots")
    try:
        stats = build(
            read_jsonl(args.files),
            args.cache,
            fetcher,
            load_registry(),
            args.out,
            sample=args.sample,
            seed=args.seed,
            per_group=args.per_group,
            progress=lambda line: print(line, file=sys.stderr),
        )
    except RateLimitError as error:
        print(f"{error}. Everything so far is cached; run the same command again later.")
        return 3
    print(summary(stats))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
