"""Tests for prompt patches and for running a patched suite (ADR 0062)."""

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from modelbump.oracles import OracleChoice, OutputKind
from modelbump.repair import (
    Edit,
    PatchError,
    PromptPatch,
    apply_patch,
    apply_patches,
    call_of,
    patch_diff,
    patches_to_json,
    read_patches,
)
from modelbump.runner import Runner
from modelbump.stats import Verdict
from modelbump.suite import Settings, Suite, SuiteCase, run_suite_on_models
from modelbump.suite.report import method_line, render_run_json, render_run_text

LABELS = OracleChoice(OutputKind.LABEL, "r", ("bug", "feature", "question"))
TEXT = OracleChoice(OutputKind.TEXT, "r")
SYSTEM = "You sort support tickets.\nAnswer with one label: bug, feature, question.\n"


def make_case(
    ticket: str, number: int, line: int = 24, oracle: OracleChoice = LABELS, system: bool = True
) -> SuiteCase:
    messages = (("system", SYSTEM),) if system else ()
    return SuiteCase(
        id=f"support.py:{line}#{number}",
        path="support.py",
        line=line,
        api="openai_chat",
        app_model="gpt-4o-mini",
        oracle=oracle,
        source="tests/test_support.py:16",
        generated_by=None,
        messages=(*messages, ("user", f"Ticket:\n{ticket}" if oracle is LABELS else ticket)),
    )


SUITE = Suite(
    (
        make_case("The app crashes.", 1),
        make_case("Add dark mode.", 2),
        make_case("Summarize: my order is late.", 1, line=30, oracle=TEXT),
    )
)
LABEL_PATCH = PromptPatch(
    "support.py:24",
    edits=(Edit("Answer with one label", "Answer with exactly one label"),),
    add_system="Reply with the label only.",
)


# --- Building and applying patches ------------------------------------------------


def test_call_of_a_case() -> None:
    assert call_of(SUITE.cases[1]) == "support.py:24"


def test_edits_then_system_text() -> None:
    patched = apply_patch(SUITE.cases[0], LABEL_PATCH)
    assert patched.id == SUITE.cases[0].id
    assert patched.messages[0] == (
        "system",
        "You sort support tickets.\nAnswer with exactly one label: bug, feature, question."
        "\n\nReply with the label only.",
    )
    assert patched.messages[1] == SUITE.cases[0].messages[1]  # the input is untouched


def test_system_text_becomes_a_new_first_message_when_there_is_none() -> None:
    case = make_case("x", 1, system=False)
    patched = apply_patch(case, PromptPatch("support.py:24", add_system="  Be brief.  "))
    assert patched.messages[0] == ("system", "Be brief.")
    assert patched.messages[1:] == case.messages


def test_an_edit_must_match_exactly_once() -> None:
    missing = PromptPatch("support.py:24", edits=(Edit("no such text", "x"),))
    with pytest.raises(PatchError, match="'no such text' is found 0 times"):
        apply_patch(SUITE.cases[0], missing)
    twice = PromptPatch("support.py:24", edits=(Edit("e", "E"),))
    with pytest.raises(PatchError, match=r"found \d+ times; an edit must match exactly once"):
        apply_patch(SUITE.cases[0], twice)


def test_an_edit_that_hits_one_cases_input_fails_on_the_others() -> None:
    # "crashes" is in case 1's ticket only: with two cases, inputs cannot be edited.
    patch = PromptPatch("support.py:24", edits=(Edit("crashes", "works"),))
    with pytest.raises(PatchError, match=r"case support.py:24#2: 'crashes' is found 0 times"):
        apply_patches(SUITE, (patch,))


def test_a_patch_must_belong_to_the_case() -> None:
    with pytest.raises(PatchError, match=r"does not belong to case support\.py:30#1"):
        apply_patch(SUITE.cases[2], LABEL_PATCH)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"call": "support.py"}, "is not path:line"),
        ({"call": "support.py:x"}, "is not path:line"),
        ({"call": "support.py:24"}, "changes nothing"),
        ({"call": "support.py:24", "add_system": "  "}, "changes nothing"),
        ({"call": "a.py:1", "edits": (Edit("", "x"),)}, "empty find"),
        ({"call": "a.py:1", "edits": (Edit("a", "b"), Edit("a", "c"))}, "same find"),
        ({"call": "a.py:1", "edits": (Edit("a", "a"),)}, "replaces text with itself"),
    ],
)
def test_bad_patches_are_refused(kwargs: dict[str, Any], message: str) -> None:
    with pytest.raises(PatchError, match=message):
        PromptPatch(**kwargs)


def test_apply_patches_keeps_ids_and_order_and_leaves_other_calls_alone() -> None:
    patched = apply_patches(SUITE, (LABEL_PATCH,))
    assert [c.id for c in patched.cases] == [c.id for c in SUITE.cases]
    assert patched.cases[0].messages != SUITE.cases[0].messages
    assert patched.cases[2] == SUITE.cases[2]


def test_apply_patches_refuses_unknown_and_repeated_calls() -> None:
    with pytest.raises(PatchError, match=r"no case in the suite for call bot\.py:14"):
        apply_patches(SUITE, (PromptPatch("bot.py:14", add_system="x"),))
    with pytest.raises(PatchError, match=r"two patches for support\.py:24"):
        apply_patches(SUITE, (LABEL_PATCH, PromptPatch("support.py:24", add_system="x")))


def test_patch_file_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "patch.json"
    note = PromptPatch("support.py:30", add_system="Use plain words.", note="by hand")
    path.write_text(patches_to_json((LABEL_PATCH, note)), encoding="utf-8")
    assert read_patches(path) == (LABEL_PATCH, note)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("{", "is not valid JSON"),
        ('{"version": 2, "patches": []}', "is not a version 1 patch file"),
        ('{"version": 1}', "a patch is missing a field"),
        ('{"version": 1, "patches": [{"edits": []}]}', "a patch is missing a field"),
        ('{"version": 1, "patches": []}', "has no patches"),
        ('{"version": 1, "patches": [{"call": "a.py:1"}]}', "changes nothing"),
    ],
)
def test_bad_patch_files(tmp_path: Path, text: str, message: str) -> None:
    path = tmp_path / "patch.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(PatchError, match=message):
        read_patches(path)


def test_patch_diff_shows_the_changed_lines() -> None:
    diff = patch_diff(SUITE.cases[0], apply_patch(SUITE.cases[0], LABEL_PATCH)).splitlines()
    assert diff[:2] == ["--- support.py:24#1 (app)", "+++ support.py:24#1 (patched)"]
    assert "-Answer with one label: bug, feature, question." in diff
    assert "+Answer with exactly one label: bug, feature, question." in diff
    assert "+Reply with the label only." in diff
    assert " [user]" in diff


# --- Running a patched suite ------------------------------------------------------


def fake_models() -> tuple[Runner, list[dict[str, Any]]]:
    """The new model gives a wrong label unless its system message says "label only".

    The judge passes everything, so the text case is decided by the stats alone.
    """
    seen: list[dict[str, Any]] = []

    def server(http_request: httpx.Request) -> httpx.Response:
        body = json.loads(http_request.content)
        seen.append(body)
        system = body["messages"][0]["content"]
        if system.startswith("You grade"):
            text = "PASS"
        elif body["model"] == "new" and "Ticket" in body["messages"][-1]["content"]:
            text = "bug" if "label only" in system else "feature"
        else:
            text = "bug"
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2},
            },
        )

    return Runner(transport=httpx.MockTransport(server)), seen


def run(patched: Suite | None, judge: str | None = None) -> tuple[Any, list[dict[str, Any]]]:
    runner, seen = fake_models()
    settings = Settings(old="ollama/old", new="ollama/new", runs=50, judge=judge)
    return asyncio.run(run_suite_on_models(SUITE, runner, settings, patched)), seen


def test_without_the_patch_the_label_cases_regress() -> None:
    result, _ = run(None)
    assert result.counts[Verdict.REGRESSED] == 2
    assert result.patched == 0


def test_the_patch_goes_to_the_new_model_only_and_fixes_the_cases() -> None:
    result, seen = run(apply_patches(SUITE, (LABEL_PATCH,)), judge="ollama/judge")
    verdicts = {r.case.id: r.verdict for r in result.cases}
    assert verdicts == {
        "support.py:24#1": Verdict.EQUIVALENT,
        "support.py:24#2": Verdict.EQUIVALENT,
        "support.py:30#1": Verdict.EQUIVALENT,
    }
    assert result.patched == 2
    systems = {
        (body["model"], "label only" in body["messages"][0]["content"])
        for body in seen
        if "Ticket" in body["messages"][-1]["content"] and body["model"] != "judge"
    }
    assert systems == {("old", False), ("new", True)}  # old model and reference: app's prompt
    # The judge always reads the app's own prompt.
    judged = [body for body in seen if body["model"] == "judge"]
    assert judged and not any("label only" in json.dumps(body) for body in judged)


def test_reports_say_which_cases_were_patched() -> None:
    result, _ = run(apply_patches(SUITE, (LABEL_PATCH,)))
    assert ", 2 patched for the new model:" in method_line(result)
    assert "(50 runs)  [patched]" in render_run_text(result)
    data = json.loads(render_run_json(result))
    assert data["patched"] == 2
    by_id = {case["id"]: case for case in data["cases"]}
    assert by_id["support.py:30#1"]["patched_messages"] is None
    sent = by_id["support.py:24#1"]["patched_messages"]
    assert sent[0]["content"].endswith("Reply with the label only.")
    assert by_id["support.py:24#1"]["messages"][0]["content"] == SYSTEM


def test_the_patched_suite_must_match_the_suite() -> None:
    other = Suite(SUITE.cases[:2])
    with pytest.raises(ValueError, match="same cases in the same order"):
        run(other)
