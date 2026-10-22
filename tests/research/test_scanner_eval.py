"""Tests for building the scanner's evaluation set. No network is used."""

import csv
import io
import json
import tarfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx
import pytest

from modelbump.registry import load_registry
from research.enrichment.files import CommitFilesClient
from research.mining.github_search import RateLimitError
from research.scanner_eval.build import (
    SHEET_COLUMNS,
    Site,
    SnapshotFetcher,
    build,
    commit_sites,
    draw_sheet,
    eligible_commits,
    extract_scannable,
    group_of,
    main,
    mentions,
    miss_reason,
    removed_sites,
    safe_member_path,
    sheet_line,
    summary,
)

PATCH = """@@ -10,4 +10,4 @@ import openai
 client = openai.OpenAI()
-MODEL = "gpt-3.5-turbo-0613"
+MODEL = "gpt-4o-mini"
 # keep
-# was gpt-3.5-turbo-0613 here
@@ -40,2 +40,3 @@ def f():
+    x = 1
-    return create(model="gpt-3.5-turbo-0613-extra")
\\ No newline at end of file
-    gpt-3.5-turbo-0613"""


def tarball(files: Mapping[str, bytes], top: str = "acme-app-abc123") -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(f"{top}/{name}")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        link = tarfile.TarInfo(f"{top}/link.py")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        archive.addfile(link)
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('MODEL = "gpt-4"', True),
        ("openai/gpt-4", True),
        ("anthropic.gpt-4", True),
        ("gpt-4-turbo", False),
        ("gpt-4.1", False),
        ("my-gpt-4", False),
        ("gpt-4.", True),
    ],
)
def test_mentions(text: str, expected: bool) -> None:
    assert mentions(text, "gpt-4") is expected


def test_removed_sites_use_old_line_numbers() -> None:
    sites = removed_sites(PATCH, "app.py", "gpt-3.5-turbo-0613")
    assert sites == [
        Site("app.py", 11, 'MODEL = "gpt-3.5-turbo-0613"'),
        Site("app.py", 13, "# was gpt-3.5-turbo-0613 here"),
        Site("app.py", 41, "    gpt-3.5-turbo-0613"),
    ]


def test_commit_sites_skip_docs_and_added_files_and_use_old_names() -> None:
    files = [
        {"filename": "README.md", "status": "modified", "patch": PATCH},
        {"filename": "new.py", "status": "added", "patch": PATCH},
        {"filename": "bin.dat", "status": "modified"},
        {
            "filename": "src/new_name.py",
            "previous_filename": "src/old.py",
            "status": "renamed",
            "patch": PATCH,
        },
    ]
    sites = commit_sites(files, "gpt-3.5-turbo-0613")
    assert {s.path for s in sites} == {"src/old.py"}
    assert len(sites) == 3


@pytest.mark.parametrize(
    ("path", "reason"),
    [
        ("node_modules/x/index.js", "skipped folder"),
        ("notes.txt", "file type not scanned"),
        ("big.json", "too big"),
        ("app.py", "not found by the finder"),
    ],
)
def test_miss_reason(path: str, reason: str) -> None:
    assert miss_reason(Site(path, 1, "x"), ["big.json"]) == reason


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("top/app.py", "app.py"),
        ("top/a/b.py", "a/b.py"),
        ("top", None),
        ("top/../evil.py", None),
        ("/top/abs.py", None),
    ],
)
def test_safe_member_path(name: str, expected: str | None) -> None:
    assert safe_member_path(name) == expected


def test_extract_keeps_only_scannable_files(tmp_path: Path) -> None:
    archive = tmp_path / "s.tar.gz"
    archive.write_bytes(
        tarball(
            {
                "app.py": b'MODEL = "gpt-4o"\n',
                "README.md": b"gpt-4o",
                "node_modules/x/i.js": b"gpt-4o",
                "data/big.json": b"x" * 1_000_001,
            }
        )
    )
    written, big = extract_scannable(archive, tmp_path / "out")
    assert (written, big) == (1, ["data/big.json"])
    assert [p.name for p in (tmp_path / "out").rglob("*") if p.is_file()] == ["app.py"]


def test_group_of() -> None:
    assert group_of("call_argument") == "code_use"
    assert group_of("comment") == "documentation"
    with pytest.raises(ValueError):
        group_of("nope")


def test_sheet_line_cuts_long_lines() -> None:
    assert sheet_line(["a" * 400], 0) == "a" * 297 + "..."
    assert sheet_line(["a"], 5) == ""


def test_draw_sheet_is_stratified_and_repeatable() -> None:
    findings = [
        {"sha": "s", "path": "a.py", "line": i, "column": 1, "context": c}
        for i, c in enumerate(["call_argument"] * 10 + ["comment"] * 3 + ["config"] * 5)
    ]
    first = draw_sheet(findings, per_group=4, seed=1)
    assert group_counts(first) == {"code_use": 4, "documentation": 3, "config": 4}
    assert first == draw_sheet(findings, per_group=4, seed=1)


def group_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        out[row["group"]] = out.get(row["group"], 0) + 1
    return out


class FakeGitHub:
    """Serves commit JSON and tarballs for a few commits."""

    def __init__(self, repos: Mapping[str, Mapping[str, bytes]]) -> None:
        self.repos = repos  # sha -> files of its parent snapshot
        self.status: dict[str, int] = {}
        self.rate_limited = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/commits/" in path:
            sha = path.rsplit("/", 1)[1]
            if sha not in self.repos:
                return httpx.Response(404, json={"message": "Not Found"})
            return httpx.Response(200, json={"sha": sha, "parents": [{"sha": f"p{sha}"}]})
        if "/tarball/" in path:
            if self.rate_limited:
                return httpx.Response(403, headers={"x-ratelimit-remaining": "0"}, text="rate")
            parent = path.rsplit("/", 1)[1]
            sha = parent[1:]
            if self.status.get(sha):
                return httpx.Response(self.status[sha])
            return httpx.Response(200, content=tarball(dict(self.repos[sha])))
        return httpx.Response(500)


def make_fetcher(tmp_path: Path, fake: FakeGitHub, max_bytes: int = 10_000_000) -> SnapshotFetcher:
    client = CommitFilesClient(
        tmp_path / "api", "token", transport=httpx.MockTransport(fake), min_interval=0
    )
    return SnapshotFetcher(client, tmp_path / "snapshots", max_bytes=max_bytes)


def write_case(tmp_path: Path) -> tuple[list[dict[str, Any]], Path]:
    cache = tmp_path / "cache"
    cache.mkdir()
    rows = []
    for sha, path in [("aaa", "app.py"), ("bbb", "docs.md"), ("ccc", "svc.py"), ("ddd", "x.py")]:
        files = [{"filename": path, "status": "modified", "patch": PATCH}]
        (cache / f"{sha}.json").write_text(json.dumps({"files": files}))
        rows.append(
            {"sha": sha, "repo": "acme/app", "model_id": "gpt-3.5-turbo-0613", "found": True}
        )
    rows.append({"sha": "eee", "repo": "acme/app", "model_id": "x", "found": False})
    return rows, cache


APP = (
    "import openai\n" * 10 + 'MODEL = "gpt-3.5-turbo-0613"\n# keep\n# was gpt-3.5-turbo-0613 here\n'
).encode()


def test_build_end_to_end(tmp_path: Path) -> None:
    rows, cache = write_case(tmp_path)
    fake = FakeGitHub(
        {"aaa": {"app.py": APP, "conf.yaml": b"model: gpt-4o\n"}, "ccc": {"svc.py": b"x = 1\n"}}
    )
    fetcher = make_fetcher(tmp_path, fake)
    out = tmp_path / "out"
    stats = build(rows, cache, fetcher, load_registry(), out, sample=5, seed=1, per_group=10)
    # bbb only touched docs, eee was not found, ddd has no snapshot (404).
    assert stats["eligible_commits"] == 3
    assert stats["snapshots"] == 2
    assert stats["skipped"] == {"commit not found (404)": 1}
    assert stats["findings_by_context"] == {"assignment": 1, "comment": 1, "config": 1}
    # aaa: lines 11 and 13 found, line 41 is past the end of the file.
    # ccc: nothing found in svc.py.
    assert stats["recall"]["yes"] == 2
    assert stats["recall"]["n"] == 6
    assert stats["misses_by_reason"] == {"not found by the finder": 4}
    with (out / "sheet.csv").open(newline="") as f:
        sheet = list(csv.DictReader(f))
    assert tuple(sheet[0]) == SHEET_COLUMNS
    assert len(sheet) == 3
    by_line = {row["line_text"]: row for row in sheet}
    row = by_line['MODEL = "gpt-3.5-turbo-0613"']
    assert row["before"] == "import openai\nimport openai"
    assert row["after"] == "# keep\n# was gpt-3.5-turbo-0613 here"
    assert row["url"] == "https://github.com/acme/app/blob/paaa/app.py#L11"
    assert "context" not in row
    with (out / "sheet_key.csv").open(newline="") as f:
        key = list(csv.DictReader(f))
    assert {k["group"] for k in key} == {"code_use", "documentation", "config"}
    assert "Recall on 6 known sites: 33.3%" in summary(stats)
    # A rerun is served from the cache.
    downloads = fetcher.downloads
    again = build(
        rows,
        cache,
        make_fetcher(tmp_path, FakeGitHub({})),
        load_registry(),
        out,
        sample=5,
        seed=1,
        per_group=10,
    )
    assert again == stats
    assert fetcher.downloads == downloads


def test_snapshot_failures_are_recorded(tmp_path: Path) -> None:
    fake = FakeGitHub({"aaa": {"app.py": APP}, "bbb": {"a.py": b"x" * 5000}})
    fake.status["aaa"] = 451
    fetcher = make_fetcher(tmp_path, fake, max_bytes=100)
    assert fetcher.snapshot("acme/app", "aaa")["status"] == "download failed (451)"
    assert fetcher.snapshot("acme/app", "bbb")["status"] == "repository too large"


def test_rate_limit_on_download_stops_cleanly(tmp_path: Path) -> None:
    fake = FakeGitHub({"aaa": {"app.py": APP}})
    fake.rate_limited = True
    fetcher = make_fetcher(tmp_path, fake)
    with pytest.raises(RateLimitError):
        fetcher.snapshot("acme/app", "aaa")
    assert not (tmp_path / "snapshots" / "aaa.json").exists()


def test_main_needs_its_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert main(["--files", str(tmp_path / "missing.jsonl")]) == 1
    files = tmp_path / "files.jsonl"
    files.write_text("")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert main(["--files", str(files)]) == 1


def test_main_runs_and_reports_rate_limits(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rows, cache = write_case(tmp_path)
    files = tmp_path / "files.jsonl"
    files.write_text("".join(json.dumps(r) + "\n" for r in rows))
    fake = FakeGitHub({"aaa": {"app.py": APP}})
    client = CommitFilesClient(
        tmp_path / "api", "t", transport=httpx.MockTransport(fake), min_interval=0
    )
    args = ["--files", str(files), "--cache", str(cache), "--out", str(tmp_path / "out")]
    fake.rate_limited = True
    assert main(args, client=client) == 3
    fake.rate_limited = False
    assert main(args, client=client) == 0
    assert "Labelling sheet:" in capsys.readouterr().out


def test_eligible_commits_needs_a_cached_diff(tmp_path: Path) -> None:
    rows = [{"sha": "zzz", "repo": "a/b", "model_id": "gpt-4", "found": True}]
    assert eligible_commits(rows, tmp_path) == []
