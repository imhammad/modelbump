"""Tests for moving hard-coded model IDs to an environment variable."""

import ast
from pathlib import Path

import pytest

from modelbump.bump import BumpError, apply_plan, plan_bump, plan_diff, suggested_env_name
from modelbump.bump.config import check_env_name, env_file_text, import_position
from modelbump.registry import load_registry

OLD = "claude-3-haiku-20240307"
NEW = "claude-haiku-4-5-20251001"
LOOKUP = f'os.environ.get("ANTHROPIC_MODEL", "{NEW}")'


def bump(root: Path, text: str, env: str | None = "ANTHROPIC_MODEL") -> str:
    (root / "app.py").write_text(text)
    plan = plan_bump(root, load_registry(), OLD, NEW, env=env)
    return plan.changes[0].after


def test_call_arguments_names_and_dict_values_read_the_variable(tmp_path: Path) -> None:
    after = bump(
        tmp_path,
        "import anthropic\n\n"
        f'MODEL = "{OLD}"\n'
        f"reply = client.messages.create(model='{OLD}')\n"
        f'payload = {{"model": "{OLD}"}}\n'
        f'def ask(model="{OLD}"): ...\n',
    )
    assert after == (
        "import os\nimport anthropic\n\n"
        f"MODEL = {LOOKUP}\n"
        f"reply = client.messages.create(model={LOOKUP})\n"
        f'payload = {{"model": {LOOKUP}}}\n'
        f"def ask(model={LOOKUP}): ...\n"
    )
    ast.parse(after)


def test_places_that_cannot_move_only_get_the_new_id(tmp_path: Path) -> None:
    after = bump(
        tmp_path,
        "import os\n"
        f'A = os.getenv("X", "{OLD}")\n'
        f'B = f"{OLD}"\n'
        f'C = "anthropic/{OLD}"\n'
        f'D = ["{OLD}"]\n'
        f'E = "{OLD}" "-x"\n',
    )
    assert after == (
        "import os\n"
        f'A = os.getenv("X", "{NEW}")\n'
        f'B = f"{NEW}"\n'
        f'C = "anthropic/{NEW}"\n'
        f'D = ["{NEW}"]\n'
        f'E = "{NEW}" "-x"\n'
    )


def test_only_python_files_are_moved(tmp_path: Path) -> None:
    (tmp_path / "app.ts").write_text(f'const model = "{OLD}";\n')
    plan = plan_bump(tmp_path, load_registry(), OLD, NEW, env="ANTHROPIC_MODEL")
    assert [c.after for c in plan.changes] == [f'const model = "{NEW}";\n']
    assert plan.moved == 0


def test_a_file_that_does_not_parse_keeps_its_literals(tmp_path: Path) -> None:
    after = bump(tmp_path, f'print "hi"\nMODEL = "{OLD}"\n')
    assert after == f'print "hi"\nMODEL = "{NEW}"\n'


def test_without_env_the_plan_counts_what_could_move(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(f'MODEL = "{OLD}"\nX = ["{OLD}"]\n')
    plan = plan_bump(tmp_path, load_registry(), OLD, NEW)
    assert (plan.movable, plan.moved) == (1, 0)
    assert plan.changes[0].after == f'MODEL = "{NEW}"\nX = ["{NEW}"]\n'


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("import json\nX = 1\n", 0),
        ('"""Doc."""\nX = 1\n', 11),
        ('"""Doc."""\nfrom __future__ import annotations\nX = 1\n', 46),
        ('"""Doc."""\nfrom __future__ import annotations\n\nimport json\n', 47),
        ("#!/usr/bin/env python\n# hi\nX = 1\n", 27),
        ("#!/usr/bin/env python\n@dec\ndef f(): ...\n", 22),
        ("", 0),
    ],
)
def test_import_position(text: str, expected: int) -> None:
    assert import_position(text) == expected


@pytest.mark.parametrize("text", ["import os\n", "import os.path\n", "import sys, os\n"])
def test_import_position_is_none_when_os_is_imported(text: str) -> None:
    assert import_position(text) is None


def test_import_os_as_another_name_still_adds_import_os() -> None:
    assert import_position("import os as system\n") == 0


def test_env_example_gets_the_variable(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_bytes(b"ANTHROPIC_API_KEY=\r\n")
    (tmp_path / "app.py").write_text(f'MODEL = "{OLD}"\n')
    plan = plan_bump(tmp_path, load_registry(), OLD, NEW, env="ANTHROPIC_MODEL")
    apply_plan(tmp_path, plan)
    assert (tmp_path / ".env.example").read_bytes() == (
        f"ANTHROPIC_API_KEY=\r\nANTHROPIC_MODEL={NEW}\r\n".encode()
    )


def test_env_example_is_created_when_missing(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(f'MODEL = "{OLD}"\n')
    plan = plan_bump(tmp_path, load_registry(), OLD, NEW, env="ANTHROPIC_MODEL")
    assert "--- /dev/null\n+++ b/.env.example\n" in plan_diff(plan)
    apply_plan(tmp_path, plan)
    assert (tmp_path / ".env.example").read_text() == f"ANTHROPIC_MODEL={NEW}\n"


def test_env_example_that_sets_the_variable_is_only_bumped(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text(f"ANTHROPIC_MODEL={OLD}\n")
    (tmp_path / "app.py").write_text(f'MODEL = "{OLD}"\n')
    plan = plan_bump(tmp_path, load_registry(), OLD, NEW, env="ANTHROPIC_MODEL")
    env_change = next(c for c in plan.changes if c.path == ".env.example")
    assert env_change.after == f"ANTHROPIC_MODEL={NEW}\n"


def test_a_single_file_bump_creates_no_env_example(tmp_path: Path) -> None:
    path = tmp_path / "app.py"
    path.write_text(f'MODEL = "{OLD}"\n')
    plan = plan_bump(path, load_registry(), OLD, NEW, env="ANTHROPIC_MODEL")
    assert [c.path for c in plan.changes] == ["app.py"]


def test_apply_refuses_an_env_example_that_appeared(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(f'MODEL = "{OLD}"\n')
    plan = plan_bump(tmp_path, load_registry(), OLD, NEW, env="ANTHROPIC_MODEL")
    (tmp_path / ".env.example").write_text("X=1\n")
    with pytest.raises(BumpError, match="appeared since"):
        apply_plan(tmp_path, plan)


def test_env_file_text() -> None:
    assert env_file_text(None, "M", "x") == "M=x\n"
    assert env_file_text("A=1", "M", "x") == "A=1\nM=x\n"
    assert env_file_text("export M=y\n", "M", "x") is None
    assert env_file_text("MM=y\n", "M", "x") == "MM=y\nM=x\n"


@pytest.mark.parametrize("bad", ["openai_model", "1MODEL", "MODEL-NAME", "M; rm"])
def test_bad_env_names_are_refused(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValueError, match="not an environment variable name"):
        check_env_name(bad)
    with pytest.raises(BumpError, match="not an environment variable name"):
        plan_bump(tmp_path, load_registry(), OLD, NEW, env=bad)


def test_suggested_env_name_follows_the_provider() -> None:
    registry = load_registry()
    assert suggested_env_name(OLD, registry) == "ANTHROPIC_MODEL"
    assert suggested_env_name("gpt-3.5-turbo", registry) == "OPENAI_MODEL"
    assert suggested_env_name("gemini-2.0-flash", registry) == "GEMINI_MODEL"
    assert suggested_env_name("my-model-1", registry) == "LLM_MODEL"


def test_env_example_with_the_old_model_under_another_key_gets_both(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text(f"SUMMARY_MODEL={OLD}\n")
    (tmp_path / "app.py").write_text(f'MODEL = "{OLD}"\n')
    plan = plan_bump(tmp_path, load_registry(), OLD, NEW, env="ANTHROPIC_MODEL")
    env_change = next(c for c in plan.changes if c.path == ".env.example")
    assert env_change.after == f"SUMMARY_MODEL={NEW}\nANTHROPIC_MODEL={NEW}\n"
