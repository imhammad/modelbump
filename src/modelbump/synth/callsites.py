"""Find the LLM calls in Python code, with their prompts and the variables they fill.

This is the first job of the suite synthesizer (ADR 0048): before ModelBump can
build test cases for an app, it must know where the app calls a model, which
model, and what prompt it sends. Each prompt becomes a *template*: the text
the code writes, with a ``{slot}`` wherever the code puts a value in at run
time. A later step fills the slots with test inputs.

Python files are read with the standard ``ast`` module, which gives the exact
value of every string and the pieces of every f-string. A file that does not
parse is counted and reported, never guessed at.

Names are followed inside one file: a prompt built in a variable, a
``messages`` list filled with ``.append``, a model ID kept in a constant or
read with ``os.getenv("X", "default")``. Values that come from another file,
a function argument or an attribute stay slots, and the call is marked as
partial so nobody mistakes a guess for the real prompt.
"""

import ast
import inspect
import string
import textwrap
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from modelbump.scanner.files import is_excluded, is_test_path, iter_source_files, read_source

_MAX_DEPTH = 8
_MAX_SOURCE = 80


class Api(StrEnum):
    """The kinds of LLM call the synthesizer recognises."""

    OPENAI_CHAT = "openai_chat"
    """``client.chat.completions.create(model=..., messages=[...])``"""
    OPENAI_RESPONSES = "openai_responses"
    """``client.responses.create(model=..., instructions=..., input=...)``"""
    OPENAI_COMPLETIONS = "openai_completions"
    """``client.completions.create(model=..., prompt=...)``"""
    ANTHROPIC = "anthropic"
    """``client.messages.create(model=..., system=..., messages=[...])``"""
    GEMINI = "gemini"
    """``client.models.generate_content(model=..., contents=...)``"""
    LITELLM = "litellm"
    """``litellm.completion(model=..., messages=[...])``"""
    OLLAMA = "ollama"
    """``ollama.chat(model=..., messages=[...])`` or ``ollama.generate(prompt=...)``"""
    OTHER = "other"
    """Any other call with ``model=`` and ``messages=`` or ``prompt=`` keywords."""


@dataclass(frozen=True, slots=True)
class PromptPart:
    """One message of a prompt, as a template.

    ``template`` uses Python's format syntax: ``{ticket}`` is a slot, and a
    literal brace is doubled (``{{``). It is None when the code builds this
    message in a way the synthesizer cannot read, such as ``messages=history``.
    """

    role: str
    """``system``, ``user``, ``assistant``, ``prompt`` (one-string APIs) or ``unknown``."""
    template: str | None
    line: int
    source: str
    """The code of the expression, shortened, to show where the text came from."""

    @property
    def slots(self) -> tuple[str, ...]:
        """The slot names, in order of first use."""
        return slot_names(self.template) if self.template is not None else ()

    @property
    def has_text(self) -> bool:
        """True when the template holds some written text, not only slots."""
        if self.template is None:
            return False
        return any(literal.strip() for literal, *_ in string.Formatter().parse(self.template))


@dataclass(frozen=True, slots=True)
class CallSite:
    """One LLM call in the code."""

    path: str
    line: int
    api: Api
    call: str
    """The called function as written, shortened: ``client.chat.completions.create``."""
    model: str | None
    """The model ID when the file names it, through constants and env defaults."""
    model_source: str | None
    """The code given as the model, or None when the call has no model argument."""
    parts: tuple[PromptPart, ...]

    @property
    def complete(self) -> bool:
        """True when every message was read and each holds written text."""
        return bool(self.parts) and all(part.has_text for part in self.parts)

    @property
    def slots(self) -> tuple[str, ...]:
        """Every slot across the messages, in order of first use."""
        seen: dict[str, None] = {}
        for part in self.parts:
            seen.update(dict.fromkeys(part.slots))
        return tuple(seen)


@dataclass(frozen=True, slots=True)
class CallSiteResult:
    """Everything one search found."""

    calls: tuple[CallSite, ...]
    files_read: int
    unparsed: tuple[str, ...] = field(default=())
    """Python files that do not parse with this Python version."""


def slot_names(template: str) -> tuple[str, ...]:
    """The slot names of a template, in order of first use."""
    seen: dict[str, None] = {}
    for _, name, _, _ in string.Formatter().parse(template):
        if name is not None:
            seen[name] = None
    return tuple(seen)


def render(template: str, values: Mapping[str, object]) -> str:
    """Fill a template's slots. A missing value raises ``KeyError`` with its name."""
    pieces = []
    for literal, name, _, _ in string.Formatter().parse(template):
        pieces.append(literal)
        if name is not None:
            pieces.append(str(values[name]))
    return "".join(pieces)


def find_call_sites(
    root: Path, exclude: Sequence[str] = (), skip_tests: bool = False
) -> CallSiteResult:
    """Find the LLM calls in every Python file under ``root`` (a folder or one file)."""
    if root.is_file():
        paths = [root]
        base = root.parent
    else:
        paths = [p for p in iter_source_files(root, exclude) if p.suffix in {".py", ".pyi"}]
        base = root
    calls: list[CallSite] = []
    unparsed: list[str] = []
    read = 0
    for path in paths:
        rel = path.relative_to(base).as_posix()
        if (skip_tests and is_test_path(rel)) or is_excluded(rel, exclude):
            continue
        text = read_source(path)
        if text is None:
            continue
        read += 1
        try:
            calls.extend(extract_calls(rel, text))
        except SyntaxError:
            unparsed.append(rel)
    return CallSiteResult(tuple(calls), read, tuple(unparsed))


def extract_calls(path: str, source: str) -> list[CallSite]:
    """Return the LLM calls in one Python file. Raises ``SyntaxError`` if it does not parse."""
    tree = ast.parse(source, filename=path)
    collector = _Collector()
    collector.visit(tree)
    calls = []
    for call, scopes in collector.calls:
        site = _call_site(path, call, _Resolver(scopes, call.lineno))
        if site is not None:
            calls.append(site)
    return calls


# ---------------------------------------------------------------------------
# Scopes: which values a name was given before a call.


@dataclass(slots=True)
class _Scope:
    """The assignments in one function body or module, in source order."""

    is_module: bool
    assigned: dict[str, list[tuple[int, ast.expr]]] = field(default_factory=dict)
    added: dict[str, list[tuple[int, ast.expr]]] = field(default_factory=dict)
    """``x += ...`` after the assignment."""
    appended: dict[str, list[tuple[int, ast.expr]]] = field(default_factory=dict)
    """``x.append(...)`` and ``x.extend(...)``, as lists to add."""


class _Collector(ast.NodeVisitor):
    """Walk a module once, recording assignments per scope and every call."""

    def __init__(self) -> None:
        self.scopes: list[_Scope] = [_Scope(is_module=True)]
        self.calls: list[tuple[ast.Call, tuple[_Scope, ...]]] = []

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> None:
        self.scopes.append(_Scope(is_module=False))
        self.generic_visit(node)
        self.scopes.pop()

    visit_FunctionDef = _function
    visit_AsyncFunctionDef = _function
    visit_Lambda = _function

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Name):
                self.scopes[-1].assigned.setdefault(target.id, []).append((node.lineno, node.value))
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name) and node.value is not None:
            self.scopes[-1].assigned.setdefault(node.target.id, []).append(
                (node.lineno, node.value)
            )
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        if isinstance(node.target, ast.Name) and isinstance(node.op, ast.Add):
            self.scopes[-1].added.setdefault(node.target.id, []).append((node.lineno, node.value))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.attr in {"append", "extend"}
            and len(node.args) == 1
        ):
            value = node.args[0]
            if func.attr == "append":
                value = ast.List(elts=[value], ctx=ast.Load())
                ast.copy_location(value, node.args[0])
            self.scopes[-1].appended.setdefault(func.value.id, []).append((node.lineno, value))
        self.calls.append((node, tuple(self.scopes)))
        self.generic_visit(node)


class _Resolver:
    """Look up what a name holds at one call, innermost scope first."""

    def __init__(self, scopes: tuple[_Scope, ...], line: int) -> None:
        self.scopes = scopes
        self.line = line

    def value(self, name: str) -> tuple[ast.expr, list[ast.expr]] | None:
        """The last value given to ``name`` before the call, and what was added after it."""
        for depth, scope in enumerate(reversed(self.scopes)):
            innermost = depth == 0
            # A function runs after its module has loaded, so module names
            # used inside a function may be assigned anywhere at module level.
            limit = self.line if innermost else 10**9
            found = [(line, v) for line, v in scope.assigned.get(name, []) if line <= limit]
            if not found:
                continue
            start, value = found[-1]
            added = [
                v
                for line, v in sorted(
                    scope.added.get(name, []) + scope.appended.get(name, []),
                    key=lambda item: item[0],
                )
                if start < line <= limit
            ]
            return value, added
        return None


# ---------------------------------------------------------------------------
# Which calls are LLM calls.


def _chain(func: ast.expr) -> list[str]:
    """``client.chat.completions.create`` -> ["client", "chat", "completions", "create"]."""
    names: list[str] = []
    while isinstance(func, ast.Attribute):
        names.append(func.attr)
        func = func.value
    if isinstance(func, ast.Name):
        names.append(func.id)
    elif isinstance(func, ast.Call):
        names.extend(reversed(_chain(func.func)))
    return list(reversed(names))


def _keyword(call: ast.Call, *names: str) -> ast.expr | None:
    for keyword in call.keywords:
        if keyword.arg in names:
            return keyword.value
    return None


# Calls that make images, audio or video from a prompt: not text to compare.
_MEDIA = frozenset({"images", "videos", "audio", "speech", "transcriptions", "embeddings"})


def _api_of(call: ast.Call) -> Api | None:
    chain = _chain(call.func)
    tail = tuple(chain[-3:])
    last = chain[-1] if chain else ""
    has_model = _keyword(call, "model") is not None
    if tail[-3:] in {("chat", "completions", x) for x in ("create", "parse", "stream")}:
        return Api.OPENAI_CHAT
    if tail[-2:] in {("responses", x) for x in ("create", "parse", "stream")}:
        return Api.OPENAI_RESPONSES
    if tail[-2:] == ("completions", "create"):
        return Api.OPENAI_COMPLETIONS
    if tail[-2:] in {("messages", x) for x in ("create", "parse", "stream")}:
        # OpenAI's Assistants API adds a message to a thread: no model, no prompt to test.
        return None if "threads" in chain else Api.ANTHROPIC
    if last in {"generate_content", "generate_content_stream"}:
        return Api.GEMINI
    if chain[:1] == ["litellm"] and last in {"completion", "acompletion"}:
        return Api.LITELLM
    if chain[:1] == ["ollama"] and last in {"chat", "generate"}:
        return Api.OLLAMA
    if (
        has_model
        and _keyword(call, "messages", "prompt") is not None
        and not _MEDIA.intersection(chain)
    ):
        return Api.OTHER
    return None


# ---------------------------------------------------------------------------
# Building one call site.


def _call_site(path: str, call: ast.Call, names: _Resolver) -> CallSite | None:
    api = _api_of(call)
    if api is None:
        return None
    parts: list[PromptPart] = []
    model_expr = _keyword(call, "model", "model_name")
    if api is Api.ANTHROPIC:
        _add_system(parts, _keyword(call, "system"), names)
        _add_messages(parts, _keyword(call, "messages"), names)
    elif api is Api.OPENAI_RESPONSES:
        _add_system(parts, _keyword(call, "instructions"), names)
        _add_input(parts, _keyword(call, "input"), names)
    elif api is Api.GEMINI:
        model_expr = _gemini_parts(call, parts, names, model_expr)
    elif api is Api.OPENAI_COMPLETIONS or (
        _keyword(call, "messages") is None and _keyword(call, "prompt") is not None
    ):
        _add_system(parts, _keyword(call, "system"), names)
        _add_text(parts, "prompt", _keyword(call, "prompt"), names)
    else:
        _add_messages(parts, _keyword(call, "messages"), names)
    model = _model_value(model_expr, names) if model_expr is not None else None
    return CallSite(
        path=path,
        line=call.lineno,
        api=api,
        call=_short(ast.unparse(call.func)),
        model=model,
        model_source=_short(ast.unparse(model_expr)) if model_expr is not None else None,
        parts=tuple(parts),
    )


def _add_text(parts: list[PromptPart], role: str, expr: ast.expr | None, names: _Resolver) -> None:
    if expr is None:
        return
    # A literal list or dict that is not text blocks (tool results, say) has no template.
    readable = not isinstance(expr, ast.List | ast.Tuple | ast.Dict | ast.Set)
    template = _template(expr, names) if readable else None
    parts.append(PromptPart(role, template, expr.lineno, _short(ast.unparse(expr))))


def _add_system(parts: list[PromptPart], expr: ast.expr | None, names: _Resolver) -> None:
    """Anthropic's ``system`` may also be a list of ``{"type": "text", "text": ...}`` blocks."""
    if expr is None or (isinstance(expr, ast.Constant) and expr.value is None):
        return
    _add_text(parts, "system", _text_blocks(expr) or expr, names)


def _add_input(parts: list[PromptPart], expr: ast.expr | None, names: _Resolver) -> None:
    """The Responses API takes one string or a list of messages as ``input``."""
    if expr is None:
        return
    target = _follow(expr, names)
    if isinstance(target, ast.List | ast.Tuple):
        _add_messages(parts, expr, names)
    else:
        _add_text(parts, "user", expr, names)


def _gemini_parts(
    call: ast.Call, parts: list[PromptPart], names: _Resolver, model_expr: ast.expr | None
) -> ast.expr | None:
    """Gemini: ``contents`` (keyword or first argument) and ``system_instruction``.

    With the older SDK the model and system prompt sit on the object:
    ``m = genai.GenerativeModel("gemini-1.5-flash", system_instruction=...)``
    and then ``m.generate_content(prompt)``. Returns the model expression.
    """
    system: ast.expr | None = None
    config = _keyword(call, "config")
    config = _follow(config, names) if config is not None else None
    if isinstance(config, ast.Call):
        system = _keyword(config, "system_instruction")
    elif isinstance(config, ast.Dict):
        system = _dict_get(config, "system_instruction")
    func = call.func
    if model_expr is None and isinstance(func, ast.Attribute):
        owner = _follow(func.value, names)
        if isinstance(owner, ast.Call) and _chain(owner.func)[-1:] == ["GenerativeModel"]:
            model_expr = _keyword(owner, "model_name", "model") or (
                owner.args[0] if owner.args else None
            )
            system = system or _keyword(owner, "system_instruction")
    _add_system(parts, system, names)
    contents = _keyword(call, "contents") or (call.args[0] if call.args else None)
    if contents is not None:
        target = _follow(contents, names)
        if isinstance(target, ast.List | ast.Tuple):
            for element in target.elts:
                if isinstance(element, ast.Dict) or _message_class(element) is not None:
                    _add_message(parts, element, names)
                else:
                    _add_text(parts, "user", element, names)
        else:
            _add_text(parts, "user", contents, names)
    return model_expr


def _add_messages(parts: list[PromptPart], expr: ast.expr | None, names: _Resolver) -> None:
    if expr is None:
        return
    elements = _list_elements(expr, names, 0)
    if elements is None:
        parts.append(PromptPart("unknown", None, expr.lineno, _short(ast.unparse(expr))))
        return
    for element in elements:
        _add_message(parts, element, names)


def _list_elements(expr: ast.expr, names: _Resolver, depth: int) -> list[ast.expr] | None:
    """The items of a messages list, following names, ``+`` and later appends."""
    if depth > _MAX_DEPTH:
        return None
    if isinstance(expr, ast.List | ast.Tuple):
        elements: list[ast.expr] = []
        for element in expr.elts:
            if isinstance(element, ast.Starred):
                inner = _list_elements(element.value, names, depth + 1)
                if inner is None:
                    return None
                elements.extend(inner)
            else:
                elements.append(element)
        return elements
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
        left = _list_elements(expr.left, names, depth + 1)
        right = _list_elements(expr.right, names, depth + 1)
        return None if left is None or right is None else left + right
    if isinstance(expr, ast.Name):
        found = names.value(expr.id)
        if found is None:
            return None
        value, added = found
        result = _list_elements(value, names, depth + 1)
        for extra in added:
            more = _list_elements(extra, names, depth + 1)
            if result is None or more is None:
                return None
            result = result + more
        return result
    return None


_MESSAGE_CLASSES = {
    "SystemMessage": "system",
    "HumanMessage": "user",
    "AIMessage": "assistant",
    "UserMessage": "user",
    "AssistantMessage": "assistant",
}


def _message_class(expr: ast.expr) -> str | None:
    if isinstance(expr, ast.Call):
        chain = _chain(expr.func)
        if chain and chain[-1] in _MESSAGE_CLASSES:
            return _MESSAGE_CLASSES[chain[-1]]
    return None


def _add_message(parts: list[PromptPart], element: ast.expr, names: _Resolver) -> None:
    """One message: a dict, ``dict(role=..., content=...)``, a (role, text) tuple, a class."""
    role: str | None = None
    content: ast.expr | None = None
    target = _follow(element, names)
    if isinstance(target, ast.Dict):
        role_expr = _dict_get(target, "role")
        role = _string(role_expr, names) if role_expr is not None else None
        content = _dict_get(target, "content")
        if content is None:
            content = _dict_get(target, "parts")
    elif isinstance(target, ast.Call) and _chain(target.func) == ["dict"]:
        role_expr = _keyword(target, "role")
        role = _string(role_expr, names) if role_expr is not None else None
        content = _keyword(target, "content")
    elif isinstance(target, ast.Tuple) and len(target.elts) == 2:
        role = _string(target.elts[0], names)
        content = target.elts[1]
    elif (kind := _message_class(target)) is not None and isinstance(target, ast.Call):
        role = kind
        content = _keyword(target, "content") or (target.args[0] if target.args else None)
    if content is None:
        parts.append(PromptPart("unknown", None, element.lineno, _short(ast.unparse(element))))
        return
    role = {"human": "user", "ai": "assistant", "model": "assistant"}.get(role or "", role)
    _add_text(parts, role or "unknown", _text_blocks(content) or content, names)


def _text_blocks(expr: ast.expr) -> ast.expr | None:
    """``[{"type": "text", "text": X}, {"type": "image", ...}]`` -> X (the text blocks joined)."""
    if not isinstance(expr, ast.List | ast.Tuple):
        return None
    texts: list[ast.expr] = []
    for element in expr.elts:
        if not isinstance(element, ast.Dict):
            return None
        text = _dict_get(element, "text")
        if text is not None:
            texts.append(text)
    if not texts:
        return None
    joined: ast.expr = texts[0]
    for text in texts[1:]:
        joined = ast.BinOp(
            left=ast.BinOp(left=joined, op=ast.Add(), right=ast.Constant("\n")),
            op=ast.Add(),
            right=text,
        )
    ast.copy_location(joined, texts[0])
    return joined


def _dict_get(node: ast.Dict, key: str) -> ast.expr | None:
    for k, v in zip(node.keys, node.values, strict=True):
        if isinstance(k, ast.Constant) and k.value == key:
            return v
    return None


def _follow(expr: ast.expr, names: _Resolver) -> ast.expr:
    """Follow a name to the value it was given, when there is one and nothing was added."""
    for _ in range(_MAX_DEPTH):
        if not isinstance(expr, ast.Name):
            return expr
        found = names.value(expr.id)
        if found is None or found[1]:
            return expr
        expr = found[0]
    return expr


def _string(expr: ast.expr, names: _Resolver) -> str | None:
    """The value of a plain string, through names; None for anything else."""
    target = _follow(expr, names)
    if isinstance(target, ast.Constant) and isinstance(target.value, str):
        return target.value
    return None


def _model_value(expr: ast.expr, names: _Resolver) -> str | None:
    """A model ID written in the file: a string, a constant, or an env lookup's default."""
    target = _follow(expr, names)
    if isinstance(target, ast.Constant) and isinstance(target.value, str):
        return target.value
    if isinstance(target, ast.Call):
        chain = _chain(target.func)
        if chain[-1:] in (["getenv"], ["get"]) and len(target.args) == 2:
            return _string(target.args[1], names)
        if chain[-1:] == ["getenv"]:
            default = _keyword(target, "default")
            return _string(default, names) if default is not None else None
    if isinstance(target, ast.BoolOp) and isinstance(target.op, ast.Or):
        # os.environ.get("MODEL") or "gpt-4o-mini"
        return _string(target.values[-1], names)
    return None


# ---------------------------------------------------------------------------
# Templates: the text of a prompt, with slots for the values filled in at run time.


def _template(expr: ast.expr, names: _Resolver, depth: int = 0) -> str:
    """The template of a prompt expression. Unknown values become one slot."""
    found = _known_template(expr, names, depth)
    return found if found is not None else _slot(expr)


def _slot(expr: ast.expr) -> str:
    name = ast.unparse(expr)
    name = " ".join(name.split())
    # Characters that would break the format syntax of the slot itself.
    for bad, good in (("{", "("), ("}", ")"), ("!", "not "), (":", " "), ("[", "("), ("]", ")")):
        name = name.replace(bad, good)
    return "{" + _short(name) + "}"


def _filled(expr: ast.expr, names: _Resolver, depth: int) -> str:
    """A value put into a prompt: its text when the file has it, else a slot.

    ``f"Labels: {LABELS}"`` with ``LABELS = "bug, feature"`` becomes the text
    ``Labels: bug, feature``; ``f"Ticket: {ticket}"`` keeps the slot ``{ticket}``.
    """
    target = _follow(expr, names)
    if (
        isinstance(target, ast.Constant)
        and isinstance(target.value, int | float)
        and not isinstance(target.value, bool)
    ):
        return str(target.value)
    return _template(expr, names, depth)


def _escape(text: str) -> str:
    return text.replace("{", "{{").replace("}", "}}")


def _known_template(expr: ast.expr, names: _Resolver, depth: int) -> str | None:
    if depth > _MAX_DEPTH:
        return None
    if isinstance(expr, ast.Constant):
        return _escape(expr.value) if isinstance(expr.value, str) else None
    if isinstance(expr, ast.JoinedStr):
        pieces = []
        for value in expr.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                pieces.append(_escape(value.value))
            elif isinstance(value, ast.FormattedValue):
                pieces.append(_filled(value.value, names, depth + 1))
        return "".join(pieces)
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
        left = _known_template(expr.left, names, depth + 1)
        right = _known_template(expr.right, names, depth + 1)
        if left is None and right is None:
            return None
        return (left if left is not None else _slot(expr.left)) + (
            right if right is not None else _slot(expr.right)
        )
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Mod):
        raw = _raw_string(expr.left, names)
        return _percent(raw, expr.right, names, depth) if raw is not None else None
    if isinstance(expr, ast.Name):
        found = names.value(expr.id)
        if found is None:
            return None
        value, added = found
        text = _known_template(value, names, depth + 1)
        if text is None:
            return None
        for extra in added:
            text += _template(extra, names, depth + 1)
        return text
    if isinstance(expr, ast.Call):
        return _call_template(expr, names, depth)
    return None


def _call_template(call: ast.Call, names: _Resolver, depth: int) -> str | None:
    func = call.func
    chain = _chain(func)
    last = chain[-1] if chain else ""
    if isinstance(func, ast.Attribute):
        if last == "format":
            raw = _raw_string(func.value, names)
            return _format(raw, call, names, depth) if raw is not None else None
        if last in {"strip", "lstrip", "rstrip"} and not call.args:
            inner = _known_template(func.value, names, depth + 1)
            return getattr(inner, last)() if inner is not None else None
        if last == "join" and len(call.args) == 1:
            sep = _string(func.value, names)
            if sep is None:
                return None
            items = _list_elements(call.args[0], names, depth + 1)
            if items is None:
                # "\n".join(lines) with lines unknown: one slot named after the list.
                return _slot(call.args[0])
            return _escape(sep).join(_filled(item, names, depth + 1) for item in items)
    if last in {"dedent", "cleandoc"} and len(call.args) == 1:
        inner = _known_template(call.args[0], names, depth + 1)
        if inner is None:
            return None
        return textwrap.dedent(inner) if last == "dedent" else inspect.cleandoc(inner)
    return None


def _raw_string(expr: ast.expr, names: _Resolver) -> str | None:
    """A plain string whose braces or % signs are placeholders (for .format and %)."""
    target = _follow(expr, names)
    if isinstance(target, ast.Call):
        chain = _chain(target.func)
        if chain[-1:] in (["dedent"], ["cleandoc"]) and len(target.args) == 1:
            inner = _raw_string(target.args[0], names)
            if inner is None:
                return None
            return textwrap.dedent(inner) if chain[-1] == "dedent" else inspect.cleandoc(inner)
        if (
            isinstance(target.func, ast.Attribute)
            and target.func.attr in {"strip", "lstrip", "rstrip"}
            and not target.args
        ):
            inner = _raw_string(target.func.value, names)
            return getattr(inner, target.func.attr)() if inner is not None else None
    return _string(target, names)


def _format(raw: str, call: ast.Call, names: _Resolver, depth: int) -> str | None:
    """``"Hi {name}, {}".format(...)``: put in the values the file has, keep slots for the rest.

    A slot keeps its field name (``{name}``); a positional slot is named by its code.
    """
    keywords = {k.arg: k.value for k in call.keywords if k.arg is not None}
    pieces: list[str] = []
    counter = 0
    try:
        parsed = list(string.Formatter().parse(raw))
    except ValueError:
        return None
    for literal, name, _, _ in parsed:
        pieces.append(_escape(literal))
        if name is None:
            continue
        if name == "":
            name = str(counter)
            counter += 1
        if name.isdigit():
            index = int(name)
            if index < len(call.args):
                pieces.append(_filled(call.args[index], names, depth + 1))
            else:
                pieces.append("{arg" + name + "}")
        elif name in keywords:
            value = _filled(keywords[name], names, depth + 1)
            # Keep the template's own name for a slot: {labels}, not {LABELS}.
            pieces.append(value if _has_text(value) else "{" + name + "}")
        else:
            pieces.append("{" + name + "}")
    return "".join(pieces)


def _has_text(template: str) -> bool:
    return any(literal for literal, *_ in string.Formatter().parse(template))


def _percent(raw: str, values: ast.expr, names: _Resolver, depth: int) -> str:
    """``"Hi %s" % name`` and ``"Hi %(name)s" % data``."""
    items = list(values.elts) if isinstance(values, ast.Tuple) else [values]
    pieces: list[str] = []
    i = 0
    used = 0
    while i < len(raw):
        char = raw[i]
        if char != "%":
            pieces.append(_escape(char))
            i += 1
            continue
        if raw[i + 1 : i + 2] == "%":
            pieces.append("%")
            i += 2
            continue
        j = i + 1
        name: str | None = None
        if raw[j : j + 1] == "(":
            close = raw.find(")", j)
            if close == -1:
                pieces.append("%")
                i += 1
                continue
            name = raw[j + 1 : close]
            j = close + 1
        while j < len(raw) and raw[j] in "#0- +.123456789":
            j += 1
        if j >= len(raw) or raw[j] not in "sdifrgeExXoc":
            pieces.append("%")
            i += 1
            continue
        if name is not None:
            pieces.append("{" + name + "}")
        elif used < len(items):
            pieces.append(_filled(items[used], names, depth + 1))
            used += 1
        else:
            pieces.append("{arg" + str(used) + "}")
            used += 1
        i = j + 1
    return "".join(pieces)


def _short(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= _MAX_SOURCE else text[: _MAX_SOURCE - 3] + "..."
