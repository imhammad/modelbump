"""Tests for running the corpus end to end. A fake server stands in for every model."""

import asyncio
import json
import random
from pathlib import Path
from typing import Any

import httpx
import pytest

from modelbump.oracles.calibrate import make_sheet
from modelbump.runner import Runner
from modelbump.suite import Method, Settings, Suite
from modelbump.synth.cases import find_cases
from research.corpus.run import (
    can_test,
    main,
    merge_reports,
    one_case_per_call,
    pick_calls,
    run_corpus,
    summary,
)
from tests.research.test_corpus import CLASSIFY, LIBRARY
from tests.suite.test_run import make_case

HISTORY = b"""from openai import OpenAI


def chat(history):
    return OpenAI().chat.completions.create(model="gpt-4", messages=history)


def fixed():
    return OpenAI().chat.completions.create(
        model="gpt-4", messages=[{"role": "user", "content": "Write a haiku about rain."}]
    )
"""


def fake_runner() -> tuple[Runner, list[dict[str, Any]]]:
    seen: list[dict[str, Any]] = []

    def server(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        system = body["messages"][0]["content"]
        prompt = body["messages"][-1]["content"]
        if system.startswith("You write test inputs"):
            slots = json.loads(prompt.split("exactly the keys ")[1].split(", and every")[0])
            text = json.dumps([{slot: f"value {body['seed']}" for slot in slots}])
        elif system.startswith("You grade"):
            text = "PASS"
        elif "billing, bug or other" in system:
            text = "other" if "qwen3" in body["model"] else "bug"  # the new model regresses
        elif "JSON" in prompt:
            text = '{"summary": "ok"}'
        else:
            text = f"Rain falls softly, number {body['seed']}."
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    return Runner(transport=httpx.MockTransport(server)), seen


def write_corpus(tmp_path: Path) -> Path:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    apps = []
    for number, (repo, files) in enumerate(
        [
            ("acme/bot", {"app.py": CLASSIFY}),
            ("acme/lib", {"lib.py": LIBRARY}),
            ("acme/poet", {"poet.py": HISTORY}),
        ],
        start=1,
    ):
        folder = tmp_path / "apps" / str(number)
        folder.mkdir(parents=True)
        for name, data in files.items():
            (folder / name).write_bytes(data)
        apps.append({"app": number, "repo": repo, "folder": str(folder)})
    (corpus / "apps.jsonl").write_text("".join(json.dumps(a) + "\n" for a in apps))
    return corpus


SETTINGS = Settings(
    old="ollama/qwen2.5:7b",
    new="ollama/qwen3:8b",
    runs=10,
    method=Method.FIXED,
    new_think="none",
    judge="ollama/gemma3:12b",
)


def test_testable_calls_and_picking(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_bytes(CLASSIFY)
    (tmp_path / "poet.py").write_bytes(HISTORY)
    result = find_cases(tmp_path)
    # classify and summarize can be tested; the tool call and the history-only call cannot.
    assert [e.site.line for e in result.sites if can_test(e)] == [7, 17, 9]
    picked = pick_calls(result, 2, random.Random(1))
    assert len(picked.sites) == 2
    assert [(e.site.path, e.site.line) for e in picked.sites] == sorted(
        (e.site.path, e.site.line) for e in picked.sites
    )
    assert picked == pick_calls(result, 2, random.Random(1))
    assert len(pick_calls(result, 10, random.Random(1)).sites) == 3


def test_one_case_per_call() -> None:
    cases = (make_case("a"), make_case("b"))
    assert len(one_case_per_call(Suite(cases)).cases) == 1  # same path and line


def test_merge_reports_prefixes_ids_and_keeps_a_judge() -> None:
    plain = {"judge": None, "counts": {"REGRESSED": 1}, "cases": [{"id": "a.py:1#1"}]}
    judged = {"judge": "j", "counts": {"REGRESSED": 0, "EQUIVALENT": 2}, "cases": [{"id": "b#1"}]}
    merged = merge_reports([("app-01", plain), ("app-02", judged)])
    assert merged["judge"] == "j"
    assert [c["id"] for c in merged["cases"]] == ["app-01/a.py:1#1", "app-02/b#1"]
    assert merged["counts"] == {"REGRESSED": 1, "EQUIVALENT": 2}
    assert merged["apps"] == ["app-01", "app-02"]
    with pytest.raises(ValueError):
        merge_reports([])


def test_run_corpus_end_to_end(tmp_path: Path) -> None:
    corpus = write_corpus(tmp_path)
    apps = [json.loads(line) for line in (corpus / "apps.jsonl").read_text().splitlines()]
    runner, seen = fake_runner()
    stats = asyncio.run(run_corpus(apps, runner, SETTINGS, corpus, calls=3, seed=1))
    assert stats["apps"] == 3
    assert stats["apps_with_cases"] == 2  # the library has nothing to test
    assert stats["cases"] == 3  # classify, summarize, the haiku
    assert stats["generated_cases"] == 2
    assert stats["cases_by_oracle"] == {"label": 1, "json": 1, "text": 1}
    assert stats["verdicts"]["REGRESSED"] == 1
    assert stats["apps_with_a_regression"] == 1
    runs = corpus / "runs"
    assert sorted(p.name for p in runs.iterdir()) == [
        "app-01.report.json",
        "app-01.suite.json",
        "app-02.suite.json",
        "app-03.report.json",
        "app-03.suite.json",
    ]
    rows = [json.loads(line) for line in (corpus / "runs.jsonl").read_text().splitlines()]
    assert [row["cases"] for row in rows] == [2, 0, 1]
    # The bot app has no free text, so its run had no judge; the merged report has one.
    bot = json.loads((runs / "app-01.report.json").read_text())
    assert bot["judge"] is None
    merged = json.loads((corpus / "report-all.json").read_text())
    assert merged["judge"] == "ollama/gemma3:12b"
    assert {c["id"].split("/")[0] for c in merged["cases"]} == {"app-01", "app-03"}
    assert {b["model"] for b in seen} == {"qwen2.5:7b", "qwen3:8b", "gemma3:12b"}
    # The merged report feeds `modelbump judge sheet` as it is.
    made = make_sheet(corpus / "report-all.json", tmp_path / "s.csv", tmp_path / "k.json", size=4)
    assert made.answers == 4
    assert "Ran 3 apps (2 with test cases)" in summary(stats)


def test_main_needs_the_corpus(tmp_path: Path) -> None:
    assert main(["--corpus", str(tmp_path)]) == 1


def test_main_runs_the_first_apps(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    corpus = write_corpus(tmp_path)
    runner, _ = fake_runner()
    assert main(["--corpus", str(corpus), "--apps", "1", "--runs", "5"], runner=runner) == 0
    out = capsys.readouterr().out
    assert "Ran 1 apps (1 with test cases)" in out
    stats = json.loads((corpus / "run.stats.json").read_text())
    assert (stats["runs"], stats["apps"]) == (5, 1)


def test_drop_case_and_out_folder(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    corpus = write_corpus(tmp_path)
    runner, _ = fake_runner()
    out = tmp_path / "run-v2"
    args = ["--corpus", str(corpus), "--out", str(out), "--drop-case", "app-03/poet.py:9#1"]
    assert main(args, runner=runner) == 0
    assert "1 dropped by hand" in capsys.readouterr().out
    stats = json.loads((out / "run.stats.json").read_text())
    assert (stats["cases"], stats["dropped"]) == (2, 1)
    assert not (out / "runs" / "app-03.report.json").exists()
    assert not (corpus / "run.stats.json").exists()  # the corpus folder only gets read


def test_main_with_another_new_model(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    corpus = write_corpus(tmp_path)
    runner, seen = fake_runner()
    out = tmp_path / "run-4b"
    args = ["--corpus", str(corpus), "--out", str(out), "--apps", "1", "--new", "ollama/qwen3:4b"]
    assert main(args, runner=runner) == 0
    assert "ollama/qwen2.5:7b -> ollama/qwen3:4b" in capsys.readouterr().out
    assert "qwen3:4b" in {body["model"] for body in seen}
    assert "qwen3:8b" not in {body["model"] for body in seen}
