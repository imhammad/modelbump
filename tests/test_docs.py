"""Tests that keep the user guide true to the code (ADR 0074)."""

import importlib
import re
from pathlib import Path

from modelbump.cli_reference import commands, render

ROOT = Path(__file__).parent.parent
GUIDE = ROOT / "docs" / "guide"


def test_command_reference_is_up_to_date() -> None:
    # If this fails, run: uv run python -m modelbump.cli_reference > docs/guide/cli.md
    assert (GUIDE / "cli.md").read_text(encoding="utf-8") == render()


def test_command_reference_has_every_command_and_option() -> None:
    page = render()
    names = [name for name, _ in commands()]
    assert "modelbump bump" in names
    assert "modelbump repair run" in names
    for name, command in commands():
        assert f"\n## {name}\n" in page
        for param in command.params:
            for opt in param.opts:
                if opt.startswith("-"):
                    assert f"`{opt}`" in page, (name, opt)


def test_stable_python_names_exist_and_are_exported() -> None:
    page = (GUIDE / "python-api.md").read_text(encoding="utf-8")
    names = re.findall(r"^\| `(modelbump\.[a-z_.]+)\.([A-Za-z_]+)` \|", page, re.MULTILINE)
    assert len(names) >= 20
    for module_name, name in names:
        module = importlib.import_module(module_name)
        assert name in module.__all__, f"{module_name}.{name}"


def test_docs_pin_the_action_to_the_major_version() -> None:
    pages = [ROOT / "README.md", ROOT / "action.yml", *sorted((ROOT / "docs").rglob("*.md"))]
    for page in pages:
        if "/adr/" in page.as_posix():
            continue  # decision records keep the text of their day
        for pin in re.findall(r"imhammad/modelbump@([\w.-]*\w)", page.read_text(encoding="utf-8")):
            assert pin == "v1", f"{page.relative_to(ROOT)} pins @{pin}"
