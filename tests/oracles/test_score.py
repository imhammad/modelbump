"""Tests for scoring answers against the old model's answers (ADR 0052)."""

import pytest

from modelbump.oracles import (
    OracleChoice,
    OutputKind,
    build_reference,
    find_label,
    parse_json,
    score,
)
from modelbump.oracles.score import has_json, json_type

JSON = OracleChoice(OutputKind.JSON, "test")
LABEL = OracleChoice(OutputKind.LABEL, "test", ("bug", "feature", "question"))
TEXT = OracleChoice(OutputKind.TEXT, "test")
TOOLS = OracleChoice(OutputKind.TOOLS, "test")


# --- Reading JSON ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ('{"a": 1}', {"a": 1}),
        ('Here you go:\n```json\n{"a": [1, 2]}\n```\nThanks!', {"a": [1, 2]}),
        ("Sure! [1, 2, 3] is the list.", [1, 2, 3]),
        ('Not this {broken, but {"b": true}', {"b": True}),
    ],
)
def test_parse_json_finds_the_value(text: str, value: object) -> None:
    assert parse_json(text) == value


def test_text_without_json_has_none() -> None:
    assert not has_json("No JSON here.")
    assert not has_json("{oops")
    assert has_json("[]")


@pytest.mark.parametrize(
    ("value", "name"),
    [
        (True, "boolean"),
        (1, "number"),
        (1.5, "number"),
        ("x", "string"),
        ([], "array"),
        ({}, "object"),
        (None, "null"),
    ],
)
def test_json_type(value: object, name: str) -> None:
    assert json_type(value) == name


# --- JSON answers ----------------------------------------------------------------

OLD_ORDERS = [
    '{"order_id": "A1", "items": ["pen"], "total": 3.5}',
    '```json\n{"order_id": "A1", "items": ["pen", "ink"], "total": 4}\n```',
    '{"order_id": "A1", "items": [], "total": 3.5, "note": "late"}',
]


def test_json_reference_keeps_common_keys_types_and_agreed_values() -> None:
    ref = build_reference(JSON, OLD_ORDERS)
    assert ref.answers == 3
    assert ref.json_type == "object"
    # "note" was in only one of three answers, so it is not expected.
    assert dict(ref.keys) == {"order_id": "string", "items": "array", "total": "number"}
    assert ref.fixed == (("order_id", "A1"),)


def test_json_answer_that_keeps_everything_scores_one() -> None:
    ref = build_reference(JSON, OLD_ORDERS)
    result = score(ref, 'Result: {"order_id": "A1", "items": ["cup"], "total": 9}')
    assert result.value == 1.0
    assert result.failed == ()


def test_json_answer_that_loses_a_key_or_changes_a_value() -> None:
    ref = build_reference(JSON, OLD_ORDERS)
    result = score(ref, '{"order_id": "B2", "items": "pen"}')
    assert result.failed == (
        "items is an array",
        "has total",
        "total is a number",
        "order_id same as before",
    )
    # 9 checks: valid, object, 3 keys x (has, type), 1 fixed value; 5 passed.
    assert result.value == pytest.approx(5 / 9)


def test_answer_without_json_scores_zero() -> None:
    ref = build_reference(JSON, OLD_ORDERS)
    result = score(ref, "Sorry, I could not find an order.")
    assert result.value == 0.0
    assert result.failed == ("valid JSON",)


def test_json_reference_from_answers_without_json_still_wants_json() -> None:
    ref = build_reference(JSON, ["no json", "still none"])
    assert ref.json_type is None
    assert score(ref, "[1]").value == 1.0
    assert score(ref, "none").value == 0.0


def test_json_array_reference_checks_the_type() -> None:
    ref = build_reference(JSON, ["[1, 2]", "[3]"])
    assert ref.json_type == "array"
    assert ref.keys == ()
    assert score(ref, '{"a": 1}').failed == ("is a JSON array",)


def test_one_old_answer_fixes_no_values() -> None:
    ref = build_reference(JSON, ['{"id": 1}'])
    assert ref.fixed == ()
    assert score(ref, '{"id": 2}').value == 1.0


# --- Labels ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "label"),
    [
        ("bug", "bug"),
        ("  Bug. ", "bug"),
        ("**Feature**", "feature"),
        ("The label is: question.", "question"),
        ("bug or feature, hard to say", None),
        ("debugging", None),
        ("", None),
    ],
)
def test_find_label(text: str, label: str | None) -> None:
    assert find_label(text, LABEL.labels) == label


def test_label_reference_is_the_label_most_old_answers_gave() -> None:
    ref = build_reference(LABEL, ["bug", "Bug.", "feature"])
    assert ref.label == "bug"
    assert score(ref, "bug").value == 1.0
    wrong = score(ref, "feature")
    assert wrong.value == 0.0
    assert wrong.failed == ("same label as before (bug)",)
    assert score(ref, "no idea").failed == ("one of the labels", "same label as before (bug)")


def test_label_without_a_majority_only_needs_a_valid_label() -> None:
    ref = build_reference(LABEL, ["bug", "feature"])
    assert ref.label is None
    assert score(ref, "question").value == 1.0
    assert score(ref, "maybe").value == 0.0


def test_label_majority_of_unreadable_answers_is_no_reference() -> None:
    ref = build_reference(LABEL, ["hmm", "hmm", "bug"])
    assert ref.label is None


# --- Free text -------------------------------------------------------------------


def test_text_reference_and_a_good_answer() -> None:
    old = ["- one\n- two\n- three", "- alpha\n- beta"]
    ref = build_reference(TEXT, old, prompt="Summarize in at most 10 words:\n...")
    assert ref.words == (4, 6)
    assert ref.formats == ("bullets",)
    assert ref.limit == (10, "words")
    result = score(ref, "- first\n- second")
    assert result.value == 1.0
    assert [check.name for check in result.checks] == [
        "not empty",
        "not a refusal",
        "length like before",
        "keeps bullets",
        "at most 10 words",
    ]


def test_text_answer_that_breaks_the_properties() -> None:
    ref = build_reference(TEXT, ["A short answer here."], prompt="Answer in at most 1 sentences.")
    long = "I'm sorry, I can't help with that. " * 5
    result = score(ref, long)
    assert result.failed == ("not a refusal", "length like before", "at most 1 sentences")
    assert result.value == pytest.approx(1 / 4)
    assert score(ref, "").failed == ("not empty", "length like before")


def test_refusals_are_allowed_when_the_old_model_refused_too() -> None:
    ref = build_reference(TEXT, ["I can't help with that."])
    assert ref.refusals
    assert "not a refusal" not in [c.name for c in score(ref, "I can't help with that.").checks]


def test_formats_kept_only_when_every_old_answer_had_them() -> None:
    ref = build_reference(TEXT, ["1. a\n2. b\n```x```", "1. c", "plain"])
    assert ref.formats == ()
    ref = build_reference(TEXT, ["1. a\n```py\nx\n```", "2) b ``` y ```"])
    assert ref.formats == ("code", "numbered")
    assert score(ref, "a plain answer here").failed == ("keeps code", "keeps numbered")


def test_sentence_limit_counts_sentences() -> None:
    ref = build_reference(TEXT, ["One. Two."], prompt="Answer in at most 2 sentences.")
    assert score(ref, "One. Two.").value == 1.0
    assert "at most 2 sentences" in score(ref, "One. Two. Three!").failed


# --- Errors ----------------------------------------------------------------------


def test_a_reference_needs_old_answers() -> None:
    with pytest.raises(ValueError, match="at least one old answer"):
        build_reference(TEXT, [])


def test_tool_calls_are_not_scored_yet() -> None:
    with pytest.raises(ValueError, match="not scored yet"):
        build_reference(TOOLS, ["x"])
    ref = build_reference(TEXT, ["x"])
    with pytest.raises(ValueError, match="not scored yet"):
        score(type(ref)(TOOLS, 1), "x")
