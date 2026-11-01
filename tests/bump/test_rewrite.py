"""Tests for planning and applying a model bump."""

from pathlib import Path

import pytest

from modelbump.bump import (
    BumpError,
    SkipReason,
    apply_plan,
    check_model_id,
    old_forms,
    plan_bump,
    plan_diff,
    skipped_lines,
)
from modelbump.registry import load_registry
from modelbump.scanner import Context

OLD = "claude-3-haiku-20240307"
NEW = "claude-haiku-4-5-20251001"

APP = f'''"""Summaries with {OLD}."""

MODEL = "{OLD}"
PRICES = {{"{OLD}": (0.25, 1.25)}}
BEDROCK = "anthropic.{OLD}-v1:0"


def summarise(client, text):
    # {OLD} is cheap.
    return client.messages.create(model="{OLD}", max_tokens=300, messages=text)
'''


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_plan_changes_uses_and_lists_what_it_leaves(tmp_path: Path) -> None:
    write(tmp_path, "app/llm.py", APP)
    plan = plan_bump(tmp_path, load_registry(), OLD, NEW)
    assert [(e.path, e.line, e.column, e.context) for e in plan.edits] == [
        ("app/llm.py", 3, 10, Context.ASSIGNMENT),
        ("app/llm.py", 10, 42, Context.CALL_ARGUMENT),
    ]
    assert [(s.finding.line, s.reason) for s in plan.skipped] == [
        (1, SkipReason.DESCRIBES),
        (4, SkipReason.TABLE),
        (5, SkipReason.PLATFORM_FORM),
        (9, SkipReason.DESCRIBES),
    ]
    after = plan.changes[0].after
    assert f'MODEL = "{NEW}"' in after
    assert f'create(model="{NEW}"' in after
    # Left alone: the docstring, the price table, Bedrock and the comment.
    assert after.count(OLD) == 4
    # Nothing is written by planning.
    assert (tmp_path / "app/llm.py").read_text() == APP


def test_include_docs_changes_comments_but_never_tables(tmp_path: Path) -> None:
    write(tmp_path, "app/llm.py", APP)
    plan = plan_bump(tmp_path, load_registry(), OLD, NEW, include_docs=True)
    assert len(plan.edits) == 4
    assert [s.reason for s in plan.skipped] == [SkipReason.TABLE, SkipReason.PLATFORM_FORM]


def test_apply_writes_files_and_keeps_line_endings(tmp_path: Path) -> None:
    env = tmp_path / ".env.example"
    env.write_bytes(f"SUMMARY_MODEL={OLD}\r\nOTHER=gpt-4o\r\n".encode())
    plan = plan_bump(tmp_path, load_registry(), OLD, NEW)
    apply_plan(tmp_path, plan)
    assert env.read_bytes() == f"SUMMARY_MODEL={NEW}\r\nOTHER=gpt-4o\r\n".encode()


def test_several_ids_on_one_line_are_all_changed(tmp_path: Path) -> None:
    write(tmp_path, "a.py", f'PAIR = ["{OLD}", "gpt-4o", "{OLD}"]\n')
    plan = plan_bump(tmp_path, load_registry(), OLD, NEW)
    assert plan.changes[0].after == f'PAIR = ["{NEW}", "gpt-4o", "{NEW}"]\n'


def test_aliases_count_as_the_old_model(tmp_path: Path) -> None:
    write(tmp_path, "a.py", 'A = "gpt-3.5-turbo"\nB = "gpt-3.5-turbo-0125"\n')
    assert old_forms("gpt-3.5-turbo", load_registry()) == {
        "gpt-3.5-turbo",
        "gpt-3.5-turbo-0125",
    }
    plan = plan_bump(tmp_path, load_registry(), "gpt-3.5-turbo", "gpt-5.1")
    assert plan.changes[0].after == 'A = "gpt-5.1"\nB = "gpt-5.1"\n'


def test_a_prefix_such_as_openai_slash_is_kept(tmp_path: Path) -> None:
    write(tmp_path, "a.py", 'M = "openai/gpt-4o"\n')
    plan = plan_bump(tmp_path, load_registry(), "gpt-4o", "gpt-5.1")
    assert plan.changes[0].after == 'M = "openai/gpt-5.1"\n'


def test_a_model_not_in_the_registry_is_matched_exactly(tmp_path: Path) -> None:
    write(tmp_path, "a.py", 'A = "gpt-4o"\nB = "gpt-4o-mini"\n')
    plan = plan_bump(tmp_path, load_registry(), "gpt-4o", "gpt-5.1")
    assert plan.changes[0].after == 'A = "gpt-5.1"\nB = "gpt-4o-mini"\n'


def test_a_single_file_can_be_bumped(tmp_path: Path) -> None:
    path = write(tmp_path, "app.py", f'MODEL = "{OLD}"\n')
    plan = plan_bump(path, load_registry(), OLD, NEW)
    apply_plan(path, plan)
    assert path.read_text() == f'MODEL = "{NEW}"\n'


def test_a_file_that_is_not_utf8_is_left_alone(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_bytes(f'MODEL = "{OLD}"  # caf\xe9\n'.encode("latin-1"))
    plan = plan_bump(tmp_path, load_registry(), OLD, NEW)
    assert plan.changes == ()
    assert [s.reason for s in plan.skipped] == [SkipReason.NOT_UTF8]


def test_apply_refuses_a_file_changed_since_the_plan(tmp_path: Path) -> None:
    path = write(tmp_path, "a.py", f'MODEL = "{OLD}"\n')
    plan = plan_bump(tmp_path, load_registry(), OLD, NEW)
    path.write_text(f'MODEL = "{OLD}"  # edited\n')
    with pytest.raises(BumpError, match="changed since"):
        apply_plan(tmp_path, plan)
    assert path.read_text() == f'MODEL = "{OLD}"  # edited\n'


@pytest.mark.parametrize("bad", ['gpt-5"; import os', "gpt 5", "", "-rf"])
def test_new_ids_that_are_not_model_ids_are_refused(bad: str) -> None:
    with pytest.raises(BumpError, match="does not look like a model ID"):
        check_model_id(bad)


def test_the_new_model_cannot_be_the_old_one(tmp_path: Path) -> None:
    with pytest.raises(BumpError, match="same model"):
        plan_bump(tmp_path, load_registry(), "gpt-3.5-turbo", "gpt-3.5-turbo-0125")


def test_diff_and_skipped_lines(tmp_path: Path) -> None:
    write(tmp_path, "a.py", f'MODEL = "{OLD}"\n# {OLD}\n')
    plan = plan_bump(tmp_path, load_registry(), OLD, NEW)
    assert plan_diff(plan) == (
        f'--- a/a.py\n+++ b/a.py\n@@ -1,2 +1,2 @@\n-MODEL = "{OLD}"\n+MODEL = "{NEW}"\n # {OLD}\n'
    )
    assert skipped_lines(plan) == [
        f"  a.py:2:3  {OLD}  (comment, docstring or sentence; --include-docs changes these too)"
    ]
