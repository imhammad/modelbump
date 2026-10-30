"""Tests for the baseline strategies: naive and iterative (ADR 0065)."""

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from modelbump.repair import Edit, Evidence, PromptPatch, write_proposals
from modelbump.repair.optimize import iterative_request, optimize, optimize_call
from modelbump.repair.propose import Strategy, naive_request, propose
from modelbump.runner import Budget, Runner
from modelbump.suite import Settings
from tests.repair.test_loop import SUITE, server
from tests.repair.test_patch import SUITE as SUITE_24  # two label cases and a text case
from tests.repair.test_propose import GOOD, proposer, report

EVIDENCE = Evidence(
    "support.py:24",
    3,
    ("support.py:24#1",),
    SUITE.cases[0].messages,
    "bug",
    (("question", ("same label as before (bug)",)),),
)
SETTINGS = Settings(old="ollama/old", new="ollama/new")


def answer_json(add_system: str) -> str:
    return json.dumps({"add_system": add_system, "edits": [], "why": "w"})


# --- Naive ------------------------------------------------------------------------


def test_naive_request_shows_the_prompt_but_no_answers() -> None:
    request = naive_request(EVIDENCE, "ollama/old", "ollama/new", "ollama/p", 2)
    text = request.messages[1].content
    assert "It was written for the model ollama/old, and the app now uses ollama/new" in text
    assert "--- system message ---\nYou sort support tickets." in text
    assert "so that it works well with ollama/new" in text
    assert "question" not in text.split("---")[-1].split("Reply")[0]  # no failing answer
    assert "old model (it passes)" not in text
    assert request.seed == 2


def test_propose_with_the_naive_strategy() -> None:
    runner, seen = proposer({0: json.dumps(GOOD), 1: "?"})
    (result,) = asyncio.run(
        propose(SUITE_24, report(), runner, model="ollama/p", count=2, strategy=Strategy.NAIVE)
    )
    assert [c.sample for c in result.candidates] == [0]
    assert all("works well with" in body["messages"][1]["content"] for body in seen)


def test_propose_refuses_the_iterative_strategy() -> None:
    runner, _ = proposer({})
    with pytest.raises(ValueError, match="use optimize"):
        asyncio.run(propose(SUITE_24, report(), runner, strategy=Strategy.ITERATIVE))


# --- Iterative --------------------------------------------------------------------


def test_iterative_request_lists_tried_changes_worst_first() -> None:
    tried = [
        (PromptPatch("support.py:24", add_system="A"), 0.9),
        (PromptPatch("support.py:24", add_system="B"), 0.1),
    ]
    text = (
        iterative_request(EVIDENCE, "o", "n", "ollama/p", 4, tried, (1.0, 0.67)).messages[1].content
    )
    assert "On this prompt o scores 1.00 and n scores 0.67." in text
    lines = text.splitlines()
    first = lines.index('- score 0.10: add_system "B"')
    assert lines[first + 1] == '- score 0.90: add_system "A"'
    assert "Propose one new small change, different from these" in text
    edits = PromptPatch("support.py:24", edits=(Edit("x", "y"),))
    assert '- score 0.50: edit "x" -> "y"' in (
        iterative_request(EVIDENCE, "o", "n", "p/p", 0, [(edits, 0.5)], (1, 0)).messages[1].content
    )
    first_round = iterative_request(EVIDENCE, "o", "n", "p/p", 0, [], (1, 0)).messages[1].content
    assert "Changes tried so far" not in first_round
    assert "so that n scores higher" in first_round


def models_and_proposer(answers: dict[int, str]) -> tuple[Runner, list[dict[str, Any]]]:
    """test_loop's models, plus a proposer that answers by seed."""
    seen: list[dict[str, Any]] = []
    models = server([])

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["messages"][0]["content"].startswith("You fix prompts"):
            seen.append(body)
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": answers[body["seed"]]}, "finish_reason": "stop"}
                    ],
                    "usage": {"prompt_tokens": 50, "completion_tokens": 20},
                },
            )
        return models.handle_request(request)

    return Runner(transport=httpx.MockTransport(handle)), seen


def test_optimize_runs_rounds_and_feeds_back_scores() -> None:
    runner, seen = models_and_proposer(
        {
            0: answer_json("Be nice."),
            1: answer_json("Always answer bug."),
            2: answer_json("Reply with the label only."),
            3: answer_json("Be nice."),
        }
    )
    result = asyncio.run(
        optimize_call(SUITE, EVIDENCE, runner, SETTINGS, model="ollama/p", rounds=2)
    )
    assert [c.sample for c in result.candidates] == [0, 1, 2]
    assert result.refused == ((3, "the same as sample 0"),)
    assert [(r, n, round(m, 2)) for r, n, m in result.trace] == [
        (0, 0, 0.67),
        (0, 1, 0.33),
        (1, 2, 1.0),
    ]
    assert len(seen) == 4
    second_round = seen[2]["messages"][1]["content"]
    assert "On this prompt ollama/old scores 1.00 and ollama/new scores 0.67." in second_round
    assert '- score 0.33: add_system "Always answer bug."' in second_round
    assert "Changes tried so far" not in seen[0]["messages"][1]["content"]


def test_optimize_stops_when_the_screen_fails() -> None:
    runner, _ = models_and_proposer({0: answer_json("Be nice.")})
    runner.budget = Budget(max_requests=5)
    result = asyncio.run(optimize_call(SUITE, EVIDENCE, runner, SETTINGS, model="ollama/p"))
    assert result.candidates == ()
    assert result.refused[0][1].startswith("the screen failed:")

    runner, _ = models_and_proposer({0: answer_json("Be nice."), 1: answer_json("x")})
    runner.budget = Budget(max_requests=45)  # the base screen fits, the first candidate's not
    result = asyncio.run(optimize_call(SUITE, EVIDENCE, runner, SETTINGS, model="ollama/p"))
    assert result.candidates == ()
    assert result.refused[0][1].startswith("the screen failed:")


def test_optimize_checks_its_numbers() -> None:
    runner, _ = models_and_proposer({})
    with pytest.raises(ValueError, match="at least 1"):
        asyncio.run(optimize_call(SUITE, EVIDENCE, runner, SETTINGS, rounds=0))


def test_optimize_every_regressed_call_of_a_report() -> None:
    runner, _ = models_and_proposer({n: answer_json(f"Rule {n}.") for n in range(6)})
    data = {"cases": [{"id": "support.py:24#1", "verdict": "REGRESSED", "answers": []}]}
    (result,) = asyncio.run(optimize(SUITE, data, runner, SETTINGS, model="ollama/p"))
    assert len(result.candidates) == 6  # 3 rounds of 2


def test_write_proposals_records_the_strategy_and_trace(tmp_path: Path) -> None:
    runner, _ = models_and_proposer({0: answer_json("Be nice."), 1: answer_json("x.")})
    result = asyncio.run(
        optimize_call(SUITE, EVIDENCE, runner, SETTINGS, model="ollama/p", rounds=1)
    )
    write_proposals([result], tmp_path, "ollama/p", strategy=Strategy.ITERATIVE)
    data = json.loads((tmp_path / "proposals.json").read_text(encoding="utf-8"))
    assert data["strategy"] == "iterative"
    assert data["calls"][0]["trace"][0] == {"round": 0, "sample": 0, "screen_mean": 0.6667}
