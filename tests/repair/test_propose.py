"""Tests for candidate patches written by a model (ADR 0063)."""

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from modelbump.repair import (
    Evidence,
    PromptPatch,
    propose,
    read_patches,
    regressed_calls,
    write_proposals,
)
from modelbump.repair.propose import parse_proposal, proposal_request, slug
from modelbump.runner import Runner
from modelbump.suite import Suite
from modelbump.suite.report import render_run_json
from tests.repair.test_patch import SUITE, run

GOOD = {"add_system": "Reply with the label only.", "edits": [], "why": "It adds words."}
EDIT = {
    "add_system": "",
    "edits": [{"find": "Answer with one label", "replace": "Answer with exactly one label"}],
    "why": "Stricter wording.",
}
OUTSIDE = {"edits": [{"find": "not in the prompt", "replace": "x"}], "why": "?"}


def report(patched: Suite | None = None) -> dict[str, Any]:
    """A real report of SUITE: the label cases (support.py:24) regress."""
    result, _ = run(patched)
    data: dict[str, Any] = json.loads(render_run_json(result))
    return data


def proposer(answers: dict[int, str]) -> tuple[Runner, list[dict[str, Any]]]:
    """A fake proposer that answers by seed."""
    seen: list[dict[str, Any]] = []

    def server(http_request: httpx.Request) -> httpx.Response:
        body = json.loads(http_request.content)
        seen.append(body)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": answers[body["seed"]]}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 30},
            },
        )

    return Runner(transport=httpx.MockTransport(server)), seen


# --- What the proposer is shown --------------------------------------------------


def test_regressed_calls_gathers_the_evidence() -> None:
    found = regressed_calls(SUITE, report())
    assert len(found) == 1
    evidence = found[0]
    assert evidence.call == "support.py:24"
    assert evidence.cases == 2 and evidence.edits_allowed
    assert evidence.regressed == ("support.py:24#1", "support.py:24#2")
    assert evidence.messages == SUITE.cases[0].messages
    assert evidence.reference == "bug"
    # Distinct failing new answers only: every one was "feature".
    assert evidence.failures == (("feature", ("same label as before (bug)",)),)


def test_regressed_calls_refuses_reports_that_do_not_fit() -> None:
    with pytest.raises(ValueError, match="has no cases"):
        regressed_calls(SUITE, {})
    other = report()
    other["cases"][0]["id"] = "elsewhere.py:1#1"
    with pytest.raises(ValueError, match=r"case elsewhere\.py:1#1 is not in the suite"):
        regressed_calls(SUITE, other)
    patched = report()
    patched["cases"][0]["patched_messages"] = [{"role": "system", "content": "x"}]
    with pytest.raises(ValueError, match="comes from a patched run"):
        regressed_calls(SUITE, patched)


def test_judge_fails_are_named() -> None:
    data = report()
    answer = next(a for a in data["cases"][0]["answers"] if a["model"] == "new")
    answer.update(failed=[], judge="FAIL", text="something else")
    found = regressed_calls(SUITE, data)
    assert ("something else", ("the judge failed it",)) in found[0].failures


def test_the_request_shows_prompt_reference_and_failures() -> None:
    evidence = regressed_calls(SUITE, report())[0]
    request = proposal_request(evidence, "ollama/old", "ollama/new", "ollama/p", 3, "d1")
    text = request.messages[1].content
    assert "It moved from the model ollama/old to ollama/new" in text
    assert "--- system message ---\nYou sort support tickets." in text
    assert "An answer from the old model (it passes):\nbug" in text
    assert "1. feature [failed: same label as before (bug)]" in text
    assert '"find"' in text
    assert (request.seed, request.sample, request.model_version) == (3, 3, "d1")
    assert request.temperature > 0


def test_one_case_calls_are_asked_for_add_system_only() -> None:
    evidence = regressed_calls(SUITE, report())[0]
    single = Evidence(**{**_fields(evidence), "cases": 1})
    text = proposal_request(single, "a", "b", "ollama/p", 0).messages[1].content
    assert 'always [] for this prompt; use "add_system" only' in text


def _fields(evidence: Evidence) -> dict[str, Any]:
    return {name: getattr(evidence, name) for name in Evidence.__slots__}


# --- Reading the proposer's answer ----------------------------------------------


EVIDENCE = Evidence("support.py:24", 2, ("support.py:24#1",), SUITE.cases[0].messages, "bug", ())


def test_parse_a_proposal_in_prose_or_a_fence() -> None:
    text = "Here you go:\n```json\n" + json.dumps(GOOD) + "\n```"
    parsed = parse_proposal(text, EVIDENCE, "by p")
    assert parsed == (
        PromptPatch("support.py:24", (), "Reply with the label only.", "by p"),
        "It adds words.",
    )


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("no json here", "no JSON object"),
        ("{not json}", "could not be read"),
        ('{"add_system": 3}', "add_system must be text"),
        ('{"edits": ["x"]}', "not a find/replace object"),
        ('{"add_system": "", "edits": []}', "changes nothing"),
    ],
)
def test_unusable_proposals(text: str, reason: str) -> None:
    parsed = parse_proposal(text, EVIDENCE, "")
    assert isinstance(parsed, str) and reason in parsed


def test_unusable_edits_are_dropped_when_there_is_an_add_system() -> None:
    both = {
        "add_system": "Be strict.",
        "edits": [{"find": "x", "replace": "x"}],
        "why": "w",
    }
    parsed = parse_proposal(json.dumps(both), EVIDENCE, "proposed")
    assert not isinstance(parsed, str)
    assert parsed[0].edits == () and parsed[0].add_system == "Be strict."
    assert parsed[0].note.startswith("proposed; edits dropped: ")
    alone = parse_proposal(json.dumps({**both, "add_system": ""}), EVIDENCE, "")
    assert isinstance(alone, str) and "replaces text with itself" in alone


def test_edits_are_dropped_where_only_add_system_is_allowed() -> None:
    single = Evidence(**{**_fields(EVIDENCE), "cases": 1})
    both = {**EDIT, "add_system": "Be strict."}
    parsed = parse_proposal(json.dumps(both), single, "")
    assert not isinstance(parsed, str) and parsed[0].edits == ()
    only = parse_proposal(json.dumps(EDIT), single, "")
    assert isinstance(only, str) and "add_system only" in only


# --- Proposing ---------------------------------------------------------------------


def test_propose_keeps_checked_distinct_candidates() -> None:
    runner, seen = proposer(
        {
            0: json.dumps(GOOD),
            1: json.dumps(GOOD),
            2: json.dumps(OUTSIDE),
            3: "?",
            4: json.dumps(EDIT),
            5: json.dumps({**OUTSIDE, "add_system": "Be brief."}),
        }
    )
    results = asyncio.run(propose(SUITE, report(), runner, model="ollama/p", count=6))
    assert len(seen) == 6 and {body["model"] for body in seen} == {"p"}
    (result,) = results
    assert [c.sample for c in result.candidates] == [0, 4, 5]
    salvaged = result.candidates[2].patch
    assert (salvaged.edits, salvaged.add_system) == ((), "Be brief.")
    assert "edits dropped: case support.py:24#1:" in salvaged.note
    assert result.candidates[0].why == "It adds words."
    assert result.candidates[1].patch.note == "proposed by ollama/p, sample 4"
    refused = dict(result.refused)
    assert refused[1] == "the same as sample 0"
    assert refused[2].startswith("does not fit the suite: case support.py:24#1:")
    assert refused[3] == "no JSON object in the answer"


def test_propose_with_nothing_regressed_asks_nothing() -> None:
    clean = report()
    for case in clean["cases"]:
        case["verdict"] = "EQUIVALENT"
    runner, seen = proposer({})
    assert asyncio.run(propose(SUITE, clean, runner)) == []
    assert seen == []
    with pytest.raises(ValueError, match="count must be at least 1"):
        asyncio.run(propose(SUITE, clean, runner, count=0))


def test_a_failed_proposer_call_is_refused() -> None:
    def server(http_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "bad request"}})

    runner = Runner(transport=httpx.MockTransport(server))
    (result,) = asyncio.run(propose(SUITE, report(), runner, count=1))
    assert result.candidates == ()
    assert result.refused[0][1].startswith("the model call failed:")


def test_write_proposals_writes_patch_files_and_a_summary(tmp_path: Path) -> None:
    runner, _ = proposer({0: json.dumps(GOOD), 1: json.dumps(EDIT), 2: "?"})
    results = asyncio.run(propose(SUITE, report(), runner, model="ollama/p", count=3))
    folder = tmp_path / "proposals"
    folder.mkdir()
    (folder / "support.py-24.07.json").write_text("old run", encoding="utf-8")
    written = write_proposals(results, folder, "ollama/p", "d1")
    assert [p.name for p in written] == ["support.py-24.00.json", "support.py-24.01.json"]
    assert not (folder / "support.py-24.07.json").exists()  # an earlier run's candidate
    assert read_patches(written[1])[0].edits == results[0].candidates[1].patch.edits
    summary = json.loads((folder / "proposals.json").read_text(encoding="utf-8"))
    assert (summary["proposer"], summary["proposer_version"]) == ("ollama/p", "d1")
    call = summary["calls"][0]
    assert call["regressed"] == ["support.py:24#1", "support.py:24#2"]
    assert call["candidates"][0] == {
        "file": "support.py-24.00.json",
        "sample": 0,
        "why": GOOD["why"],
    }
    assert call["refused"] == [{"sample": 2, "reason": "no JSON object in the answer"}]


def test_slug() -> None:
    assert slug("src/app/support.py:24") == "src_app_support.py-24"
