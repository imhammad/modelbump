"""Tests for building the benchmark corpus. No network and no model is used."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from modelbump.synth.cases import find_cases
from research.corpus.build import Snapshots, build, main, measure, screen, summary
from research.enrichment.files import CommitFilesClient
from research.scanner_eval.build import SnapshotFetcher
from tests.research.test_scanner_eval import PATCH, FakeGitHub

CLASSIFY = b"""from openai import OpenAI

client = OpenAI()


def classify(ticket):
    return client.chat.completions.create(
        model="gpt-3.5-turbo-0613",
        messages=[
            {"role": "system", "content": "Reply with one word: billing, bug or other."},
            {"role": "user", "content": f"Ticket: {ticket}"},
        ],
    )


def summarize(text):
    return client.chat.completions.create(
        model="gpt-3.5-turbo-0613",
        messages=[{"role": "user", "content": "Summarize in JSON: " + text}],
    )


def tool(history):
    return client.chat.completions.create(model="gpt-4", messages=history, tools=[])
"""

TEST_FILE = b"""from app import classify


def test_classify():
    classify("I was charged twice")
"""

LIBRARY = b"""def complete(client, model, messages):
    return client.chat.completions.create(model=model, messages=messages)
"""

TOOLS_ONLY = b"""from openai import OpenAI

OpenAI().chat.completions.create(
    model="gpt-4", messages=[{"role": "user", "content": "Plan a trip"}], tools=[{}]
)
"""


def write_rows(tmp_path: Path, commits: list[tuple[str, str]]) -> tuple[list[dict[str, Any]], Path]:
    cache = tmp_path / "cache"
    cache.mkdir()
    rows = []
    for sha, repo in commits:
        files = [{"filename": "app.py", "status": "modified", "patch": PATCH}]
        (cache / f"{sha}.json").write_text(json.dumps({"files": files}))
        rows.append({"sha": sha, "repo": repo, "model_id": "gpt-3.5-turbo-0613", "found": True})
    return rows, cache


def make_snapshots(tmp_path: Path, fake: FakeGitHub) -> Snapshots:
    client = CommitFilesClient(
        tmp_path / "api", "token", transport=httpx.MockTransport(fake), min_interval=0
    )
    return Snapshots(tmp_path / "reuse", SnapshotFetcher(client, tmp_path / "new"))


def write_app(folder: Path, files: dict[str, bytes]) -> None:
    for name, data in files.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(data)


def test_measure_counts_calls_oracles_and_caller_inputs(tmp_path: Path) -> None:
    write_app(tmp_path, {"app.py": CLASSIFY, "tests/test_app.py": TEST_FILE})
    m = measure(find_cases(tmp_path, skip_tests=True))
    assert m["python_files"] == 1  # the test file is read for callers, not listed
    assert m["calls"] == 3
    assert m["calls_by_oracle"] == {"label": 1, "json": 1, "tools": 1}
    assert m["calls_with_text"] == 2
    assert m["with_slots"] == 2
    assert m["calls_with_caller_cases"] == 1
    assert m["app_models"] == ["gpt-3.5-turbo-0613", "gpt-4"]


@pytest.mark.parametrize(
    ("files", "reason"),
    [
        ({"README.json": b"{}"}, "no Python files"),
        ({"app.py": b"x = 1\n"}, "no LLM call found"),
        ({"lib.py": LIBRARY}, "no call with written prompt text"),
        ({"plan.py": TOOLS_ONLY}, "no call with written prompt text"),
        ({"app.py": CLASSIFY}, "ok"),
    ],
)
def test_screen_reasons(tmp_path: Path, files: dict[str, bytes], reason: str) -> None:
    write_app(tmp_path, files)
    assert screen({"status": "ok"}, tmp_path)[0] == reason


def test_screen_without_a_snapshot(tmp_path: Path) -> None:
    assert screen({"status": "repository too large"}, tmp_path) == (
        "no snapshot: repository too large",
        {},
    )


def test_build_reuses_snapshots_and_keeps_one_per_repo(tmp_path: Path) -> None:
    commits = [(sha, "acme/app") for sha in ("a1", "a2")] + [
        ("b1", "acme/lib"),
        ("c1", "acme/bot"),
        ("d1", "acme/gone"),
    ]
    rows, cache = write_rows(tmp_path, commits)
    # a1 and a2 were downloaded by the scanner evaluation already.
    reuse = tmp_path / "reuse"
    for sha in ("a1", "a2"):
        reuse.mkdir(exist_ok=True)
        meta = {"repo": "acme/app", "sha": sha, "parent": f"p{sha}", "status": "ok", "files": 1}
        (reuse / f"{sha}.json").write_text(json.dumps(meta))
        write_app(reuse / sha, {"app.py": CLASSIFY})
    fake = FakeGitHub({"b1": {"lib.py": LIBRARY}, "c1": {"bot.py": CLASSIFY}})
    snapshots = make_snapshots(tmp_path, fake)
    out = tmp_path / "out"
    stats = build(rows, cache, snapshots, out, target=10, seed=1)
    assert stats["apps"] == 2
    assert stats["screened"] == 5
    assert stats["left_out"] == {
        "repository already in corpus": 1,
        "no call with written prompt text": 1,
        "no snapshot: commit not found (404)": 1,
    }
    assert snapshots.reused == 1  # the second acme/app snapshot was never opened
    assert snapshots.fetcher.downloads == 2
    apps = [json.loads(line) for line in (out / "apps.jsonl").read_text().splitlines()]
    assert sorted(app["repo"] for app in apps) == ["acme/app", "acme/bot"]
    assert [app["app"] for app in apps] == [1, 2]
    assert all(app["retired_model"] == "gpt-3.5-turbo-0613" for app in apps)
    bot = next(app for app in apps if app["repo"] == "acme/bot")
    assert bot["url"] == "https://github.com/acme/bot/tree/pc1"
    assert bot["folder"] == str(tmp_path / "new" / "c1")
    assert (out / "apps.txt").read_text().splitlines() == [app["folder"] for app in apps]
    assert stats["calls_by_oracle"] == {"label": 2, "json": 2, "tools": 2}
    assert stats["apps_by_oracle"] == {"label": 2, "json": 2, "tools": 2}
    assert "Corpus: 2 apps (target 10)" in summary(stats)
    # The same seed gives the same corpus, from the cache.
    again = build(rows, cache, make_snapshots(tmp_path, FakeGitHub({})), out, target=10, seed=1)
    assert again == stats


def test_build_stops_at_the_target(tmp_path: Path) -> None:
    commits = [(f"s{i}", f"acme/app{i}") for i in range(5)]
    rows, cache = write_rows(tmp_path, commits)
    fake = FakeGitHub({sha: {"app.py": CLASSIFY} for sha, _ in commits})
    stats = build(rows, cache, make_snapshots(tmp_path, fake), tmp_path / "out", target=2)
    assert stats["apps"] == 2
    assert stats["screened"] == 2
    capped = build(
        rows, cache, make_snapshots(tmp_path, fake), tmp_path / "out", target=5, max_screened=3
    )
    assert capped["screened"] == 3


def test_main_needs_its_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert main(["--files", str(tmp_path / "missing.jsonl")]) == 1
    files = tmp_path / "files.jsonl"
    files.write_text("")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert main(["--files", str(files)]) == 1


def test_main_runs_and_reports_rate_limits(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rows, cache = write_rows(tmp_path, [("c1", "acme/bot")])
    files = tmp_path / "files.jsonl"
    files.write_text("".join(json.dumps(r) + "\n" for r in rows))
    fake = FakeGitHub({"c1": {"bot.py": CLASSIFY}})
    client = CommitFilesClient(
        tmp_path / "api", "t", transport=httpx.MockTransport(fake), min_interval=0
    )
    args = ["--files", str(files), "--cache", str(cache), "--out", str(tmp_path / "out")]
    args += ["--reuse", str(tmp_path / "reuse")]
    fake.rate_limited = True
    assert main(args, client=client) == 3
    assert "run the same command again later" in capsys.readouterr().out
    fake.rate_limited = False
    assert main(args, client=client) == 0
    out = capsys.readouterr().out
    assert "Corpus: 1 app (target 40)" in out
    assert "Reused 0 snapshots, downloaded 1." in out
