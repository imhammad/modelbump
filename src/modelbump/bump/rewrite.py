"""Change one model ID to another where the code uses it (ADR 0068).

The scanner already knows every place a model ID is written and what kind of
place it is. A bump plan keeps the places that use the old model, and turns
each into an edit of exactly the characters the scanner found:

- calls, names, other strings, config values and files the scanner does not
  parse are changed;
- comments, docstrings and sentences describe a model, so they are left alone
  unless ``include_docs`` is set;
- price and limit tables are never changed, because the old model's prices
  are not the new model's;
- cloud platform forms (Bedrock ``anthropic.claude-...-v1:0``, Vertex
  ``claude-...@20240620``) are left alone, because the new model's platform
  ID cannot be worked out from its provider ID.

With an environment variable name, whole string literals in Python are
also moved to that variable (:mod:`modelbump.bump.config`, ADR 0069).

Every place left alone is listed with its reason, so nothing is skipped
silently. Nothing is written until :func:`apply_plan`, which refuses a file
that changed since the plan was made.
"""

import ast
import difflib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from modelbump.bump.config import (
    check_env_name,
    env_file_text,
    env_lookup,
    import_position,
    movable,
    newline_of,
)
from modelbump.bump.evidence import Evidence
from modelbump.bump.prompts import Literal, apply_repair, literals, plan_repair
from modelbump.registry import Registry
from modelbump.scanner import Context, Finding, ScanResult, iter_source_files, scan_path
from modelbump.scanner.context import file_kind
from modelbump.scanner.files import is_test_path

# A model ID as people write it in code. Checked on the new ID so a bump can
# never write quotes, spaces or code into a file.
_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@-]*")
_DESCRIBES = frozenset({Context.COMMENT, Context.DOCSTRING, Context.PROSE})


class BumpError(ValueError):
    """A bump that cannot be planned or applied."""


class SkipReason(StrEnum):
    """Why a place that names the old model is left alone."""

    DESCRIBES = "describes"
    """A comment, docstring or sentence (changed with ``include_docs``)."""
    TABLE = "table"
    """The key of a price or limit table: the old model's numbers stay with it."""
    PLATFORM_FORM = "platform_form"
    """A Bedrock or Vertex AI form, whose new form must be looked up by hand."""
    NOT_UTF8 = "not_utf8"
    """A file that is not valid UTF-8, so it cannot be rewritten safely."""


SKIP_HINTS: dict[SkipReason, str] = {
    SkipReason.DESCRIBES: "comment, docstring or sentence; --include-docs changes these too",
    SkipReason.TABLE: "price or limit table; add the new model's row by hand",
    SkipReason.PLATFORM_FORM: "cloud platform ID; look up the new model's ID there",
    SkipReason.NOT_UTF8: "file is not UTF-8; change it by hand",
}


@dataclass(frozen=True, slots=True)
class Edit:
    """One model ID to change, at one place."""

    path: str
    line: int
    column: int
    old: str
    """The ID exactly as written."""
    new: str
    context: Context
    moved: bool = False
    """True when the literal now reads the environment variable."""
    movable: bool = False
    """True when the literal could read an environment variable (see ``env``)."""


@dataclass(frozen=True, slots=True)
class FileChange:
    """All edits in one file, with its text before and after."""

    path: str
    before: str
    after: str
    edits: tuple[Edit, ...]
    created: bool = False
    """True for a file the bump creates (``.env.example``, evidence files)."""
    evidence: bool = False
    """True for a file in ``.modelbump/``: listed, not shown in the diff."""


@dataclass(frozen=True, slots=True)
class Skipped:
    """A place that names the old model but is left alone."""

    finding: Finding
    reason: SkipReason


@dataclass(frozen=True, slots=True)
class BumpPlan:
    """What a bump would change, and what it leaves for a person to check."""

    old: str
    new: str
    changes: tuple[FileChange, ...]
    skipped: tuple[Skipped, ...]
    files_scanned: int
    env: str | None = None
    """The environment variable hard-coded IDs were moved to, if any."""
    repaired: tuple[str, ...] = ()
    """Calls whose accepted repair was written into the code."""
    by_hand: tuple[tuple[str, str], ...] = ()
    """``(call, reason)`` for accepted repairs that must be applied by hand."""
    tested: tuple[str, str] | None = None
    """The two models the test report compared."""

    @property
    def edits(self) -> tuple[Edit, ...]:
        return tuple(edit for change in self.changes for edit in change.edits)

    @property
    def moved(self) -> int:
        """Places that now read the environment variable."""
        return sum(edit.moved for edit in self.edits)

    @property
    def movable(self) -> int:
        """Places that hard-code the model and could read an environment variable."""
        return sum(edit.movable for edit in self.edits)


def check_model_id(model_id: str) -> str:
    """Return ``model_id`` if it looks like a model ID, else raise BumpError."""
    if _MODEL_ID.fullmatch(model_id) is None:
        raise BumpError(f"{model_id!r} does not look like a model ID")
    return model_id


def old_forms(old: str, registry: Registry) -> frozenset[str]:
    """The plain IDs that mean ``old``: itself, and its registry ID and aliases."""
    found = registry.get(old)
    if found is None:
        return frozenset({old})
    return frozenset({old, *found[1].all_ids()})


def plan_bump(
    root: Path,
    registry: Registry,
    old: str,
    new: str,
    *,
    exclude: Sequence[str] = (),
    include_docs: bool = False,
    env: str | None = None,
    evidence: Evidence | None = None,
    result: ScanResult | None = None,
) -> BumpPlan:
    """Plan the change from ``old`` to ``new`` under ``root`` (a folder or a file).

    With ``env``, whole string literals in Python read that environment
    variable instead, with ``new`` as the default, and ``.env.example`` in the
    root folder gets ``ENV=new`` when it does not set the variable yet.

    With ``evidence``, accepted repairs are written into the app's Python
    source where the place is certain, and the evidence files are added to
    ``.modelbump/`` (ADR 0070).

    ``result`` is a scan of ``root`` with the same ``exclude``, already made;
    ``bump-all`` passes it so the repository is scanned once (ADR 0073).
    """
    check_model_id(old)
    check_model_id(new)
    if env is not None:
        try:
            check_env_name(env)
        except ValueError as error:
            raise BumpError(str(error)) from error
    forms = old_forms(old, registry)
    if new in forms:
        raise BumpError(f"{new} is the same model as {old}")
    found = registry.get(old)
    registry_id = found[1].id if found is not None else None
    if result is None:
        result = scan_path(root, registry, exclude)
    base = root.parent if root.is_file() else root

    by_file: dict[str, list[Finding]] = {}
    skipped: list[Skipped] = []
    for finding in result.findings:
        same_model = finding.model_id in forms or (
            registry_id is not None and finding.registry_id == registry_id
        )
        if not same_model:
            continue
        reason = _skip_reason(finding, forms, include_docs)
        if reason is not None:
            skipped.append(Skipped(finding, reason))
        else:
            by_file.setdefault(finding.path, []).append(finding)

    changes: list[FileChange] = []
    for path, findings in by_file.items():
        try:
            before = (base / path).read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            skipped.extend(Skipped(f, SkipReason.NOT_UTF8) for f in findings)
            continue
        changes.append(_change(path, before, findings, new, env))
    moved = any(edit.moved for change in changes for edit in change.edits)
    if env is not None and moved and root.is_dir():
        changes = _with_env_file(base, changes, env, new)
    repaired: list[str] = []
    by_hand: list[tuple[str, str]] = []
    if evidence is not None and evidence.accepted:
        repaired, by_hand = _with_repairs(root, base, changes, evidence, exclude)
    if evidence is not None:
        _with_evidence(base, changes, evidence)
    skipped.sort(key=lambda s: (s.finding.path, s.finding.line, s.finding.column))
    return BumpPlan(
        old,
        new,
        tuple(changes),
        tuple(skipped),
        result.files_scanned,
        env,
        tuple(repaired),
        tuple(by_hand),
        evidence.tested if evidence is not None else None,
    )


def _with_repairs(
    root: Path,
    base: Path,
    changes: list[FileChange],
    evidence: Evidence,
    exclude: Sequence[str],
) -> tuple[list[str], list[tuple[str, str]]]:
    """Write each accepted repair into the source, or say why it must be done by hand."""
    assert evidence.suite is not None
    paths = [root] if root.is_file() else list(iter_source_files(root, exclude))
    texts: dict[str, str] = {}
    start: dict[str, str] = {}
    for path in paths:
        rel = path.relative_to(base).as_posix()
        if file_kind(rel) != "python" or is_test_path(rel):
            continue
        existing = next((c for c in changes if c.path == rel), None)
        try:
            texts[rel] = existing.after if existing else path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            continue
        start[rel] = texts[rel]
    found: dict[str, list[Literal]] = {rel: literals(rel, text) for rel, text in texts.items()}
    repaired: list[str] = []
    by_hand: list[tuple[str, str]] = []
    for patch in evidence.accepted:
        repair = plan_repair(patch, evidence.suite, found)
        if repair.reason is not None:
            by_hand.append((patch.call, repair.reason))
            continue
        touched = {lit.path for lit, _ in repair.replacements}
        try:
            new_texts = {rel: apply_repair(texts[rel], rel, repair) for rel in touched}
        except ValueError as error:
            by_hand.append((patch.call, str(error)))
            continue
        for rel, text in new_texts.items():
            texts[rel] = text
            found[rel] = literals(rel, text)
        repaired.append(patch.call)
    for rel, text in texts.items():
        if text == start[rel]:
            continue
        index = next((i for i, c in enumerate(changes) if c.path == rel), None)
        if index is not None:
            change = changes[index]
            changes[index] = FileChange(rel, change.before, text, change.edits, change.created)
        else:
            changes.append(FileChange(rel, start[rel], text, ()))
    return repaired, by_hand


def _with_evidence(base: Path, changes: list[FileChange], evidence: Evidence) -> None:
    """Add or update each evidence file in ``.modelbump/``."""
    for rel, text in evidence.files().items():
        path = base / rel
        before = path.read_bytes().decode("utf-8") if path.is_file() else None
        if before == text:
            continue
        changes.append(
            FileChange(rel, before or "", text, (), created=before is None, evidence=True)
        )


def _skip_reason(finding: Finding, forms: frozenset[str], include_docs: bool) -> SkipReason | None:
    if finding.model_id not in forms:
        return SkipReason.PLATFORM_FORM
    if finding.context is Context.TABLE:
        return SkipReason.TABLE
    if finding.context in _DESCRIBES and not include_docs:
        return SkipReason.DESCRIBES
    return None


def _change(
    path: str, before: str, findings: Sequence[Finding], new: str, env: str | None
) -> FileChange:
    """Edit ``before`` at every finding, checking each finding's text first."""
    parsed = file_kind(path) == "python" and _parses(before)
    change = _edit(path, before, findings, new, env, parsed)
    if parsed and env is not None and not _parses(change.after):
        # A safety net: if a swap would break the syntax, keep every literal.
        change = _edit(path, before, findings, new, None, parsed)
    return change


def _edit(
    path: str,
    before: str,
    findings: Sequence[Finding],
    new: str,
    env: str | None,
    parsed: bool,
) -> FileChange:
    starts = [0]
    for line in before.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    spans: list[tuple[int, int, str]] = []
    edits: list[Edit] = []
    for finding in findings:
        offset = starts[finding.line - 1] + finding.column - 1
        end = offset + len(finding.model_id)
        if before[offset:end] != finding.model_id:
            raise BumpError(f"{path}:{finding.line}: the text changed while it was read")
        can_move = parsed and movable(finding, before, offset, end)
        if can_move and env is not None:
            spans.append((offset - 1, end + 1, env_lookup(env, new)))
        else:
            spans.append((offset, end, new))
        edits.append(
            Edit(
                path,
                finding.line,
                finding.column,
                finding.model_id,
                new,
                finding.context,
                moved=can_move and env is not None,
                movable=can_move,
            )
        )
    if any(edit.moved for edit in edits):
        position = import_position(before)
        if position is not None:
            spans.append((position, position, "import os" + newline_of(before)))
    after = before
    for offset, end, text in sorted(spans, key=lambda span: span[0], reverse=True):
        after = after[:offset] + text + after[end:]
    return FileChange(path, before, after, tuple(edits))


def _parses(text: str) -> bool:
    try:
        ast.parse(text)
    except SyntaxError:
        return False
    return True


def _with_env_file(base: Path, changes: list[FileChange], env: str, new: str) -> list[FileChange]:
    """Add ``ENV=new`` to ``.env.example`` in ``base``, creating it if needed."""
    name = ".env.example"
    for index, change in enumerate(changes):
        if change.path == name:
            text = env_file_text(change.after, env, new)
            if text is not None:
                changes[index] = FileChange(name, change.before, text, change.edits)
            return changes
    path = base / name
    try:
        before = path.read_bytes().decode("utf-8") if path.exists() else None
    except UnicodeDecodeError:
        return changes
    text = env_file_text(before, env, new)
    if text is not None:
        changes.append(FileChange(name, before or "", text, (), created=before is None))
    return changes


def apply_plan(root: Path, plan: BumpPlan) -> None:
    """Write every change in ``plan``. Refuses if any file changed since the plan."""
    base = root.parent if root.is_file() else root
    for change in plan.changes:
        path = base / change.path
        if change.created:
            if path.exists():
                raise BumpError(f"{change.path} appeared since the bump was planned; run it again")
        elif path.read_bytes().decode("utf-8") != change.before:
            raise BumpError(f"{change.path} changed since the bump was planned; run it again")
    for change in plan.changes:
        path = base / change.path
        path.parent.mkdir(parents=True, exist_ok=True)
        # Bytes keep the file's own line endings (\r\n stays \r\n).
        path.write_bytes(change.after.encode("utf-8"))


def plan_diff(plan: BumpPlan) -> str:
    """A unified diff of every change, as ``git diff`` would show it."""
    parts: list[str] = []
    for change in plan.changes:
        if change.evidence:
            continue
        parts.extend(
            difflib.unified_diff(
                change.before.splitlines(keepends=True),
                change.after.splitlines(keepends=True),
                fromfile="/dev/null" if change.created else f"a/{change.path}",
                tofile=f"b/{change.path}",
            )
        )
    text = "".join(parts)
    return text if not text or text.endswith("\n") else text + "\n"


def skipped_lines(plan: BumpPlan) -> list[str]:
    """One line per place left alone: where, what, and what to do about it."""
    return [
        f"  {s.finding.path}:{s.finding.line}:{s.finding.column}  {s.finding.model_id}  "
        f"({SKIP_HINTS[s.reason]})"
        for s in plan.skipped
    ]
