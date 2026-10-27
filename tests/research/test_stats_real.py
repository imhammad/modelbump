"""Tests for the real-model experiment (ADR 0046), with a fake Ollama."""

import json
import re
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from modelbump.runner import ChatRequest, ResponseCache, Runner
from research.stats_real.run import (
    NEW_MODEL,
    OLD_MODEL,
    Settings,
    collect,
    decide,
    inject,
    main,
    requests_for,
    split,
)
from research.stats_real.tasks import FAMILIES, Task, make_tasks, score
from tests.research.fake_ollama import fake_ollama

RATES = {
    "multiply": 0.8,
    "count": 0.6,
    "reverse": 0.9,
    "weekday": 0.3,
    "sort": 0.95,
    "letters": 0.5,
}


def _chance(model: str, task: Task) -> float:
    if model == "qwen3:8b" and task.family == "multiply":
        return 0.0  # the new model forgot how to multiply
    return RATES[task.family]


def _no_pin(requests: list[ChatRequest]) -> list[ChatRequest]:
    return list(requests)


def _runner(tasks: list[Task], cache: ResponseCache | None = None) -> Runner:
    return Runner(
        transport=httpx.MockTransport(fake_ollama(tasks, _chance)), cache=cache, concurrency=4
    )


def test_tasks_are_the_same_every_time_and_cover_every_family() -> None:
    tasks = make_tasks(3)
    assert tasks == make_tasks(3)
    assert len(tasks) == 3 * len(FAMILIES)
    assert {t.family for t in tasks} == set(FAMILIES)
    assert len({t.id for t in tasks}) == len(tasks)
    with pytest.raises(ValueError, match="per_family"):
        make_tasks(0)


def test_task_answers_are_computed_right() -> None:
    for task in make_tasks(5):
        if task.family == "multiply":
            a, b = (int(n) for n in re.findall(r"\d+", task.prompt))
            assert task.answer == str(a * b)
        if task.family == "weekday":
            text = task.prompt.removeprefix("What day of the week was ").split("?")[0]
            assert task.answer == datetime.strptime(text, "%d %B %Y").strftime("%A").lower()


@pytest.mark.parametrize(
    ("family", "answer", "text", "expected"),
    [
        ("multiply", "14792", "14,792", 1.0),
        ("multiply", "14792", "43 x 344 = 14792.", 1.0),
        ("multiply", "14792", "14782", 0.0),
        ("count", "2", "There are 2.", 1.0),
        ("weekday", "monday", "**Monday**", 1.0),
        ("weekday", "monday", "Monday or Tuesday", 0.0),
        ("sort", "candle, island", "Candle, Island.", 1.0),
        ("sort", "candle, island", "island, candle", 0.0),
        ("reverse", "eldeen", "'eldeen'", 1.0),
        ("reverse", "eldeen", "Reversed: eldeen", 1.0),
        ("letters", "styn", "s t y n", 1.0),
        ("letters", "styn", "stym", 0.0),
    ],
)
def test_score_is_lenient_about_form_but_not_about_the_answer(
    family: str, answer: str, text: str, expected: float
) -> None:
    assert score(Task("t", family, "prompt", answer), text) == expected


def test_requests_use_the_sample_as_seed_and_turn_qwen3_thinking_off() -> None:
    tasks = make_tasks(1)[:2]
    old = requests_for(tasks, OLD_MODEL, range(3))
    new = requests_for(tasks, NEW_MODEL, range(2))
    assert len(old) == 6
    assert [r.sample for r in old[:3]] == [0, 1, 2]
    assert all(r.seed == r.sample and r.temperature == 0.7 for r in old)
    assert {r.reasoning_effort for r in old} == {None}
    assert {r.reasoning_effort for r in new} == {"none"}


def test_collect_scores_answers_in_sample_order_and_reuses_the_cache() -> None:
    tasks = make_tasks(1)
    cache = ResponseCache()
    messages: list[str] = []
    first, rows = collect(
        tasks, OLD_MODEL, range(4), _runner(tasks, cache), _no_pin, messages.append
    )
    again, _ = collect(tasks, OLD_MODEL, range(4), _runner(tasks, cache), _no_pin, messages.append)
    cache.close()
    assert first == again
    assert all(len(scores) == 4 for scores in first.values())
    assert [r["sample"] for r in rows[:4]] == [0, 1, 2, 3]
    assert messages[0].startswith(f"{OLD_MODEL}: 24/24 answers (0 from the cache")
    assert messages[1].startswith(f"{OLD_MODEL}: 24/24 answers (24 from the cache")


def test_split_gives_two_separate_halves_and_inject_only_touches_chosen_cases() -> None:
    pool = {"a": [1.0, 1.0, 0.0, 0.0], "b": [1.0, 0.0, 1.0, 0.0]}
    old, new = split(pool, 2, shuffle=0)
    assert old == {"a": [1.0, 1.0], "b": [1.0, 0.0]}
    assert new == {"a": [0.0, 0.0], "b": [1.0, 0.0]}
    shuffled_old, shuffled_new = split(pool, 2, shuffle=1)
    assert sorted(shuffled_old["a"] + shuffled_new["a"]) == sorted(pool["a"])
    broken = inject({"a": [1.0] * 5, "b": [1.0] * 5}, {"a"}, 1.0, shuffle=0)
    assert broken == {"a": [0.0] * 5, "b": [1.0] * 5}


def test_decide_flags_a_clear_drop_with_every_method_and_nothing_when_equal() -> None:
    same = {f"case-{i}": [1.0] * 30 for i in range(6)}
    worse = dict(same) | {"case-0": [0.0] * 30}
    settings = Settings(small_k=10)
    for method, decision in decide(same, worse, settings).items():
        assert decision.flagged == ["case-0"], method
    for decision in decide(same, same, settings).values():
        assert decision.flagged == []


def test_quick_run_writes_results_and_finds_the_broken_family(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tasks = make_tasks(Settings.quick().per_family)
    assert main(["--quick", "--out", str(tmp_path)], runner=_runner(tasks), pin=_no_pin) == 0
    results = json.loads((tmp_path / "results.json").read_text())
    assert results["pass_rates"][NEW_MODEL]["multiply"] == 0.0
    # 10 answers are too few for the sequential suite; fixed k + BH finds both.
    assert results["natural"]["flagged"]["fixed k=10 + BH"] == 2
    assert set(results["natural"]["per_task"]) == {t.id for t in tasks}
    assert {row["inject_rate"] for row in results["injected"]} == {0.3, 0.6}
    assert all(row["false_alarms"] == 0 for row in results["null"] if "BH" in row["method"])
    lines = (tmp_path / "answers.jsonl").read_text().splitlines()
    assert len(lines) == 12 * 10 * 3
    assert (tmp_path / "tasks.csv").read_text().startswith("task,family,answer")
    out = capsys.readouterr().out
    assert "12 test cases, 10 answers per model per comparison: 360 answers in all" in out
    assert "  multiply: 88% / 0%" in out


def test_a_stopped_ollama_gives_a_clear_error(capsys: pytest.CaptureFixture[str]) -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    runner = Runner(transport=httpx.MockTransport(down), max_attempts=1)
    assert main(["--quick"], runner=runner, pin=_no_pin) == 1
    assert "open -a Ollama" in capsys.readouterr().err
