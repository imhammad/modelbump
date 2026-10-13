"""Tests for fetching and sorting the changed files of migration commits."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from research.enrichment.files import (
    CommitFilesClient,
    changed_lines,
    describe,
    draw,
    kind,
    main,
    only_ids,
    run,
)
from research.mining.github_search import RateLimitError, ServerError


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("tests/test_llm.py", "test"),
        ("src/app.test.ts", "test"),
        ("pkg/client_test.go", "test"),
        ("spec/models_spec.rb", "test"),
        ("__tests__/api.js", "test"),
        ("Tests/Unit/Service/RegistryTest.php", "test"),
        ("src/RegistryTest.php", "test"),
        ("Tests/helpers.swift", "test"),
        ("evals/golden.jsonl", "eval"),
        ("src/llm_eval.py", "eval"),
        ("promptfooconfig.yaml", "eval"),
        ("benchmark/run.py", "eval"),
        ("study/lib/llm_judge.py", "eval"),
        ("judges/rubric.yaml", "eval"),
        ("prompts/system.md", "prompt"),
        ("src/prompt_templates.yaml", "prompt"),
        (".github/workflows/ci.yml", "ci"),
        ("README.md", "docs"),
        ("docs/models.md", "docs"),
        (".env.example", "config"),
        ("config/models.yaml", "config"),
        ("package.json", "config"),
        ("src/llm.py", "code"),
        ("app/retrieval.py", "code"),
        ("src/medieval.py", "code"),
        ("src/judgement.py", "code"),
        ("src/Testimonials.php", "code"),
        ("assets/logo.png", "other"),
    ],
)
def test_kind(path: str, expected: str) -> None:
    assert kind(path) == expected


PATCH = """@@ -1,3 +1,3 @@
 import os
-MODEL = "gpt-4-0613"
+MODEL = "gpt-4o"
"""


def test_changed_lines_and_only_ids() -> None:
    assert changed_lines(PATCH) == ['MODEL = "gpt-4-0613"', 'MODEL = "gpt-4o"']
    assert only_ids(changed_lines(PATCH))
    assert not only_ids(['MODEL = "gpt-4o"', "timeout = 30"])
    assert not only_ids(["", "  "])


def commit(sha: str = "abc", repo: str = "a/b") -> dict[str, Any]:
    return {
        "sha": sha,
        "repo": repo,
        "url": f"https://github.com/{repo}/commit/{sha}",
        "model_id": "gpt-4-0613",
        "target": "gpt-4o",
        "ai_assisted": False,
    }


def gh_file(path: str, status: str = "modified", patch: str | None = PATCH) -> dict[str, Any]:
    f: dict[str, Any] = {"filename": path, "status": status, "additions": 1, "deletions": 1}
    if patch is not None:
        f["patch"] = patch
    return f


def test_describe() -> None:
    files = [
        gh_file("src/llm.py"),
        gh_file("tests/test_llm.py", "added", '+assert MODEL == "gpt-4o"\n'),
        gh_file("README.md", patch="+Uses gpt-4o and is fast.\n"),
    ]
    row = describe(commit(), files)
    assert row["found"] is True
    assert row["file_count"] == 3
    assert row["kinds"] == {"code": 1, "test": 1, "docs": 1}
    assert row["touches_test"] and row["adds_test"] and row["test_mentions_model"]
    assert not row["touches_eval"]
    assert row["id_swap_only"] is True  # the README line is ignored

    swap = describe(commit(), [gh_file("src/llm.py", patch="+MODEL = 'gpt-4o'\n+retries = 3\n")])
    assert swap["id_swap_only"] is False
    unknown = describe(commit(), [gh_file("model.bin", patch=None)])
    assert unknown["id_swap_only"] is None
    docs = describe(commit(), [gh_file("README.md")])
    assert docs["id_swap_only"] is False


class FakeCommits:
    """Serves commit file lists; counts requests."""

    def __init__(self, files: dict[str, list[dict[str, Any]]]) -> None:
        self.files = files
        self.calls: list[str] = []
        self.refusals: list[httpx.Response] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.refusals:
            return self.refusals.pop(0)
        sha = request.url.path.rsplit("/", 1)[-1]
        page = int(request.url.params["page"])
        self.calls.append(f"{sha}:{page}")
        if sha not in self.files:
            return httpx.Response(404, json={"message": "Not Found"})
        chunk = self.files[sha][(page - 1) * 100 : page * 100]
        return httpx.Response(200, json={"sha": sha, "files": chunk})


def client_for(fake: FakeCommits, tmp_path: Path, sleeps: list[float]) -> CommitFilesClient:
    return CommitFilesClient(
        tmp_path / "cache",
        "token",
        transport=httpx.MockTransport(fake.handler),
        sleep=sleeps.append,
        clock=lambda: 1000.0,
        min_interval=0.0,
    )


def test_client_pages_caches_and_reports_missing(tmp_path: Path) -> None:
    many = [gh_file(f"src/f{i}.py") for i in range(150)]
    fake = FakeCommits({"big": many, "small": [gh_file("a.py")]})
    client = client_for(fake, tmp_path, [])
    status, files = client.files("a/b", "big")
    assert status == 200 and len(files) == 150
    assert fake.calls == ["big:1", "big:2"]
    assert client.files("a/b", "big")[1] == files  # from the cache
    assert client.cache_hits == 1
    assert client.files("a/b", "gone") == (404, [])
    assert client.files("a/b", "gone") == (404, [])  # missing commits are cached too
    assert fake.calls.count("gone:1") == 1


def test_client_waits_on_rate_limit(tmp_path: Path) -> None:
    fake = FakeCommits({"x": [gh_file("a.py")]})
    fake.refusals.append(
        httpx.Response(
            403,
            headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1060"},
            json={"message": "API rate limit exceeded"},
        )
    )
    sleeps: list[float] = []
    client = client_for(fake, tmp_path, sleeps)
    assert client.files("a/b", "x")[0] == 200
    assert 61.0 in sleeps


def test_draw_is_repeatable() -> None:
    rows = [commit(f"s{i}") for i in range(50)]
    first = draw(rows, 10, 1)
    assert first == draw(list(reversed(rows)), 10, 1)
    assert len(first) == 10
    assert draw(rows, 99, 1) == sorted(rows, key=lambda r: r["sha"])


def test_run_and_main(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rows = [{**commit(f"s{i}"), "ai_assisted": i % 2 == 0} for i in range(6)]
    files = {
        "s0": [gh_file("src/llm.py"), gh_file("tests/test_llm.py")],
        "s1": [gh_file("src/llm.py")],
        "s2": [gh_file("evals/cases.jsonl", "added")],
        "s3": [gh_file("README.md")],
        "s4": [gh_file("src/llm.py", patch="+MODEL = 'gpt-4o'\n+x = 1\n")],
    }
    fake = FakeCommits(files)
    done, stats = run(rows, client_for(fake, tmp_path, []), size=6, seed=1)
    assert len(done) == 6
    assert stats.found == 5
    assert stats.missing == {"404": 1}
    assert stats.rates["touches a test file"].yes == 1
    assert stats.rates["adds an evaluation file"].yes == 1
    assert stats.rates["touches a test or evaluation file"].yes == 2
    assert stats.rates["pure ID swap (diffs known)"].yes == 3  # s0, s1, s2; not docs-only s3
    assert stats.kinds["code"] == 3
    assert stats.by_ai["AI-assisted"]["touches a test file"].n == 3  # s0, s2, s4

    targets = tmp_path / "targets.jsonl"
    targets.write_text("".join(json.dumps(r) + "\n" for r in rows))
    out_path = tmp_path / "files.jsonl"
    client = client_for(fake, tmp_path, [])
    code = main(["--targets", str(targets), "--out", str(out_path), "--sample", "6"], client=client)
    assert code == 0
    assert len(out_path.read_text().splitlines()) == 6
    assert json.loads((tmp_path / "files.stats.json").read_text())["found"] == 5
    assert "RQ4" in capsys.readouterr().out


def test_main_needs_targets_and_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--targets", str(tmp_path / "none.jsonl")]) == 1
    targets = tmp_path / "targets.jsonl"
    targets.write_text(json.dumps(commit()) + "\n")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert main(["--targets", str(targets)]) == 1
    assert "GITHUB_TOKEN" in capsys.readouterr().err


def test_client_retries_server_and_network_errors(tmp_path: Path) -> None:
    fake = FakeCommits({"x": [gh_file("a.py")]})
    fake.refusals.append(httpx.Response(502, text="Bad Gateway"))
    sleeps: list[float] = []
    assert client_for(fake, tmp_path, sleeps).files("a/b", "x")[0] == 200
    assert sleeps == [30.0]

    failures = {"left": 1}

    def flaky(request: httpx.Request) -> httpx.Response:
        if failures["left"]:
            failures["left"] -= 1
            raise httpx.ConnectError("offline", request=request)
        return fake.handler(request)

    sleeps = []
    client = CommitFilesClient(
        tmp_path / "cache2",
        transport=httpx.MockTransport(flaky),
        sleep=sleeps.append,
        clock=lambda: 0.0,
        min_interval=0.0,
    )
    assert client.files("a/b", "x")[0] == 200
    assert sleeps == [60.0]


def test_client_gives_up(tmp_path: Path) -> None:
    def always(status: int) -> CommitFilesClient:
        return CommitFilesClient(
            tmp_path / f"cache{status}",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(status, json={"message": "rate limit"})
            ),
            sleep=lambda _: None,
            clock=lambda: 0.0,
            min_interval=0.0,
            max_retries=1,
        )

    with pytest.raises(ServerError):
        always(503).files("a/b", "x")
    with pytest.raises(RateLimitError):
        always(429).files("a/b", "x")


def test_client_follows_a_renamed_repository(tmp_path: Path) -> None:
    fake = FakeCommits({"x": [gh_file("a.py")]})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/repos/old/name/"):
            new = str(request.url).replace("/repos/old/name/", "/repositories/123/")
            return httpx.Response(301, headers={"location": new})
        assert request.headers["authorization"] == "Bearer token"
        return fake.handler(request)

    client = CommitFilesClient(
        tmp_path / "cache",
        "token",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
        clock=lambda: 0.0,
        min_interval=0.0,
    )
    status, files = client.files("old/name", "x")
    assert status == 200 and len(files) == 1
