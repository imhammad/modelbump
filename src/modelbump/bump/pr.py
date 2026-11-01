"""The bump's pull request: its description, and opening it with git and gh (ADR 0071).

The description is the evidence report. It says why the model changes (the
registry), what changed and what a person must check, and what the test
found, case by case, with the command that reproduces it. It holds verdicts
and scores only: the prompts and answers stay in ``.modelbump/test.json``,
where they are reviewed like any other file in the change.

Opening the pull request runs plain ``git`` and ``gh`` commands, with
argument lists and no shell, in this order: check the working tree is clean
and the branch is new, write the files, commit them on a new branch, push,
``gh pr create``, and switch back to the branch the developer was on.
"""

import re
import subprocess
import tempfile
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from modelbump import __version__
from modelbump.bump.evidence import EVIDENCE_DIR, Evidence
from modelbump.bump.rewrite import SKIP_HINTS, BumpError, BumpPlan
from modelbump.registry import Registry
from modelbump.scanner import Severity, assess

HOMEPAGE = "https://github.com/imhammad/modelbump"
_ORDER = ("regressed", "inconclusive", "equivalent", "improved")
_BRANCH_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")

Run = Callable[[Sequence[str], Path], "subprocess.CompletedProcess[str]"]


def pr_title(plan: BumpPlan) -> str:
    return f"Bump LLM model from {plan.old} to {plan.new}"


def branch_name(old: str, new: str) -> str:
    """``modelbump/gpt-4o-to-gpt-5.1``, safe for git (no ``:``, ``@``, ``..``)."""

    def part(model_id: str) -> str:
        return re.sub(r"\.{2,}", ".", _BRANCH_UNSAFE.sub("-", model_id)).strip(".-")

    return f"modelbump/{part(old)}-to-{part(new)}"


def pr_body(plan: BumpPlan, evidence: Evidence | None, registry: Registry, today: date) -> str:
    """The pull request description, in GitHub Markdown."""
    lines = [f"## Bump `{plan.old}` to `{plan.new}`", "", _why(plan, registry, today), ""]
    lines += _changed(plan)
    lines += _check_by_hand(plan)
    lines += _test(plan, evidence)
    lines += [
        "---",
        f"Opened by [ModelBump]({HOMEPAGE}) {__version__}. "
        "A person should review this change before it is merged.",
    ]
    return "\n".join(lines) + "\n"


def _why(plan: BumpPlan, registry: Registry, today: date) -> str:
    found = assess(plan.old, registry, today)
    if found.severity is Severity.UNKNOWN:
        return f"`{plan.old}` has no retirement announced in the ModelBump registry."
    shutdown = f"{'no earlier than ' if found.shutdown_is_earliest else ''}{found.shutdown}"
    if found.severity is Severity.RETIRED:
        status = f"`{plan.old}` shut down on {shutdown}: calls to it fail now."
    else:
        status = f"`{plan.old}` shuts down {'' if found.shutdown_is_earliest else 'on '}{shutdown}"
        status += f" (in {found.days_left} days)."
    if found.replacement == plan.new:
        status += f" The provider suggests `{plan.new}`."
    elif found.replacement:
        status += f" The provider suggests `{found.replacement}`; this bump uses `{plan.new}`."
    return status


def _changed(plan: BumpPlan) -> list[str]:
    lines = ["### What changed", ""]
    places = len(plan.edits)
    files = sum(1 for change in plan.changes if change.edits)
    if places:
        line = (
            f"- {places} {_s(places, 'place')} in {files} {_s(files, 'file')} "
            f"now {'uses' if places == 1 else 'use'} `{plan.new}`."
        )
        if plan.moved:
            line += f" {plan.moved} of them read `{plan.env}` from the environment."
        lines.append(line)
    if plan.repaired:
        calls = ", ".join(f"`{call}`" for call in plan.repaired)
        lines.append(f"- The prompt of {calls} has the repair the test accepted.")
    evidence = [change.path for change in plan.changes if change.evidence]
    if evidence:
        lines.append(
            f"- Evidence added in `{EVIDENCE_DIR}/`: "
            + ", ".join(f"`{path.removeprefix(EVIDENCE_DIR + '/')}`" for path in evidence)
            + "."
        )
    if len(lines) == 2:
        lines.append("- Nothing in the code uses the old model.")
    return [*lines, ""]


def _check_by_hand(plan: BumpPlan) -> list[str]:
    if not plan.skipped and not plan.by_hand:
        return []
    lines = ["### Check by hand", ""]
    for skipped in plan.skipped:
        f = skipped.finding
        lines.append(f"- `{f.path}:{f.line}` `{f.model_id}`: {SKIP_HINTS[skipped.reason]}.")
    for call, reason in plan.by_hand:
        lines.append(
            f"- Repair for `{call}` not written into the code: {reason}. "
            f"The patch is in `{EVIDENCE_DIR}/repairs.json`."
        )
    return [*lines, ""]


def _test(plan: BumpPlan, evidence: Evidence | None) -> list[str]:
    lines = ["### Test", ""]
    data = evidence.test_data if evidence is not None else None
    if data is None:
        lines += [
            "No test was run for this bump. Run `modelbump suite` and `modelbump test`, "
            "then bump with `--suite` and `--report` to add the evidence.",
            "",
        ]
        return lines
    old, new = str(data.get("old")), str(data.get("new"))
    lines.append(f"Ran the app's test cases on `{old}` and `{new}`: {_method(data)}.")
    if (old.rsplit("/", 1)[-1], new.rsplit("/", 1)[-1]) != (plan.old, plan.new):
        lines.append(
            "These models stand in for the bump's models, so the result shows how the app's "
            "prompts hold up across a model change, not these exact models."
        )
    if data.get("patched"):
        patched = int(data["patched"])
        lines.append(
            f"The new model got the repaired prompts in {patched} {_s(patched, 'test case')}."
        )
    lines.append("")
    # Counted from the cases, so the warning, the table and the summary always agree.
    counts = Counter(
        str(case.get("verdict") or "").lower() for case in data["cases"] if not case.get("error")
    )
    regressed = counts["regressed"]
    errors = sum(1 for case in data["cases"] if case.get("error"))
    if regressed or errors:
        problems = []
        if regressed:
            problems.append(f"{regressed} {_s(regressed, 'test case')} REGRESSED")
        if errors:
            problems.append(f"{errors} could not be run")
        lines += [f"> [!WARNING]\n> {' and '.join(problems)}. Review before merging.", ""]
    else:
        lines += ["No test case regressed.", ""]
    lines += [
        "| Verdict | Case | Checked by | Old | New | New model failed |",
        "|---|---|---|---|---|---|",
    ]
    for case in data["cases"]:
        lines.append(_row(case))
    summary = ", ".join(f"{counts[v]} {v}" for v in _ORDER)
    lines += [
        "",
        f"Result: {summary}. Scores are the share of answers that passed (0 to 1). "
        f"Every prompt, answer and score is in `{EVIDENCE_DIR}/test.json`.",
        "",
        "Run it again:",
        "",
        "```bash",
        _reproduce(data, evidence),
        "```",
        "",
    ]
    return lines


def _method(data: dict[str, Any]) -> str:
    runs = data.get("runs")
    how = (
        f"{runs} answers per model per case, fixed test with Benjamini-Hochberg"
        if data.get("method") == "fixed"
        else f"up to {runs} answers per model per case, sequential test with e-BH"
    )
    how += f" (q {data.get('q')}, margin {data.get('margin')})"
    if data.get("judge"):
        how += f", free text judged by `{data['judge']}`"
    return how


def _row(case: dict[str, Any]) -> str:
    verdict = "NOT RUN" if case.get("error") else str(case.get("verdict", "")).upper()
    failures = case.get("new_failures") or {}
    top = ", ".join(f"{name} ({times})" for name, times in list(failures.items())[:2])
    if case.get("error"):
        top = str(case["error"])
    cells = [
        f"**{verdict}**" if verdict in ("REGRESSED", "NOT RUN") else verdict,
        f"`{case.get('id')}`",
        str(case.get("kind", "")),
        f"{float(case.get('old_mean', 0)):.2f}",
        f"{float(case.get('new_mean', 0)):.2f}",
        top.replace("|", "\\|") if verdict != "EQUIVALENT" else "",
    ]
    return "| " + " | ".join(cells) + " |"


def _reproduce(data: dict[str, Any], evidence: Evidence | None) -> str:
    parts = [
        "modelbump test",
        f"{EVIDENCE_DIR}/suite.json",
        f"--from {data.get('old')}",
        f"--to {data.get('new')}",
        f"--runs {data.get('runs')}",
    ]
    if data.get("method") in ("fixed", "sequential"):
        parts.append(f"--method {data['method']}")
    if data.get("reference") is not None:
        parts.append(f"--reference {data['reference']}")
    if data.get("old_think"):
        parts.append(f"--from-think {data['old_think']}")
    if data.get("new_think"):
        parts.append(f"--to-think {data['new_think']}")
    if data.get("patched") and evidence is not None and evidence.accepted:
        parts.append(f"--patch {EVIDENCE_DIR}/repairs.json")
    if data.get("judge"):
        parts.append(f"--judge {data['judge']}")
    else:
        parts.append("--no-judge")
    return " ".join(parts)


def _s(count: int, word: str) -> str:
    return word if count == 1 else word + "s"


@dataclass(frozen=True, slots=True)
class Repo:
    """The git repository a pull request is opened from."""

    top: Path
    branch: str
    """The branch checked out now, which the pull request goes into."""


def _run(args: Sequence[str], cwd: Path) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, check=False)


def _ok(run: Run, args: Sequence[str], cwd: Path) -> str:
    done = run(args, cwd)
    if done.returncode != 0:
        detail = (done.stderr or done.stdout).strip().splitlines()
        raise BumpError(f"`{' '.join(args[:3])}` failed: {detail[-1] if detail else 'no output'}")
    return done.stdout.strip()


def check_repo(root: Path, branch: str, run: Run = _run) -> Repo:
    """Check a pull request can be opened: gh exists, the tree is clean, the branch is new."""
    try:
        has_gh = run(["gh", "--version"], root if root.is_dir() else root.parent).returncode == 0
    except FileNotFoundError:
        has_gh = False
    if not has_gh:
        raise BumpError("--open-pr needs the GitHub CLI (gh): https://cli.github.com")
    cwd = root if root.is_dir() else root.parent
    top = Path(_ok(run, ["git", "rev-parse", "--show-toplevel"], cwd))
    if _ok(run, ["git", "status", "--porcelain"], top):
        raise BumpError("the working tree has changes; commit or stash them first")
    current = _ok(run, ["git", "branch", "--show-current"], top)
    if not current:
        raise BumpError("no branch is checked out (detached HEAD); switch to one first")
    if (
        run(["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], top).returncode
        == 0
    ):
        raise BumpError(f"branch {branch} already exists; delete it or merge its pull request")
    remote = run(["git", "ls-remote", "--exit-code", "--heads", "origin", branch], top)
    if remote.returncode == 0:
        raise BumpError(f"branch {branch} is already on origin; is a pull request open for it?")
    return Repo(top, current)


def open_pr(
    repo: Repo,
    paths: Sequence[Path],
    branch: str,
    title: str,
    body: str,
    run: Run = _run,
) -> str:
    """Commit ``paths`` on a new branch, push it, open the pull request, return its URL."""
    files = [path.resolve().relative_to(repo.top.resolve()).as_posix() for path in paths]
    _ok(run, ["git", "switch", "--create", branch], repo.top)
    try:
        _ok(run, ["git", "add", "--", *files], repo.top)
        _ok(run, ["git", "commit", "--message", title, "--message", _commit_note()], repo.top)
        _ok(run, ["git", "push", "--set-upstream", "origin", branch], repo.top)
        with tempfile.NamedTemporaryFile(
            "w", suffix=".md", delete=False, encoding="utf-8"
        ) as handle:
            handle.write(body)
        body_file = Path(handle.name)
        try:
            url = _ok(
                run,
                [
                    "gh",
                    "pr",
                    "create",
                    "--base",
                    repo.branch,
                    "--head",
                    branch,
                    "--title",
                    title,
                    "--body-file",
                    str(body_file),
                ],
                repo.top,
            )
        finally:
            body_file.unlink(missing_ok=True)
    finally:
        run(["git", "switch", repo.branch], repo.top)
    return url.splitlines()[-1] if url else ""


def _commit_note() -> str:
    return f"Changed by modelbump bump ({__version__}). The pull request holds the evidence."
