"""Tests for the LLM judge of free-text answers (ADR 0054)."""

import pytest

from modelbump.oracles import OracleChoice, OutputKind, build_reference, score
from modelbump.oracles.judge import (
    DEFAULT_JUDGE,
    JUDGE_CHECK,
    judge_request,
    parse_verdict,
    with_judge,
)

TEXT = OracleChoice(OutputKind.TEXT, "test")


def test_judge_request_shows_prompt_reference_and_answer() -> None:
    request = judge_request(
        (("system", "Be brief."), ("user", "Summarize: x")), "Ref answer.", "New answer."
    )
    assert request.model == DEFAULT_JUDGE
    assert (request.temperature, request.seed, request.max_tokens) == (0.0, 0, 8)
    system, user = request.messages
    assert system.role == "system"
    assert "Reply with one word: PASS or FAIL." in system.content
    assert user.content == (
        "## The app's prompt\n[system]\nBe brief.\n\n[user]\nSummarize: x\n\n"
        "## Reference answer\nRef answer.\n\n"
        "## Candidate answer\nNew answer.\n\n"
        "Does the candidate PASS or FAIL?"
    )
    pinned = judge_request((("user", "q"),), "r", "a", "ollama/j", "digest")
    assert (pinned.model, pinned.model_version) == ("ollama/j", "digest")


@pytest.mark.parametrize(
    ("reply", "verdict"),
    [
        ("PASS", True),
        ("fail", False),
        ("**PASS**.", True),
        ("Verdict: FAIL", False),
        ("PASS or FAIL?", None),
        ("It is fine.", None),
        ("PASSING", None),
    ],
)
def test_parse_verdict(reply: str, verdict: bool | None) -> None:
    assert parse_verdict(reply) is verdict


def test_the_judge_sets_a_text_score() -> None:
    reference = build_reference(TEXT, ["A good short answer."])
    properties = score(reference, "Another short answer.")
    assert properties.value == 1.0
    failed = with_judge(properties, False)
    assert failed.value == 0.0
    assert failed.failed == (JUDGE_CHECK,)
    # A long answer fails "length like before", but the judge decides the score.
    long = score(reference, "word " * 50)
    assert long.value < 1.0
    passed = with_judge(long, True)
    assert passed.value == 1.0
    assert passed.failed == ("length like before",)


def test_empty_answers_and_refusals_score_zero_even_if_the_judge_passes_them() -> None:
    reference = build_reference(TEXT, ["A good short answer."])
    assert with_judge(score(reference, ""), True).value == 0.0
    assert with_judge(score(reference, "I'm sorry, I can't help with that."), True).value == 0.0


def test_unclear_verdict_keeps_the_property_score() -> None:
    reference = build_reference(TEXT, ["A good short answer."])
    properties = score(reference, "word " * 50)
    unclear = with_judge(properties, None)
    assert unclear.value == properties.value
    assert unclear.failed[-1] == "judge: no clear verdict"
