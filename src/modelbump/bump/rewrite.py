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

Every place left alone is listed with its reason, so nothing is skipped
silently. Nothing is written until :func:`apply_plan`, which refuses a file
that changed since the plan was made.
"""

import difflib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from modelbump.registry import Registry
from modelbump.scanner import Context, Finding, scan_path

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


@dataclass(frozen=True, slots=True)
class FileChange:
    """All edits in one file, with its text before and after."""

    path: str
    before: str
    after: str
    edits: tuple[Edit, ...]


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

    @property
    def edits(self) -> tuple[Edit, ...]:
        return tuple(edit for change in self.changes for edit in change.edits)


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
) -> BumpPlan:
    """Plan the change from ``old`` to ``new`` under ``root`` (a folder or a file)."""
    check_model_id(old)
    check_model_id(new)
    forms = old_forms(old, registry)
    if new in forms:
        raise BumpError(f"{new} is the same model as {old}")
    found = registry.get(old)
    registry_id = found[1].id if found is not None else None
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
        changes.append(_change(path, before, findings, new))
    skipped.sort(key=lambda s: (s.finding.path, s.finding.line, s.finding.column))
    return BumpPlan(old, new, tuple(changes), tuple(skipped), result.files_scanned)


def _skip_reason(finding: Finding, forms: frozenset[str], include_docs: bool) -> SkipReason | None:
    if finding.model_id not in forms:
        return SkipReason.PLATFORM_FORM
    if finding.context is Context.TABLE:
        return SkipReason.TABLE
    if finding.context in _DESCRIBES and not include_docs:
        return SkipReason.DESCRIBES
    return None


def _change(path: str, before: str, findings: Sequence[Finding], new: str) -> FileChange:
    """Edit ``before`` at every finding, checking each finding's text first."""
    starts = [0]
    for line in before.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    spans: list[tuple[int, int]] = []
    edits: list[Edit] = []
    for finding in findings:
        offset = starts[finding.line - 1] + finding.column - 1
        end = offset + len(finding.model_id)
        if before[offset:end] != finding.model_id:
            raise BumpError(f"{path}:{finding.line}: the text changed while it was read")
        spans.append((offset, end))
        edits.append(
            Edit(path, finding.line, finding.column, finding.model_id, new, finding.context)
        )
    after = before
    for offset, end in sorted(spans, reverse=True):
        after = after[:offset] + new + after[end:]
    return FileChange(path, before, after, tuple(edits))


def apply_plan(root: Path, plan: BumpPlan) -> None:
    """Write every change in ``plan``. Refuses if any file changed since the plan."""
    base = root.parent if root.is_file() else root
    for change in plan.changes:
        if (base / change.path).read_bytes().decode("utf-8") != change.before:
            raise BumpError(f"{change.path} changed since the bump was planned; run it again")
    for change in plan.changes:
        # Bytes keep the file's own line endings (\r\n stays \r\n).
        (base / change.path).write_bytes(change.after.encode("utf-8"))


def plan_diff(plan: BumpPlan) -> str:
    """A unified diff of every change, as ``git diff`` would show it."""
    parts: list[str] = []
    for change in plan.changes:
        parts.extend(
            difflib.unified_diff(
                change.before.splitlines(keepends=True),
                change.after.splitlines(keepends=True),
                fromfile=f"a/{change.path}",
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
