"""Move a hard-coded model ID in Python code to an environment variable (ADR 0069).

``model="gpt-4o"`` becomes ``model=os.environ.get("OPENAI_MODEL", "gpt-5.1")``:
the environment variable is the one place to change the model next time,
and the new model is the default, so the app behaves the same when the
variable is not set.

Only places where the swap is plain Python are moved: a whole string literal
that is a call argument, the value given to a name, or a dict value. A file
whose new text would not parse keeps every literal. Places
that already read the environment (``os.getenv("X", "gpt-4o")``), f-strings,
bytes, strings with a prefix such as ``openai/``, and files that do not parse
keep their literal, and only the ID inside changes.
"""

import ast
import re

from modelbump.registry import Provider, Registry
from modelbump.scanner import Context, Finding
from modelbump.scanner.context import file_kind

_ENV_NAME = re.compile(r"[A-Z_][A-Z0-9_]*")
_QUOTES = "\"'"
_READS_ENV = ("getenv", "environ")
DEFAULT_ENV_NAMES: dict[Provider, str] = {
    Provider.ANTHROPIC: "ANTHROPIC_MODEL",
    Provider.GOOGLE: "GEMINI_MODEL",
    Provider.OPENAI: "OPENAI_MODEL",
}
FALLBACK_ENV_NAME = "LLM_MODEL"


def check_env_name(name: str) -> str:
    """Return ``name`` if it is a plain environment variable name, else raise ValueError."""
    if _ENV_NAME.fullmatch(name) is None:
        raise ValueError(f"{name!r} is not an environment variable name (A-Z, 0-9 and _)")
    return name


def suggested_env_name(old: str, registry: Registry) -> str:
    """``ANTHROPIC_MODEL``, ``GEMINI_MODEL`` or ``OPENAI_MODEL`` by the old model's provider."""
    found = registry.get(old)
    return DEFAULT_ENV_NAMES[found[0]] if found is not None else FALLBACK_ENV_NAME


def env_lookup(name: str, new: str) -> str:
    """The Python expression that replaces the string literal."""
    return f'os.environ.get("{name}", "{new}")'


def movable(finding: Finding, text: str, offset: int, end: int) -> bool:
    """True if the ID at ``text[offset:end]`` is a whole string literal that can be moved."""
    if file_kind(finding.path) != "python":
        return False
    detail = finding.detail or ""
    if finding.context is Context.STRING:
        # In Python, a STRING with a detail is a dict value with a string key.
        if not detail:
            return False
    elif finding.context not in (Context.CALL_ARGUMENT, Context.ASSIGNMENT):
        return False
    if any(word in detail for word in _READS_ENV):
        return False
    if offset < 1 or end >= len(text):
        return False
    quote = text[offset - 1]
    if quote not in _QUOTES or text[end] != quote:
        return False
    # Not an f/r/b/u string, and not a triple-quoted or empty-string neighbour.
    before = text[offset - 2] if offset >= 2 else ""
    if before.isalnum() or before == "_" or before == quote:
        return False
    # Not part of an implicit concatenation such as "gpt-4o" "-mini".
    left = text[: offset - 1].rstrip(" \t")
    right = text[end + 1 :].lstrip(" \t")
    return not (left.endswith(tuple(_QUOTES)) or right.startswith(tuple(_QUOTES)))


def import_position(text: str) -> int | None:
    """Where ``import os`` goes, or None if the file already imports it.

    It goes before the first top-level import other than ``from __future__``.
    Without one, it goes after the module docstring and ``from __future__``
    imports, or before the first statement (below a shebang or comments).
    Raises SyntaxError if ``text`` does not parse.
    """
    module = ast.parse(text)
    for stmt in module.body:
        if isinstance(stmt, ast.Import) and any(
            alias.asname is None and (alias.name == "os" or alias.name.startswith("os."))
            for alias in stmt.names
        ):
            return None
    starts = _line_starts(text)
    for stmt in module.body:
        if isinstance(stmt, ast.Import) or (
            isinstance(stmt, ast.ImportFrom) and stmt.module != "__future__"
        ):
            return starts[stmt.lineno - 1]
    after_line = 0
    for index, stmt in enumerate(module.body):
        is_docstring = (
            index == 0
            and isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
        )
        is_future = isinstance(stmt, ast.ImportFrom) and stmt.module == "__future__"
        if not (is_docstring or is_future):
            break
        after_line = stmt.end_lineno or stmt.lineno
    if after_line:
        return starts[after_line]
    if not module.body:
        return 0
    first = module.body[0]
    decorators: list[ast.expr] = getattr(first, "decorator_list", [])
    line: int = min([first.lineno, *(d.lineno for d in decorators)])
    return starts[line - 1]


def newline_of(text: str) -> str:
    """The file's own line ending."""
    return "\r\n" if "\r\n" in text else "\n"


def env_file_text(before: str | None, name: str, new: str) -> str | None:
    """``.env.example`` with ``NAME=new`` added, or None if it already sets NAME."""
    if before is None:
        return f"{name}={new}\n"
    pattern = re.compile(rf"^\s*(?:export\s+)?{re.escape(name)}\s*=", re.MULTILINE)
    if pattern.search(before):
        return None
    newline = newline_of(before)
    if before and not before.endswith(("\n", "\r")):
        before += newline
    return f"{before}{name}={new}{newline}"


def _line_starts(text: str) -> list[int]:
    starts = [0]
    for line in text.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    return starts
