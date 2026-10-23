"""Where in a file a model ID appears: a call argument, a variable, a comment, ...

Python (ADR 0027), TypeScript and JavaScript (ADR 0028) files are parsed with
tree-sitter, which also builds a tree for files that do not parse cleanly
(Python 2, half-edited code), so a syntax error never hides a finding. Config
files get the key the ID is the value of. Other files keep the plain-text
finding without context.

Three line rules then mark IDs that only describe a model (ADR 0031): comment
lines in files that are not parsed, price and limit tables, and IDs inside a
sentence.
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath

import tree_sitter_python
import tree_sitter_typescript
from tree_sitter import Language, Node, Parser

PYTHON_SUFFIXES = frozenset({".py", ".pyi"})
# TypeScript proper cannot use the TSX grammar (`<T>x` casts clash with JSX),
# and JavaScript files often hold JSX, so they use the TSX grammar.
TYPESCRIPT_SUFFIXES = frozenset({".ts", ".mts", ".cts"})
TSX_SUFFIXES = frozenset({".tsx", ".js", ".jsx", ".mjs", ".cjs"})
CONFIG_SUFFIXES = frozenset(
    {".json", ".jsonc", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".env"}
)
# Example env files without a leading dot.
CONFIG_NAMES = frozenset({"env.example", "env.sample", "env.template", "example.env"})
# How a comment line starts, for files that are not parsed. JSON has no comments.
_HASH = ("#",)
_C_LIKE = ("//", "/*", "* ", "*/")
COMMENT_PREFIXES: dict[str, tuple[str, ...]] = {
    ".go": _C_LIKE,
    ".java": _C_LIKE,
    ".kt": _C_LIKE,
    ".rs": _C_LIKE,
    ".cs": _C_LIKE,
    ".swift": _C_LIKE,
    ".php": (*_C_LIKE, "#"),
    ".rb": _HASH,
    ".sh": _HASH,
    ".ex": _HASH,
    ".exs": _HASH,
    ".html": ("<!--",),
    ".htm": ("<!--",),
    ".jsonc": ("//", "/*"),
    ".yaml": _HASH,
    ".yml": _HASH,
    ".toml": _HASH,
    ".ini": ("#", ";"),
    ".cfg": ("#", ";"),
    ".conf": ("#", ";"),
    ".env": _HASH,
}
_MAX_DETAIL = 60
_CONFIG_KEY = re.compile(r"""^\s*(?:export\s+)?["']?([A-Za-z0-9_.-]+)["']?\s*[:=]""")
_PYTHON = Language(tree_sitter_python.language())
_TYPESCRIPT = Language(tree_sitter_typescript.language_typescript())
_TSX = Language(tree_sitter_typescript.language_tsx())


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
    PROSE = "prose"
    """Inside a sentence, such as help text: ``"Model to use (default: gpt-4o)"``."""
    TABLE = "table"
    """The key of a price or limit table: ``"gpt-4o": (2.50, 10.00)``."""


# Contexts that describe a model rather than use it; --skip-comments leaves them out.
DOCUMENTATION = frozenset({Context.COMMENT, Context.DOCSTRING, Context.PROSE, Context.TABLE})


@dataclass(frozen=True, slots=True)
class Place:
    """The context of one finding, with a short detail such as the call or name."""

    context: Context
    detail: str | None = None


def file_kind(path: str) -> str:
    """``python``, ``typescript``, ``tsx``, ``config`` or ``text``, from a file name."""
    name = PurePosixPath(path).name
    suffix = PurePosixPath(path).suffix.lower()
    if suffix in PYTHON_SUFFIXES:
        return "python"
    if suffix in TYPESCRIPT_SUFFIXES:
        return "typescript"
    if suffix in TSX_SUFFIXES:
        return "tsx"
    if (
        suffix in CONFIG_SUFFIXES
        or name in CONFIG_NAMES
        or name == ".env"
        or name.startswith(".env.")
    ):
        return "config"
    return "text"


def comment_prefixes(path: str) -> tuple[str, ...]:
    """How a whole-line comment starts in a file that is not parsed; empty if unknown."""
    name = PurePosixPath(path).name
    if name in CONFIG_NAMES or name == ".env" or name.startswith(".env."):
        return _HASH
    return COMMENT_PREFIXES.get(PurePosixPath(path).suffix.lower(), ())


def places(path: str, text: str, spots: Sequence[tuple[int, int, int]]) -> list[Place]:
    """Return the place of each ``(line, column, length)`` spot in ``text``.

    Lines and columns start at 1 and count characters, as the finder reports them.
    """
    kind = file_kind(path)
    lines = text.splitlines()
    if kind == "python":
        found = _tree_places(_PYTHON, _classify, text, spots)
    elif kind == "typescript":
        found = _tree_places(_TYPESCRIPT, _classify_js, text, spots)
    elif kind == "tsx":
        found = _tree_places(_TSX, _classify_js, text, spots)
    elif kind == "config":
        found = [_config_place(lines[line - 1], column) for line, column, _ in spots]
    else:
        found = [Place(Context.TEXT) for _ in spots]
    prefixes = comment_prefixes(path) if kind in {"config", "text"} else ()
    return [
        _describe(place, lines[line - 1], column, length, prefixes)
        for place, (line, column, length) in zip(found, spots, strict=True)
    ]


def _describe(
    place: Place, line: str, column: int, length: int, prefixes: tuple[str, ...]
) -> Place:
    """Apply the line rules of ADR 0031 to a finding that is not documentation yet."""
    if place.context in DOCUMENTATION:
        return place
    if prefixes and line.lstrip().startswith(prefixes):
        return Place(Context.COMMENT)
    span = _string_around(line, column - 1, column - 1 + length)
    if span is None:
        return place
    start, end = span
    if _TABLE_VALUE.match(line, end + 1):
        return Place(Context.TABLE)
    inner = line[start + 1 : end]
    if (
        any(c.isspace() for c in inner)
        and not _escaped_quotes_around(line, column - 1, length)
        and not _code_quotes_around(line, column - 1, length, line[start])
    ):
        return Place(Context.PROSE)
    return place


# After a table key: a number, a tuple of numbers, or an object whose first value is one.
_TABLE_VALUE = re.compile(r"""\s*(?::|=>)\s*(?:[(\[]\s*|\{\s*["']?\w+["']?\s*:\s*)?[-+]?\.?\d""")
_STRING = re.compile(r""""(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|`(?:[^`\\]|\\.)*`""")


def _string_around(line: str, start: int, end: int) -> tuple[int, int] | None:
    """The quotes (start, end index) of the one-line string holding [start, end), if any."""
    for match in _STRING.finditer(line):
        if match.start() < start and end < match.end():
            return match.start(), match.end() - 1
        if match.start() > start:
            break
    return None


def _code_quotes_around(line: str, start: int, length: int, outer: str) -> bool:
    """True for ``"model='gpt-4o'"``: code with its own quotes, stored in a string."""
    quote = line[start - 1] if start > 0 else ""
    if quote not in {'"', "'", "`"} or quote == outer:
        return False
    if line[start + length : start + length + 1] != quote:
        return False
    before = line[: start - 1].rstrip()
    return before.endswith(("=", "(", ",", ":", "[", "{"))


def _escaped_quotes_around(line: str, start: int, length: int) -> bool:
    """True for ``\\"gpt-4o\\"``: a string in code that is itself stored in a string."""
    before = line[max(0, start - 2) : start]
    after = line[start + length : start + length + 2]
    return before in {'\\"', "\\'"} and after == before


def _config_place(line: str, column: int) -> Place:
    match = _CONFIG_KEY.match(line)
    if match is None or match.end() > column - 1:
        return Place(Context.CONFIG)
    return Place(Context.CONFIG, match.group(1))


def _tree_places(
    language: Language,
    classify: Callable[[Node | None], Place],
    text: str,
    spots: Sequence[tuple[int, int, int]],
) -> list[Place]:
    # The finder counts characters; tree-sitter counts UTF-8 bytes.
    lines = text.splitlines(keepends=True)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line.encode("utf-8")))
    tree = Parser(language).parse(text.encode("utf-8"))
    result = []
    for line_no, column, length in spots:
        line = lines[line_no - 1]
        start = starts[line_no - 1] + len(line[: column - 1].encode("utf-8"))
        end = start + len(line[column - 1 : column - 1 + length].encode("utf-8"))
        node = tree.root_node.descendant_for_byte_range(start, end)
        result.append(classify(node))
    return result


def _classify(node: Node | None) -> Place:
    """Classify a node in a Python tree."""
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


# Nodes an ID's string passes through on its way to what uses it:
# ("gpt-4o"), "gpt-4o" as const, env.MODEL ?? "gpt-4o", cond ? "a" : "b".
_JS_TRANSPARENT = frozenset(
    {
        "parenthesized_expression",
        "as_expression",
        "satisfies_expression",
        "binary_expression",
        "ternary_expression",
    }
)


def _classify_js(node: Node | None) -> Place:
    """Classify a node in a TypeScript or JavaScript tree."""
    while node is not None and node.type not in {"string", "template_string", "comment"}:
        node = node.parent
    if node is None:
        return Place(Context.STRING)
    if node.type == "comment":
        return Place(Context.COMMENT)
    while node.parent is not None and node.parent.type in _JS_TRANSPARENT:
        node = node.parent
    parent = node.parent
    if parent is None:
        return Place(Context.STRING)
    if parent.type == "pair" and _is_field(parent, "value", node):
        key = _js_key(parent.child_by_field_name("key"))
        options = parent.parent
        call = _js_call_of(options.parent) if options is not None else None
        if call is not None and options is not None and options.type == "object":
            return Place(Context.CALL_ARGUMENT, _short(f"{call}({{{key}}})"))
        return Place(Context.STRING, _short(key))
    if parent.type == "arguments":
        call = _js_call_of(parent)
        if call is not None:
            position = [c.id for c in parent.named_children].index(node.id) + 1
            return Place(Context.CALL_ARGUMENT, _short(f"{call}(argument {position})"))
    for kind, value_field, name_field in _JS_NAMED:
        if parent.type == kind and _is_field(parent, value_field, node):
            return Place(Context.ASSIGNMENT, _short(_text(parent.child_by_field_name(name_field))))
    if parent.type == "jsx_attribute" and parent.named_children:
        return Place(Context.STRING, _short(_text(parent.named_children[0])))
    return Place(Context.STRING)


# (node type, field holding the value, field holding the name)
_JS_NAMED = (
    ("variable_declarator", "value", "name"),
    ("assignment_expression", "right", "left"),
    ("public_field_definition", "value", "name"),
    ("required_parameter", "value", "pattern"),
    ("optional_parameter", "value", "pattern"),
    ("assignment_pattern", "right", "left"),
    ("object_assignment_pattern", "right", "left"),
)


def _js_call_of(arguments: Node | None) -> str | None:
    if arguments is None or arguments.type != "arguments" or arguments.parent is None:
        return None
    call = arguments.parent
    if call.type == "call_expression":
        return _text(call.child_by_field_name("function"))
    if call.type == "new_expression":
        return "new " + _text(call.child_by_field_name("constructor"))
    return None


def _js_key(key: Node | None) -> str:
    if key is not None and key.type == "string":
        parts = [c for c in key.named_children if c.type == "string_fragment"]
        return "".join(_text(part) for part in parts) or _text(key)
    return _text(key)


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
