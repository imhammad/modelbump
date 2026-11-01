"""Tests for writing accepted prompt repairs back into Python source."""

import ast

import pytest

from modelbump.bump.prompts import Literal, apply_repair, literals, plan_repair, render
from modelbump.repair import PromptPatch
from modelbump.repair.patch import Edit
from modelbump.suite import Suite
from modelbump.suite.file import SuiteCase
from tests.suite.test_run import LABELS


def case(path: str, line: int, system: str | None, user: str = "Hi") -> SuiteCase:
    messages = ((("system", system),) if system is not None else ()) + (("user", user),)
    return SuiteCase(
        id=f"{path}:{line}#1",
        path=path,
        line=line,
        api="openai.chat",
        app_model="gpt-4o",
        oracle=LABELS,
        source="test",
        generated_by=None,
        messages=messages,
    )


def sources(files: dict[str, str]) -> dict[str, list[Literal]]:
    return {path: literals(path, text) for path, text in files.items()}


def test_literals_skip_fstrings_and_bytes() -> None:
    text = 'A = "plain"\nB = f"x {A} y"\nC = b"bytes"\nD = """multi\nline"""\n'
    assert [lit.value for lit in literals("a.py", text)] == ["plain", "multi\nline"]


def test_literal_offsets_count_characters_not_bytes() -> None:
    text = 'A = "café"; B = "after"\n'
    lits = literals("a.py", text)
    assert [text[lit.start : lit.end] for lit in lits] == ['"café"', '"after"']


def test_literal_offsets_with_crlf_lines() -> None:
    text = 'A = 1\r\nB = "two"\r\n'
    (lit,) = literals("a.py", text)
    assert text[lit.start : lit.end] == '"two"'


def test_a_file_that_does_not_parse_has_no_literals() -> None:
    assert literals("a.py", 'print "hi"\n') == []


def test_add_system_appends_to_the_one_system_literal() -> None:
    files = {"app.py": 'SYSTEM = "You sort tickets."\n'}
    suite = Suite((case("app.py", 9, "You sort tickets."),))
    patch = PromptPatch("app.py:9", add_system="Reply with the label only.")
    repair = plan_repair(patch, suite, sources(files))
    assert repair.reason is None
    after = apply_repair(files["app.py"], "app.py", repair)
    assert after == 'SYSTEM = "You sort tickets.\\n\\nReply with the label only."\n'
    namespace: dict[str, object] = {}
    exec(compile(after, "app.py", "exec"), namespace)
    assert namespace["SYSTEM"] == "You sort tickets.\n\nReply with the label only."


def test_triple_quoted_prompts_keep_their_style() -> None:
    files = {"app.py": 'SYSTEM = """You sort tickets.\nBe brief.\n"""\n'}
    suite = Suite((case("app.py", 9, "You sort tickets.\nBe brief.\n"),))
    patch = PromptPatch("app.py:9", add_system="No lists.")
    after = apply_repair(files["app.py"], "app.py", plan_repair(patch, suite, sources(files)))
    assert after == 'SYSTEM = """You sort tickets.\nBe brief.\n\nNo lists."""\n'


def test_edits_change_the_literal_in_another_file() -> None:
    files = {
        "app.py": "from prompts import SYSTEM\n",
        "prompts.py": 'SYSTEM = "Answer from the FAQ. If unsure, say so."\n',
    }
    suite = Suite((case("app.py", 4, "Answer from the FAQ. If unsure, say so."),))
    patch = PromptPatch("app.py:4", edits=(Edit("If unsure, say so.", "Never guess."),))
    repair = plan_repair(patch, suite, sources(files))
    assert [lit.path for lit, _ in repair.replacements] == ["prompts.py"]
    after = apply_repair(files["prompts.py"], "prompts.py", repair)
    assert after == 'SYSTEM = "Answer from the FAQ. Never guess."\n'


def test_an_edit_and_add_system_on_the_same_literal() -> None:
    files = {"app.py": 'SYSTEM = "Be kind. Be brief."\n'}
    suite = Suite((case("app.py", 2, "Be kind. Be brief."),))
    patch = PromptPatch(
        "app.py:2", edits=(Edit("Be brief.", "Be very brief."),), add_system="No lists."
    )
    after = apply_repair(files["app.py"], "app.py", plan_repair(patch, suite, sources(files)))
    assert ast.literal_eval(after.split(" = ", 1)[1]) == "Be kind. Be very brief.\n\nNo lists."


@pytest.mark.parametrize(
    ("files", "patch", "reason"),
    [
        (
            {"a.py": 'X = "one"\n'},
            PromptPatch("a.py:1", edits=(Edit("two", "2"),)),
            "the text to replace is in no string literal",
        ),
        (
            {"a.py": 'X = "one one"\n'},
            PromptPatch("a.py:1", edits=(Edit("one", "1"),)),
            "the text to replace is 2 times in the code",
        ),
        (
            {"a.py": 'X = f"one {y}"\n'},
            PromptPatch("a.py:1", edits=(Edit("one", "1"),)),
            "the text to replace is in no string literal",
        ),
        (
            {"a.py": 'X = "Hi"\n'},
            PromptPatch("a.py:1", add_system="Be brief."),
            "the call has no system message to add to",
        ),
    ],
)
def test_uncertain_places_are_left_for_a_person(
    files: dict[str, str], patch: PromptPatch, reason: str
) -> None:
    suite = Suite((case("a.py", 1, None),))
    assert plan_repair(patch, suite, sources(files)).reason == reason


def test_a_system_message_built_at_runtime_is_left_for_a_person() -> None:
    files = {"a.py": 'S = "You sort {kind}.".format(kind="tickets")\n'}
    suite = Suite((case("a.py", 1, "You sort tickets."),))
    repair = plan_repair(PromptPatch("a.py:1", add_system="Be brief."), suite, sources(files))
    assert repair.reason == "the system message is built at runtime"


def test_a_system_message_written_twice_is_left_for_a_person() -> None:
    files = {"a.py": 'S = "Be kind."\nT = "Be kind."\n'}
    suite = Suite((case("a.py", 1, "Be kind."),))
    repair = plan_repair(PromptPatch("a.py:1", add_system="Be brief."), suite, sources(files))
    assert repair.reason == "the system message is written in more than one place"


@pytest.mark.parametrize(
    ("source", "value", "expected"),
    [
        ('"a"', "b c", '"b c"'),
        ("'a'", "b c", "'b c'"),
        ('"a"', 'say "hi"', '"say \\"hi\\""'),
        ('"a"', "two\nlines", '"two\\nlines"'),
        ('"""a"""', "two\nlines", '"""two\nlines"""'),
        ('"""a"""', 'ends with "', '"ends with \\""'),
        ('r"a"', "b", '"b"'),
        ('"a" "b"', "ab!", '"ab!"'),
    ],
)
def test_render(source: str, value: str, expected: str) -> None:
    lit = Literal("a.py", 0, len(source), "x", source)
    assert render(lit, value) == expected
    assert ast.literal_eval(expected) == value


def test_apply_refuses_a_literal_that_changed() -> None:
    files = {"a.py": 'S = "Be kind."\n'}
    suite = Suite((case("a.py", 1, "Be kind."),))
    repair = plan_repair(PromptPatch("a.py:1", add_system="Be brief."), suite, sources(files))
    with pytest.raises(ValueError, match="changed while it was read"):
        apply_repair('S = "Be nice."\n', "a.py", repair)
