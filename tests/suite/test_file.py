"""Tests for the suite file (ADR 0053)."""

import json
from pathlib import Path

import pytest

from modelbump.oracles import OutputKind
from modelbump.suite import build_suite, read_suite, suite_to_json
from modelbump.synth.cases import find_cases

DEMO = Path(__file__).parents[1] / "fixtures" / "prompt-demo"


def write(tmp_path: Path, data: object) -> Path:
    path = tmp_path / "suite.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_demo_suite_has_each_complete_case_with_its_oracle() -> None:
    suite = build_suite(find_cases(DEMO))
    assert [case.id for case in suite.cases] == [
        "bot.py:14#1",
        "support.py:24#1",
        "support.py:24#2",
        "support.py:24#3",
        "support.py:30#1",
    ]
    label = suite.cases[1]
    assert label.oracle.kind is OutputKind.LABEL
    assert label.oracle.labels == ("bug", "feature", "question")
    assert label.messages[-1] == ("user", "Ticket:\nThe app crashes when I log in.")
    assert label.source == "tests/test_support.py:16"
    assert label.app_model == "gpt-4o-mini"
    assert "at most 2 sentences" in suite.cases[0].prompt
    assert suite.left_out == (
        ("extract.py:9", "no complete test case"),
        ("support.py:39", "no complete test case"),
    )


def test_suite_file_round_trip(tmp_path: Path) -> None:
    suite = build_suite(find_cases(DEMO))
    path = tmp_path / "suite.json"
    path.write_text(suite_to_json(suite), encoding="utf-8")
    assert read_suite(path) == suite
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert data["cases"][1]["oracle"]["kind"] == "label"
    assert data["left_out"][0] == {"call": "extract.py:9", "reason": "no complete test case"}


def test_tool_calls_and_calls_without_prompts_are_left_out(tmp_path: Path) -> None:
    (tmp_path / "agent.py").write_text(
        'client.chat.completions.create(model="m", messages=[{"role": "user", "content": "hi"}],'
        " tools=TOOLS)\n"
        'client.chat.completions.create(model="m")\n',
        encoding="utf-8",
    )
    suite = build_suite(find_cases(tmp_path))
    assert suite.cases == ()
    assert suite.left_out == (
        ("agent.py:1", "tool calls are not scored yet"),
        ("agent.py:2", "no prompt argument"),
    )


def case(**changes: object) -> dict[str, object]:
    item: dict[str, object] = {
        "id": "a.py:1#1",
        "path": "a.py",
        "line": 1,
        "api": "openai_chat",
        "oracle": {"kind": "text", "reason": "r", "labels": []},
        "messages": [{"role": "user", "content": "hi"}],
    }
    item.update(changes)
    return item


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"version": 2, "cases": []}, "not a version 1 suite file"),
        ([], "not a version 1 suite file"),
        ({"version": 1, "cases": [{"id": "x"}]}, "missing a field"),
        ({"version": 1, "cases": [case(), case()]}, "two cases share an id"),
        ({"version": 1, "cases": [case(messages=[])]}, "no messages"),
        (
            {"version": 1, "cases": [case(oracle={"kind": "tools"})]},
            "tool calls are not scored yet",
        ),
        (
            {"version": 1, "cases": [case(oracle={"kind": "label", "labels": ["a"]})]},
            "needs at least two labels",
        ),
    ],
)
def test_bad_suite_files_say_what_is_wrong(tmp_path: Path, data: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        read_suite(write(tmp_path, data))


def test_suite_file_that_is_not_json(tmp_path: Path) -> None:
    path = tmp_path / "suite.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        read_suite(path)


def test_hand_written_case_with_defaults(tmp_path: Path) -> None:
    suite = read_suite(write(tmp_path, {"version": 1, "cases": [case()]}))
    (only,) = suite.cases
    assert only.source == ""
    assert only.generated_by is None
    assert only.app_model is None
    assert suite.left_out == ()


def test_a_fixed_prompt_is_its_own_case(tmp_path: Path) -> None:
    (tmp_path / "poet.py").write_text(
        "from openai import OpenAI\n\n"
        "OpenAI().chat.completions.create(\n"
        '    model="gpt-4", messages=[{"role": "user", "content": "Write a haiku about rain."}]\n'
        ")\n"
    )
    suite = build_suite(find_cases(tmp_path))
    (only,) = suite.cases
    assert only.id == "poet.py:3#1"
    assert only.source == "fixed prompt in the code"
    assert only.generated_by is None
    assert only.messages == (("user", "Write a haiku about rain."),)
    assert suite.left_out == ()
