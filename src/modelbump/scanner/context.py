"""Where in a file a model ID appears: a call argument, a variable, a comment, ... (ADR 0027).

Python files are parsed with tree-sitter, which also builds a tree for files
that do not parse cleanly (Python 2, half-edited code), so a syntax error
never hides a finding. Config files get the key the ID is the value of. Other
files keep the plain-text finding without context.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath

import tree_sitter_python
from tree_sitter import Language, Node, Parser

PYTHON_SUFFIXES = frozenset({".py", ".pyi"})
CONFIG_SUFFIXES = frozenset(
    {".json", ".jsonc", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".env"}
)
_MAX_DETAIL = 60
_CONFIG_KEY = re.compile(r"""^\s*(?:export\s+)?["']?([A-Za-z0-9_.-]+)["']?\s*[:=]""")
_PYTHON = Language(tree_sitter_python.language())


class Context(StrEnum):
    """Kinds of places a model ID can appear."""

    CALL_ARGUMENT = "call_argument"
    """A string passed to a call, such as ``create(model="gpt-4o")``."""
    ASSIGNMENT = "assignment"
    """A string given to a name: ``MODEL = "gpt-4o"`` or ``def f(model="gpt-4o")``."""
    STRING = "string"
    """Any other string in code, such as a dict value or a list item."""
    DOCSTRING = "docstring"
    """A string that is a statement on its own, as docstrings are."""
    COMMENT = "comment"
    CONFIG = "config"
    """A value in a config file (JSON, YAML, TOML, INI, .env)."""
    TEXT = "text"
    """A file the scanner does not parse (yet)."""


# Contexts that describe the code rather than use the model.
DOCUMENTATION = frozenset({Context.COMMENT, Context.DOCSTRING})


@dataclass(frozen=True, slots=True)
class Place:
    """The context of one finding, with a short detail such as the call or name."""

    context: Context
    detail: str | None = None


def file_kind(path: str) -> str:
    """``python``, ``config`` or ``text``, from a file name."""
    name = PurePosixPath(path).name
    suffix = PurePosixPath(path).suffix.lower()
    if suffix in PYTHON_SUFFIXES:
        return "python"
    if suffix in CONFIG_SUFFIXES or name == ".env" or name.startswith(".env."):
        return "config"
    return "text"


def places(path: str, text: str, spots: Sequence[tuple[int, int, int]]) -> list[Place]:
    """Return the place of each ``(line, column, length)`` spot in ``text``.

    Lines and columns start at 1 and count characters, as the finder reports them.
    """
    kind = file_kind(path)
    if kind == "python":
        return _python_places(text, spots)
    if kind == "config":
        lines = text.splitlines()
        return [_config_place(lines[line - 1], column) for line, column, _ in spots]
    return [Place(Context.TEXT) for _ in spots]


def _config_place(line: str, column: int) -> Place:
    match = _CONFIG_KEY.match(line)
    if match is None or match.end() > column - 1:
        return Place(Context.CONFIG)
    return Place(Context.CONFIG, match.group(1))


def _python_places(text: str, spots: Sequence[tuple[int, int, int]]) -> list[Place]:
    lines = text.splitlines(keepends=True)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line.encode("utf-8")))
    tree = Parser(_PYTHON).parse(text.encode("utf-8"))
    result = []
    for line_no, column, length in spots:
        line = lines[line_no - 1]
        start = starts[line_no - 1] + len(line[: column - 1].encode("utf-8"))
        end = start + len(line[column - 1 : column - 1 + length].encode("utf-8"))
        node = tree.root_node.descendant_for_byte_range(start, end)
        result.append(_classify(node))
    return result


def _classify(node: Node | None) -> Place:
    while node is not None and node.type not in {"string", "comment"}:
        node = node.parent
    if node is None:
        return Place(Context.STRING)
    if node.type == "comment":
        return Place(Context.COMMENT)
    # Step out of "a" "b" concatenations and (parentheses).
    while node.parent is not None and node.parent.type in {
        "concatenated_string",
        "parenthesized_expression",
    }:
        node = node.parent
    parent = node.parent
    if parent is None:
        return Place(Context.STRING)
    if parent.type == "keyword_argument":
        call = _call_of(parent.parent)
        name = _text(parent.child_by_field_name("name"))
        if call is not None:
            return Place(Context.CALL_ARGUMENT, _short(f"{call}({name}=)"))
    if parent.type == "argument_list":
        call = _call_of(parent)
        if call is not None:
            position = [c.id for c in parent.named_children].index(node.id) + 1
            return Place(Context.CALL_ARGUMENT, _short(f"{call}(argument {position})"))
    if parent.type == "assignment" and _is_field(parent, "right", node):
        return Place(Context.ASSIGNMENT, _short(_text(parent.child_by_field_name("left"))))
    if parent.type in {"default_parameter", "typed_default_parameter"}:
        return Place(Context.ASSIGNMENT, _short(_text(parent.child_by_field_name("name"))))
    if parent.type == "pair" and _is_field(parent, "value", node):
        key = parent.child_by_field_name("key")
        if key is not None and key.type == "string":
            return Place(Context.STRING, _short(_string_value(key)))
    if parent.type == "expression_statement":
        return Place(Context.DOCSTRING)
    return Place(Context.STRING)


def _call_of(argument_list: Node | None) -> str | None:
    if argument_list is None or argument_list.type != "argument_list":
        return None
    call = argument_list.parent
    if call is None or call.type != "call":
        return None
    return _text(call.child_by_field_name("function"))


def _is_field(parent: Node, field: str, node: Node) -> bool:
    child = parent.child_by_field_name(field)
    return child is not None and child.id == node.id


def _text(node: Node | None) -> str:
    if node is None or node.text is None:
        return "?"
    return " ".join(node.text.decode("utf-8", errors="replace").split())


def _string_value(node: Node) -> str:
    parts = [c for c in node.named_children if c.type == "string_content"]
    return "".join(_text(part) for part in parts) or _text(node)


def _short(detail: str) -> str:
    """Keep details readable: ``a.very.long(...).chain.create`` keeps its end."""
    if len(detail) <= _MAX_DETAIL:
        return detail
    return "..." + detail[-(_MAX_DETAIL - 3) :]
