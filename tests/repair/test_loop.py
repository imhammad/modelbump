"""Tests for the repair loop: screen, then confirm on fresh answers (ADR 0064)."""

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from modelbump.oracles import OracleChoice, OutputKind
from modelbump.repair import Candidate, Evidence, PromptPatch, Proposals, write_proposals
from modelbump.repair.loop import (
    CONFIRM_OFFSET,
    CallCandidates,
    LoopSettings,
    check_case,
    read_candidates,
    repair_call,
    repair_suite,
)
from modelbump.repair.report import render_repair_json, render_repair_text, repair_summary
from modelbump.runner import Budget, Runner
from modelbump.suite import Settings, Suite, SuiteCase

LABELS = OracleChoice(OutputKind.LABEL, "r", ("bug", "feature", "question"))
SYSTEM = "You sort support tickets.\nAnswer with one label: bug, feature, question.\n"
TICKETS = {"The app crashes.": "bug", "Add dark mode.": "feature", "How do I export?": "question"}


def case(ticket: str, number: int, line: int = 24) -> SuiteCase:
    return SuiteCase(
        id=f"support.py:{line}#{number}",
        path="support.py",
        line=line,
        api="openai_chat",
        app_model="gpt-4o-mini",
        oracle=LABELS,
        source="tests/test_support.py:16",
        generated_by=None,
        messages=(("system", SYSTEM), ("user", f"Ticket:\n{ticket}")),
    )


SUITE = Suite(
    (
        *(case(ticket, n) for n, ticket in enumerate(TICKETS, start=1)),
        case("Add dark mode.", 1, line=40),
    )
)
FIX = PromptPatch("support.py:24", add_system="Reply with the label only.")
NOTHING = PromptPatch("support.py:24", add_system="Be nice.")
ALWAYS_BUG = PromptPatch("support.py:24", add_system="Always answer bug.")
LUCKY = PromptPatch("support.py:24", add_system="Lucky.")
SETTINGS = Settings(old="ollama/old", new="ollama/new")


def server(seen: list[dict[str, Any]]) -> httpx.MockTransport:
    """The old model is always right. The new one gets the crash ticket wrong, unless patched.

    "label only" fixes it; "Always answer bug" fixes the crash and breaks the others;
    "Lucky" is right only on the samples screening uses, never on fresh ones.
    """

    def answer(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        system = body["messages"][0]["content"]
        ticket = body["messages"][-1]["content"].removeprefix("Ticket:\n")
        right = TICKETS[ticket]
        if body["model"] == "old" or "label only" in system:
            text = right
        elif "Always answer bug" in system:
            text = "bug"
        elif "Lucky" in system:
            text = right if body["seed"] < CONFIRM_OFFSET else "question"
        else:
            text = "question" if ticket == "The app crashes." else right
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 1},
            },
        )

    return httpx.MockTransport(answer)


def run(
    candidates: list[tuple[str, PromptPatch]], budget: Budget | None = None, **loop: Any
) -> tuple[Any, list[dict[str, Any]]]:
    seen: list[dict[str, Any]] = []
    runner = Runner(transport=server(seen), budget=budget)
    entry = CallCandidates("support.py:24", ("support.py:24#1",), tuple(candidates))
    result = asyncio.run(repair_call(SUITE, entry, runner, SETTINGS, LoopSettings(**loop)))
    return result, seen


# --- The loop ---------------------------------------------------------------------


def test_the_fix_is_screened_first_and_accepted() -> None:
    result, seen = run([("nothing.json", NOTHING), ("fix.json", FIX), ("bug.json", ALWAYS_BUG)])
    assert [s.file for s in result.screened] == ["fix.json", "nothing.json", "bug.json"]
    assert [round(s.new_mean, 2) for s in result.screened] == [1.0, 0.67, 0.33]
    assert (result.old_mean, round(result.unpatched_mean, 2)) == (1.0, 0.67)
    assert result.cases == 3  # only the call's own cases; support.py:40 is left alone
    assert result.patch == FIX
    (confirmation,) = result.confirmations
    assert confirmation.accepted
    assert [c.case_id for c in confirmation.checks] == [f"support.py:24#{n}" for n in (1, 2, 3)]
    assert all((c.old_passes, c.new_passes, c.runs) == (100, 100, 100) for c in confirmation.checks)
    # Screening reuses the test's samples (3-12); confirming uses fresh ones.
    new_fix = [b["seed"] for b in seen if b["model"] == "new" and "label only" in json.dumps(b)]
    assert min(new_fix) == 3
    assert {s for s in new_fix if s > 12} == set(range(CONFIRM_OFFSET + 3, CONFIRM_OFFSET + 103))
    old_seeds = {b["seed"] for b in seen if b["model"] == "old"}
    assert old_seeds == set(range(13)) | set(range(CONFIRM_OFFSET + 3, CONFIRM_OFFSET + 103))


def test_a_patch_that_breaks_another_case_is_rejected() -> None:
    result, _ = run([("bug.json", ALWAYS_BUG)], max_gap=1.0)  # confirm however it screens
    assert result.patch is None
    (confirmation,) = result.confirmations
    assert not confirmation.accepted
    oks = {c.case_id: c.ok for c in confirmation.checks}
    assert oks == {"support.py:24#1": True, "support.py:24#2": False, "support.py:24#3": False}
    broken = confirmation.checks[1]
    assert (broken.old_passes, broken.new_passes) == (100, 0)


def test_luck_in_screening_does_not_survive_fresh_answers() -> None:
    result, _ = run([("lucky.json", LUCKY), ("fix.json", FIX)])
    assert [s.file for s in result.screened] == ["lucky.json", "fix.json"]  # a tie keeps order
    assert result.patch is None  # only the best one is confirmed by default
    assert [c.file for c in result.confirmations] == ["lucky.json"]


def test_confirming_more_candidates_splits_alpha() -> None:
    result, _ = run([("lucky.json", LUCKY), ("fix.json", FIX)], top=2)
    assert [(c.file, c.accepted) for c in result.confirmations] == [
        ("lucky.json", False),
        ("fix.json", True),
    ]
    assert result.patch == FIX
    check = result.confirmations[1].checks[0]
    assert check.low == pytest.approx(check_case("x", [1] * 100, [1] * 100, 0.025, 0.1).low)


def test_check_case_is_non_inferiority_against_the_old_model() -> None:
    assert check_case("x", [1] * 100, [1] * 100, 0.05, 0.10).ok
    assert check_case("x", [1] * 50, [1] * 50, 0.05, 0.10).ok
    assert not check_case("x", [1] * 30, [1] * 30, 0.05, 0.10).ok  # too few answers to show it
    assert not check_case("x", [1] * 100, [1] * 80 + [0] * 20, 0.05, 0.10).ok
    partial = check_case("x", [0.5] * 10, [0.5] * 10, 0.05, 0.10)
    assert (partial.old_passes, partial.new_passes) == (5, 5)


def test_a_call_without_candidates_or_cases() -> None:
    result, seen = run([])
    assert result.screened == () and result.confirmations == () and result.patch is None
    assert {b["model"] for b in seen} == {"old", "new"}  # the unpatched screen only
    entry = CallCandidates("nowhere.py:1", (), ())
    with pytest.raises(ValueError, match=r"no case in the suite for call nowhere\.py:1"):
        asyncio.run(
            repair_call(SUITE, entry, Runner(transport=server([])), SETTINGS, LoopSettings())
        )


def test_the_budget_stops_the_loop_without_accepting() -> None:
    result, _ = run([("fix.json", FIX)], budget=Budget(max_requests=40))
    assert result.patch is None
    assert result.unpatched_mean is None
    assert result.screened[0].error is not None
    assert result.confirmations == ()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"screen_runs": 0}, "at least 1"),
        ({"top": 0}, "at least 1"),
        ({"alpha": 0.5}, "alpha"),
        ({"margin": 0}, "margin"),
    ],
)
def test_loop_settings_check_their_numbers(kwargs: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        LoopSettings(**kwargs)


def test_settings_offset_must_not_be_negative() -> None:
    with pytest.raises(ValueError, match="offset"):
        Settings(old="ollama/a", new="ollama/b", offset=-1)


# --- Reading candidates and reports -----------------------------------------------


def write_folder(folder: Path, patches: list[PromptPatch]) -> None:
    evidence = Evidence("support.py:24", 3, ("support.py:24#1",), SUITE.cases[0].messages, "", ())
    candidates = tuple(Candidate(n, patch, "why") for n, patch in enumerate(patches))
    write_proposals([Proposals(evidence, candidates, ())], folder, "ollama/p")


def test_read_candidates_from_a_propose_folder(tmp_path: Path) -> None:
    write_folder(tmp_path, [FIX, ALWAYS_BUG])
    (entry,) = read_candidates(tmp_path, SUITE)
    assert entry.call == "support.py:24"
    assert entry.regressed == ("support.py:24#1",)
    assert entry.candidates == (
        ("support.py-24.00.json", FIX),
        ("support.py-24.01.json", ALWAYS_BUG),
    )


def test_read_candidates_errors(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"has no proposals\.json"):
        read_candidates(tmp_path, SUITE)
    (tmp_path / "proposals.json").write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="cannot be read"):
        read_candidates(tmp_path, SUITE)
    write_folder(tmp_path, [PromptPatch("support.py:24", (), "x")])
    (tmp_path / "support.py-24.00.json").write_text(
        json.dumps({"version": 1, "patches": [{"call": "gone.py:1", "add_system": "x"}]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=r"cannot be used: no case .* gone\.py:1"):
        read_candidates(tmp_path, SUITE)
    two = {"call": "support.py:24", "add_system": "x"}
    (tmp_path / "support.py-24.00.json").write_text(
        json.dumps({"version": 1, "patches": [two, two]}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="is not a one-patch file"):
        read_candidates(tmp_path, SUITE)


def test_repair_suite_and_reports() -> None:
    runner = Runner(transport=server([]))
    calls = [
        CallCandidates("support.py:24", ("support.py:24#1",), (("fix.json", FIX),)),
        CallCandidates("support.py:24", ("support.py:24#1",), (("bug.json", ALWAYS_BUG),)),
        CallCandidates("support.py:24", ("support.py:24#1",), ()),
    ]
    loop = LoopSettings(confirm_runs=50, max_gap=1.0)
    results = asyncio.run(repair_suite(SUITE, calls, runner, SETTINGS, loop))
    assert repair_summary(results) == "Result: 1 of 3 calls repaired."
    text = render_repair_text(results, SETTINGS, loop).splitlines()
    assert text[0] == (
        "Repair ollama/old -> ollama/new: screen each candidate on 10 runs, "
        "confirm the best candidate on 50 fresh runs (alpha 0.05, margin 0.10, max gap 1.00)."
    )
    assert text[1] == "REPAIRED      support.py:24  (3 test cases)"
    assert "              screen: old 1.00, unpatched new 0.67" in text
    assert "                fix.json: new 1.00" in text
    assert "              confirm fix.json: accepted" in text
    assert (
        "                support.py:24#1: old 50/50, patched new 50/50, lower bound -0.07 > -0.10"
        in text
    )
    assert "NOT REPAIRED  support.py:24  (3 test cases)" in text
    assert (
        "                support.py:24#2: old 50/50, patched new 0/50, lower bound -1.00 <= -0.10"
        in text
    )
    assert "NO CANDIDATES support.py:24  (3 test cases)" in text
    data = json.loads(render_repair_json(results, SETTINGS, loop))
    assert [c["status"] for c in data["calls"]] == ["REPAIRED", "NOT REPAIRED", "NO CANDIDATES"]
    assert data["calls"][0]["accepted"] == "fix.json"
    assert data["calls"][1]["confirmations"][0]["checks"][1]["ok"] is False
    assert (data["confirm_runs"], data["top"]) == (50, 1)


def test_report_for_a_call_that_could_not_be_run() -> None:
    result, _ = run([("fix.json", FIX)], budget=Budget(max_requests=40))
    text = render_repair_text([result], SETTINGS, LoopSettings())
    assert "NOT RUN       support.py:24  (3 test cases)" in text
    assert "fix.json: " in text
    multi = render_repair_text([result], SETTINGS, LoopSettings(top=2))
    assert "confirm the best 2 candidates" in multi


def test_a_candidate_that_screens_far_below_the_old_model_is_not_confirmed() -> None:
    result, seen = run([("bug.json", ALWAYS_BUG)])  # screens 0.33, old 1.00
    assert result.skipped == ("bug.json",)
    assert result.confirmations == () and result.patch is None
    assert not [b for b in seen if b["seed"] >= CONFIRM_OFFSET]  # no fresh answers spent
    text = render_repair_text([result], SETTINGS, LoopSettings())
    assert "NOT REPAIRED  support.py:24  (3 test cases)" in text
    assert "confirm bug.json: skipped, screen 0.33 is more than 0.25 below old" in text
    data = json.loads(render_repair_json([result], SETTINGS, LoopSettings()))
    assert data["calls"][0]["skipped"] == ["bug.json"]
    assert data["max_gap"] == 0.25
    with pytest.raises(ValueError, match="max gap"):
        LoopSettings(max_gap=1.5)
