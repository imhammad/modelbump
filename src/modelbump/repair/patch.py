"""Prompt patches: edits to the prompt text of one LLM call (ADR 0062).

A patch changes what the new model is sent, never what its answers are
checked against: the reference answers, the oracle and the judge still see
the app's own prompt. So a patch cannot pass by changing the task.

A patch is scoped to a call (``support.py:24``) and applies to every test
case of that call. Each edit must match exactly once in every case, so with
two or more cases it can only touch text the cases share: the prompt the
developer wrote, not one case's inputs.
"""

import difflib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from modelbump.suite.file import Suite, SuiteCase

PATCH_VERSION = 1


class PatchError(ValueError):
    """A patch that is malformed or does not fit the suite."""


@dataclass(frozen=True, slots=True)
class Edit:
    """Replace ``find`` with ``replace``. ``find`` must occur exactly once in each case."""

    find: str
    replace: str


@dataclass(frozen=True, slots=True)
class PromptPatch:
    """The edits for one LLM call, and an optional instruction added to its system message."""

    call: str
    """``path:line`` of the call, as in the case ids (``support.py:24``)."""
    edits: tuple[Edit, ...] = ()
    add_system: str = ""
    """Text added at the end of the system message, or as a new system message first."""
    note: str = ""
    """Why the patch exists, or who wrote it. Not sent to any model."""

    def __post_init__(self) -> None:
        path, _, line = self.call.rpartition(":")
        if not path or not line.isdigit():
            raise PatchError(f"patch call {self.call!r} is not path:line, e.g. support.py:24")
        if not self.edits and not self.add_system.strip():
            raise PatchError(f"patch for {self.call} changes nothing")
        finds = [edit.find for edit in self.edits]
        if any(not find for find in finds):
            raise PatchError(f"patch for {self.call}: an edit has an empty find")
        if len(set(finds)) != len(finds):
            raise PatchError(f"patch for {self.call}: two edits have the same find")
        if any(edit.find == edit.replace for edit in self.edits):
            raise PatchError(f"patch for {self.call}: an edit replaces text with itself")


def call_of(case: SuiteCase) -> str:
    """The call a case belongs to: ``support.py:24`` for ``support.py:24#2``."""
    return f"{case.path}:{case.line}"


def _short(text: str, limit: int = 40) -> str:
    flat = " ".join(text.split())
    return repr(flat if len(flat) <= limit else flat[: limit - 3] + "...")


def apply_patch(case: SuiteCase, patch: PromptPatch) -> SuiteCase:
    """The case with the patch applied: edits in order, then the system text."""
    if call_of(case) != patch.call:
        raise PatchError(f"patch for {patch.call} does not belong to case {case.id}")
    messages = list(case.messages)
    for edit in patch.edits:
        hits = sum(text.count(edit.find) for _, text in messages)
        if hits != 1:
            raise PatchError(
                f"case {case.id}: {_short(edit.find)} is found {hits} times; "
                "an edit must match exactly once"
            )
        messages = [(role, text.replace(edit.find, edit.replace)) for role, text in messages]
    if patch.add_system.strip():
        added = patch.add_system.strip()
        for index, (role, text) in enumerate(messages):
            if role == "system":
                messages[index] = (role, f"{text.rstrip()}\n\n{added}")
                break
        else:
            messages.insert(0, ("system", added))
    return replace(case, messages=tuple(messages))


def apply_patches(suite: Suite, patches: tuple[PromptPatch, ...]) -> Suite:
    """The suite with every patch applied. Same cases, same ids, same order."""
    calls = {call_of(case) for case in suite.cases}
    by_call: dict[str, PromptPatch] = {}
    for patch in patches:
        if patch.call in by_call:
            raise PatchError(f"two patches for {patch.call}; merge them into one")
        if patch.call not in calls:
            raise PatchError(f"no case in the suite for call {patch.call}")
        by_call[patch.call] = patch
    cases = tuple(
        apply_patch(case, by_call[call_of(case)]) if call_of(case) in by_call else case
        for case in suite.cases
    )
    return Suite(cases, suite.left_out)


def patches_to_json(patches: tuple[PromptPatch, ...]) -> str:
    """The patch file's text."""
    data = {
        "version": PATCH_VERSION,
        "patches": [
            {
                "call": patch.call,
                "edits": [{"find": e.find, "replace": e.replace} for e in patch.edits],
                "add_system": patch.add_system,
                "note": patch.note,
            }
            for patch in patches
        ],
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _patch(item: Any) -> PromptPatch:
    edits = tuple(Edit(str(e["find"]), str(e["replace"])) for e in item.get("edits", []))
    return PromptPatch(
        call=str(item["call"]),
        edits=edits,
        add_system=str(item.get("add_system", "")),
        note=str(item.get("note", "")),
    )


def read_patches(path: Path) -> tuple[PromptPatch, ...]:
    """Read a patch file. Raises ``PatchError`` with a readable message if it is wrong."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise PatchError(f"{path} is not valid JSON: {error}") from error
    if not isinstance(data, dict) or data.get("version") != PATCH_VERSION:
        raise PatchError(f"{path} is not a version {PATCH_VERSION} patch file")
    try:
        patches = tuple(_patch(item) for item in data["patches"])
    except (KeyError, TypeError) as error:
        raise PatchError(f"{path}: a patch is missing a field ({error})") from error
    if not patches:
        raise PatchError(f"{path} has no patches")
    return patches


def _lines(case: SuiteCase) -> list[str]:
    lines: list[str] = []
    for role, text in case.messages:
        lines.append(f"[{role}]")
        lines.extend(text.splitlines())
    return lines


def patch_diff(before: SuiteCase, after: SuiteCase) -> str:
    """A unified diff of what one case sends, before and after the patch."""
    diff = difflib.unified_diff(
        _lines(before), _lines(after), f"{before.id} (app)", f"{after.id} (patched)", lineterm=""
    )
    return "\n".join(diff)
