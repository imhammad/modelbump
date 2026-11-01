"""Tests for the evidence a bump adds, and for repairs written into the code."""

import json
import shutil
from pathlib import Path

import pytest

from modelbump.bump import apply_plan, load_evidence, plan_bump, plan_diff
from modelbump.registry import load_registry
from modelbump.scanner import scan_path
from modelbump.suite import build_suite, suite_to_json
from modelbump.synth.cases import find_cases

DEMO = Path(__file__).parent.parent / "fixtures" / "prompt-demo"
REPORT = {"version": 1, "old": "ollama/qwen2.5:7b", "new": "ollama/qwen3:4b", "cases": []}
FIRST = {"call": "support.py:30", "edits": [], "add_system": "No numbered lists.", "note": ""}
PATCHES = {
    "version": 1,
    "patches": [
        {"call": "support.py:30", "edits": [], "add_system": "No numbered lists.", "note": ""},
        {
            "call": "bot.py:14",
            "edits": [{"find": "If unsure, say you don't know.", "replace": "Never guess."}],
            "add_system": "",
            "note": "",
        },
        {"call": "support.py:24", "edits": [], "add_system": "Label only.", "note": ""},
    ],
}


def demo(tmp_path: Path) -> tuple[Path, Path]:
    """A copy of the demo app, and its suite file outside it."""
    app = tmp_path / "app"
    shutil.copytree(DEMO, app)
    suite = build_suite(find_cases(app))
    suite_file = tmp_path / "suite.json"
    suite_file.write_text(suite_to_json(suite))
    return app, suite_file


def write_json(path: Path, data: object) -> Path:
    path.write_text(json.dumps(data))
    return path


def test_patch_is_written_into_the_code_where_it_is_certain(tmp_path: Path) -> None:
    app, suite_file = demo(tmp_path)
    evidence = load_evidence(
        suite_file,
        write_json(tmp_path / "test.json", REPORT),
        patch_file=write_json(tmp_path / "fix.json", PATCHES),
    )
    plan = plan_bump(app, load_registry(), "gpt-4o-mini", "gpt-6-sol", evidence=evidence)
    assert plan.repaired == ("support.py:30", "bot.py:14")
    assert plan.by_hand == (("support.py:24", "the system message is built at runtime"),)
    assert plan.tested == ("ollama/qwen2.5:7b", "ollama/qwen3:4b")
    diff = plan_diff(plan)
    assert '+        system="You write short, factual summaries.\\n\\nNo numbered lists.",' in diff
    assert '+FAQ_SYSTEM = "Answer questions about our product from the FAQ. Never guess."' in diff
    assert ".modelbump" not in diff  # evidence is listed, not shown

    apply_plan(app, plan)
    assert sorted(p.name for p in (app / ".modelbump").iterdir()) == [
        "repairs.json",
        "suite.json",
        "test.json",
    ]
    assert json.loads((app / ".modelbump/test.json").read_text()) == REPORT
    # The repaired app gives the repaired prompts, as tested.
    repaired = build_suite(find_cases(app))
    systems = {c.id: dict(c.messages).get("system") for c in repaired.cases}
    assert systems["support.py:30#1"] == "You write short, factual summaries.\n\nNo numbered lists."
    assert systems["bot.py:14#1"] == "Answer questions about our product from the FAQ. Never guess."


def test_evidence_folder_is_not_scanned(tmp_path: Path) -> None:
    app, suite_file = demo(tmp_path)
    plan = plan_bump(
        app, load_registry(), "gpt-4o-mini", "gpt-6-sol", evidence=load_evidence(suite_file)
    )
    apply_plan(app, plan)
    found = scan_path(app, load_registry()).findings
    assert not any(f.path.startswith(".modelbump/") for f in found)


def test_unchanged_evidence_is_not_rewritten_and_changed_is_updated(tmp_path: Path) -> None:
    app, suite_file = demo(tmp_path)
    evidence = load_evidence(suite_file)
    apply_plan(app, plan_bump(app, load_registry(), "gpt-4o-mini", "gpt-6-sol", evidence=evidence))
    again = plan_bump(app, load_registry(), "gpt-6-sol", "gpt-7", evidence=evidence)
    assert not any(c.evidence for c in again.changes)
    report = load_evidence(suite_file, write_json(tmp_path / "t.json", REPORT))
    third = plan_bump(app, load_registry(), "gpt-6-sol", "gpt-7", evidence=report)
    assert [(c.path, c.created) for c in third.changes if c.evidence] == [
        (".modelbump/test.json", True)
    ]


def test_accepted_repairs_come_from_the_repair_report(tmp_path: Path) -> None:
    _, suite_file = demo(tmp_path)
    proposals = tmp_path / "proposals"
    proposals.mkdir()
    write_json(proposals / "support-py-30.01.json", {"version": 1, "patches": [FIRST]})
    report = {
        "version": 1,
        "calls": [
            {"call": "support.py:30", "accepted": "support-py-30.01.json"},
            {"call": "bot.py:14", "accepted": None},
        ],
    }
    evidence = load_evidence(
        suite_file,
        repair_file=write_json(tmp_path / "repair.json", report),
        proposals=proposals,
    )
    assert [p.call for p in evidence.accepted] == ["support.py:30"]
    assert set(evidence.files()) == {
        ".modelbump/suite.json",
        ".modelbump/repair.json",
        ".modelbump/repairs.json",
    }


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"test_file": "test.json"}, "need --suite"),
        ({"suite_file": "suite.json", "repair_file": "repair.json"}, "needs --proposals"),
        (
            {"suite_file": "suite.json", "repair_file": "repair.json", "patch_file": "fix.json"},
            "not both",
        ),
        ({"suite_file": "suite.json", "test_file": "bad.json"}, "is not a JSON report"),
        ({"suite_file": "suite.json", "test_file": "broken.json"}, "is not valid JSON"),
        ({"suite_file": "suite.json", "patch_file": "other.json"}, "does not fit the suite"),
        (
            {"suite_file": "suite.json", "repair_file": "repair.json", "proposals": "props"},
            "has no such file",
        ),
        (
            {"suite_file": "suite.json", "repair_file": "bad.json", "proposals": "props"},
            "is not a JSON report from `modelbump repair run`",
        ),
    ],
)
def test_bad_evidence_says_what_is_wrong(
    tmp_path: Path, kwargs: dict[str, str], message: str
) -> None:
    demo(tmp_path)
    write_json(tmp_path / "test.json", REPORT)
    write_json(tmp_path / "bad.json", {"version": 2})
    (tmp_path / "broken.json").write_text("{")
    write_json(tmp_path / "fix.json", PATCHES)
    other = {"version": 1, "patches": [{"call": "nope.py:1", "add_system": "x"}]}
    write_json(tmp_path / "other.json", other)
    report = {"version": 1, "calls": [{"call": "support.py:30", "accepted": "missing.json"}]}
    write_json(tmp_path / "repair.json", report)
    (tmp_path / "props").mkdir()
    paths = {key: tmp_path / value for key, value in kwargs.items()}
    with pytest.raises(ValueError, match=message):
        load_evidence(**paths)
