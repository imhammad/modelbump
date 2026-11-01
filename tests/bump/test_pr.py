"""Tests for the pull request description and for opening it with git and gh."""

import subprocess
from collections import Counter
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from modelbump import __version__
from modelbump.bump import (
    BumpError,
    Evidence,
    apply_plan,
    branch_name,
    check_repo,
    open_pr,
    plan_bump,
    pr_body,
    pr_title,
)
from modelbump.registry import load_registry
from tests.bump.conftest import FakeGh, git

OLD = "claude-3-haiku-20240307"
NEW = "claude-haiku-4-5-20251001"
TODAY = date(2026, 11, 1)
REPORT: dict[str, Any] = {
    "version": 1,
    "old": "ollama/qwen2.5:7b",
    "new": "ollama/qwen3:4b-instruct",
    "method": "fixed",
    "runs": 10,
    "reference": 1,
    "q": 0.05,
    "margin": 0.1,
    "judge": "ollama/gemma3:12b",
    "old_think": None,
    "new_think": "none",
    # Real reports key counts by verdict value (REGRESSED); the description counts the cases.
    "counts": {"REGRESSED": 1, "INCONCLUSIVE": 0, "EQUIVALENT": 1, "IMPROVED": 0},
    "patched": 0,
    "cases": [
        {
            "id": "support.py:24#1",
            "kind": "label",
            "verdict": "REGRESSED",
            "error": None,
            "old_mean": 1.0,
            "new_mean": 0.4,
            "new_failures": {"one label": 6, "a|b": 1},
        },
        {
            "id": "bot.py:14#1",
            "kind": "text",
            "verdict": "EQUIVALENT",
            "error": None,
            "old_mean": 1.0,
            "new_mean": 1.0,
            "new_failures": {"judge": 1},
        },
    ],
}


def plan_for(tmp_path: Path, text: str = f'MODEL = "{OLD}"\nPRICE = {{"{OLD}": 1.0}}\n') -> Any:
    (tmp_path / "app.py").write_text(text)
    return plan_bump(tmp_path, load_registry(), OLD, NEW)


def test_title_and_branch() -> None:
    assert branch_name("gpt-4o", "gpt-5.1") == "modelbump/gpt-4o-to-gpt-5.1"
    assert (
        branch_name("claude-3-5-sonnet@20240620", "anthropic.claude-v2:1")
        == "modelbump/claude-3-5-sonnet-20240620-to-anthropic.claude-v2-1"
    )
    assert branch_name("a..b", "c") == "modelbump/a.b-to-c"


def test_body_without_a_test(tmp_path: Path) -> None:
    plan = plan_for(tmp_path)
    body = pr_body(plan, None, load_registry(), TODAY)
    assert pr_title(plan) == f"Bump LLM model from {OLD} to {NEW}"
    assert body.startswith(
        f"## Bump `{OLD}` to `{NEW}`\n\n"
        f"`{OLD}` shut down on 2026-04-20: calls to it fail now. "
        f"The provider suggests `{NEW}`.\n\n"
        "### What changed\n\n"
        f"- 1 place in 1 file now uses `{NEW}`.\n\n"
        "### Check by hand\n\n"
        f"- `app.py:2` `{OLD}`: price or limit table; add the new model's row by hand.\n\n"
        "### Test\n\n"
        "No test was run for this bump."
    )
    assert body.endswith(
        f"Opened by [ModelBump](https://github.com/imhammad/modelbump) {__version__}. "
        "A person should review this change before it is merged.\n"
    )


def test_body_with_a_test_report(tmp_path: Path) -> None:
    plan = plan_for(tmp_path)
    body = pr_body(plan, Evidence(test_data=REPORT), load_registry(), TODAY)
    assert "These models stand in for the bump's models" in body
    assert "> [!WARNING]\n> 1 test case REGRESSED. Review before merging." in body
    assert (
        "| **REGRESSED** | `support.py:24#1` | label | 1.00 | 0.40 | one label (6), a\\|b (1) |"
        in body
    )
    assert "| EQUIVALENT | `bot.py:14#1` | text | 1.00 | 1.00 |  |" in body
    assert "Result: 1 regressed, 0 inconclusive, 1 equivalent, 0 improved." in body
    assert (
        "modelbump test .modelbump/suite.json --from ollama/qwen2.5:7b "
        "--to ollama/qwen3:4b-instruct --runs 10 --method fixed --reference 1 "
        "--to-think none --judge ollama/gemma3:12b\n"
    ) in body
    # Verdicts and scores only: no prompts or answers in the description.
    assert "messages" not in body
    assert (
        "ModelBump found no keys, tokens or email addresses in it. Names, street addresses "
        "and phone numbers are not looked for, so read `.modelbump/test.json` before merging."
    ) in body


def test_body_says_what_was_redacted(tmp_path: Path) -> None:
    redacted = {".modelbump/test.json": Counter({"email address": 2, "OpenAI key": 1})}
    evidence = Evidence(test_data=REPORT, redacted=redacted)
    body = pr_body(plan_for(tmp_path), evidence, load_registry(), TODAY)
    assert (
        "ModelBump replaced 1 OpenAI key, 2 email addresses with `[REDACTED:...]`. "
        "Names, street addresses"
    ) in body


def test_body_says_when_nothing_regressed_and_no_judge(tmp_path: Path) -> None:
    report = {
        **REPORT,
        "judge": None,
        "old": "openai/" + OLD,
        "new": "openai/" + NEW,
        "counts": {"equivalent": 1},
        "cases": [REPORT["cases"][1]],
    }
    body = pr_body(plan_for(tmp_path), Evidence(test_data=report), load_registry(), TODAY)
    assert "No test case regressed." in body
    assert "stand in" not in body
    assert body.count("--no-judge") == 1


def test_body_for_a_case_that_could_not_run(tmp_path: Path) -> None:
    case = {**REPORT["cases"][1], "verdict": None, "error": "timed out"}
    report = {**REPORT, "counts": {}, "cases": [case]}
    body = pr_body(plan_for(tmp_path), Evidence(test_data=report), load_registry(), TODAY)
    assert "> 1 could not be run. Review before merging." in body
    assert "| **NOT RUN** | `bot.py:14#1` | text | 1.00 | 1.00 | timed out |" in body


def test_a_long_error_is_one_short_cell(tmp_path: Path) -> None:
    error = "Traceback:\n  line 1\n" + "x" * 300
    case = {**REPORT["cases"][1], "verdict": None, "error": error}
    body = pr_body(
        plan_for(tmp_path), Evidence(test_data={**REPORT, "cases": [case]}), load_registry(), TODAY
    )
    (row,) = [line for line in body.splitlines() if "NOT RUN" in line]
    assert "| Traceback: line 1 xxx" in row
    assert row.endswith("... |")
    assert len(row) < 200


@pytest.mark.parametrize(
    ("old", "line"),
    [
        (
            "gpt-5.1",
            "`gpt-5.1` shuts down on 2027-04-01 (in 151 days). "
            "The provider suggests `gpt-6-sol`; this bump uses `gpt-9`.",
        ),
        ("gpt-4o", "`gpt-4o` has no retirement announced in the ModelBump registry."),
    ],
)
def test_why_line(tmp_path: Path, old: str, line: str) -> None:
    (tmp_path / "app.py").write_text(f'M = "{old}"\n')
    plan = plan_bump(tmp_path, load_registry(), old, "gpt-9")
    assert pr_body(plan, None, load_registry(), TODAY).splitlines()[2] == line


def test_open_pr_commits_pushes_and_switches_back(repo: Path) -> None:
    gh = FakeGh()
    plan = plan_bump(repo, load_registry(), OLD, NEW)
    branch = branch_name(OLD, NEW)
    found = check_repo(repo, branch, run=gh)
    assert found.branch == "main"
    apply_plan(repo, plan)
    url = open_pr(found, [repo / "app.py"], branch, pr_title(plan), "the body\n", run=gh)
    assert url == "https://github.com/o/r/pull/7"
    assert git(repo, "branch", "--show-current") == "main"
    assert git(repo, "status", "--porcelain") == ""
    assert git(repo, "log", "-1", "--format=%s", branch) == pr_title(plan)
    assert NEW in git(repo, "show", f"{branch}:app.py")
    assert git(repo, "ls-remote", "--heads", "origin", branch)
    create = gh.calls[-1]
    assert create[:3] == ["gh", "pr", "create"]
    assert create[create.index("--base") + 1] == "main"
    assert create[create.index("--head") + 1] == branch
    assert gh.body == "the body\n"


def test_check_repo_refuses_a_dirty_tree(repo: Path) -> None:
    (repo / "app.py").write_text("changed\n")
    with pytest.raises(BumpError, match="working tree has changes"):
        check_repo(repo, "modelbump/x", run=FakeGh())


def test_check_repo_refuses_an_existing_branch(repo: Path) -> None:
    git(repo, "branch", "modelbump/x")
    with pytest.raises(BumpError, match="already exists"):
        check_repo(repo, "modelbump/x", run=FakeGh())
    git(repo, "push", "--quiet", "origin", "modelbump/x")
    git(repo, "branch", "-D", "modelbump/x")
    with pytest.raises(BumpError, match="already on origin"):
        check_repo(repo, "modelbump/x", run=FakeGh())


def test_check_repo_needs_gh(repo: Path) -> None:
    def no_gh(args: Sequence[str], cwd: Path) -> "subprocess.CompletedProcess[str]":
        if args[0] == "gh":
            raise FileNotFoundError("gh")
        return subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, check=False)

    with pytest.raises(BumpError, match="needs the GitHub CLI"):
        check_repo(repo, "modelbump/x", run=no_gh)


def test_check_repo_needs_a_git_repository(tmp_path: Path) -> None:
    with pytest.raises(BumpError, match="git rev-parse"):
        check_repo(tmp_path, "modelbump/x", run=FakeGh())


def test_a_failed_push_switches_back_and_says_why(repo: Path) -> None:
    gh = FakeGh()
    found = check_repo(repo, "modelbump/x", run=gh)
    git(repo, "remote", "set-url", "origin", str(repo / "missing.git"))
    apply_plan(repo, plan_bump(repo, load_registry(), OLD, NEW))
    with pytest.raises(BumpError, match="git push"):
        open_pr(found, [repo / "app.py"], "modelbump/x", "t", "b", run=gh)
    assert git(repo, "branch", "--show-current") == "main"
