"""Write an accepted prompt repair back into the app's Python source (ADR 0070).

A repair is a patch to the messages one call sends (ADR 0062): edits that
find and replace text, and an instruction added to the system message. In
the source, that text lives in string literals, often in another file than
the call ([ADR 0049](0049-follow-prompts-across-files-classes-and-functions.md)).

A patch is written back only when the place is certain:

- an edit's ``find`` must be in exactly one string literal of the app's
  Python files, exactly once;
- an added system instruction needs the call's whole system message to be
  exactly one string literal; the instruction is appended to it the way the
  test appended it (``text.rstrip() + "\\n\\n" + added``).

Literals inside f-strings are never touched, because their text is mixed
with code. Everything else is reported as "apply by hand", with the reason,
and the patch file stays in the evidence so the result can be reproduced.
"""

import ast
import json
from collections.abc import Mapping
from dataclasses import dataclass

from modelbump.repair import PromptPatch
from modelbump.suite import Suite


@dataclass(frozen=True, slots=True)
class Literal:
    """One plain string literal in a Python file."""

    path: str
    start: int
    """Offset of the literal's first character (its prefix or quote)."""
    end: int
    value: str
    source: str
    """The literal as written, quotes included."""


@dataclass(frozen=True, slots=True)
class SourceRepair:
    """Where each piece of a patch goes, or why it cannot be written back."""

    call: str
    replacements: tuple[tuple[Literal, str], ...]
    """``(literal, new value)`` pairs."""
    reason: str | None = None
    """Set when the patch must be applied by hand."""


def literals(path: str, text: str) -> list[Literal]:
    """Every plain string literal in ``text``: not bytes, not part of an f-string."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    in_fstring: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            in_fstring.update(id(part) for part in ast.walk(node))
    starts = _line_starts(text)
    found: list[Literal] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in in_fstring
            and node.end_lineno is not None
            and node.end_col_offset is not None
        ):
            start = _offset(text, starts, node.lineno, node.col_offset)
            end = _offset(text, starts, node.end_lineno, node.end_col_offset)
            found.append(Literal(path, start, end, node.value, text[start:end]))
    return found


def plan_repair(
    patch: PromptPatch, suite: Suite, sources: Mapping[str, list[Literal]]
) -> SourceRepair:
    """Find the literal each part of ``patch`` changes, in the app's Python files."""
    all_literals = [lit for found in sources.values() for lit in found]
    changed: dict[tuple[str, int], tuple[Literal, str]] = {}

    def current(lit: Literal) -> str:
        return changed.get((lit.path, lit.start), (lit, lit.value))[1]

    for edit in patch.edits:
        hits = [lit for lit in all_literals if edit.find in current(lit)]
        count = sum(current(lit).count(edit.find) for lit in hits)
        if count != 1:
            where = "in no string literal" if count == 0 else f"{count} times in the code"
            return SourceRepair(patch.call, (), f"the text to replace is {where}")
        (lit,) = hits
        changed[(lit.path, lit.start)] = (lit, current(lit).replace(edit.find, edit.replace))

    added = patch.add_system.strip()
    if added:
        system = _system_message(patch.call, suite)
        if system is None:
            return SourceRepair(patch.call, (), "the call has no system message to add to")
        for edit in patch.edits:  # the test added the instruction after the edits
            system = system.replace(edit.find, edit.replace)
        hits = [lit for lit in all_literals if current(lit) == system]
        if len(hits) != 1:
            why = "is built at runtime" if not hits else "is written in more than one place"
            return SourceRepair(patch.call, (), f"the system message {why}")
        (lit,) = hits
        changed[(lit.path, lit.start)] = (lit, f"{current(lit).rstrip()}\n\n{added}")
    return SourceRepair(patch.call, tuple(changed.values()))


def _system_message(call: str, suite: Suite) -> str | None:
    """The system message of the call's first case (the same in every case for a fixed one)."""
    systems = {
        text
        for case in suite.cases
        if f"{case.path}:{case.line}" == call
        for role, text in case.messages
        if role == "system"
    }
    return systems.pop() if len(systems) == 1 else None


def render(lit: Literal, value: str) -> str:
    """``value`` as a Python literal, in the old literal's quote style when that is safe."""
    source = lit.source
    for quote in ('"""', "'''"):
        if (
            source.startswith(quote)
            and source.endswith(quote)
            and quote not in value
            and "\\" not in value
            and "\r" not in value
            and not value.endswith(quote[0])
        ):
            return f"{quote}{value}{quote}"
    for quote in ('"', "'"):
        if (
            source.startswith(quote)
            and not source.startswith(quote * 3)
            and quote not in value
            and "\\" not in value
            and "\n" not in value
            and "\r" not in value
        ):
            return f"{quote}{value}{quote}"
    # A prefix, escapes or a joined literal: write a plain escaped string.
    return json.dumps(value, ensure_ascii=False)


def apply_repair(text: str, path: str, repair: SourceRepair) -> str:
    """``text`` with this file's replacements made, checked by parsing it again."""
    mine = sorted(
        ((lit, value) for lit, value in repair.replacements if lit.path == path),
        key=lambda pair: pair[0].start,
        reverse=True,
    )
    for lit, value in mine:
        if text[lit.start : lit.end] != lit.source:
            raise ValueError(f"{path}: a prompt literal changed while it was read")
        text = text[: lit.start] + render(lit, value) + text[lit.end :]
    values = {lit.value for lit in literals(path, text)}
    if not all(value in values for _, value in mine):
        raise ValueError(f"{path}: the repaired prompt did not come out as tested")
    return text


def _line_starts(text: str) -> list[int]:
    # ast counts lines on \n, \r\n and \r only (not str.splitlines' other breaks).
    starts = [0]
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\r" and text[index + 1 : index + 2] == "\n":
            index += 1
            starts.append(index + 1)
        elif char in "\r\n":
            starts.append(index + 1)
        index += 1
    return starts


def _offset(text: str, starts: list[int], line: int, col_utf8: int) -> int:
    """ast columns count UTF-8 bytes; turn one into a character offset."""
    start = starts[line - 1]
    line_end = starts[line] if line < len(starts) else len(text)
    encoded = text[start:line_end].encode("utf-8")
    return start + len(encoded[:col_utf8].decode("utf-8", errors="ignore"))
