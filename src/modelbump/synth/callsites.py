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
from pathlib import Path, PurePosixPath

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
    output: str | None = None
    """What the call's own settings ask for: ``json`` (``response_format`` and the
    like), ``tools`` (``tools=`` or ``functions=``), or None for plain text."""

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
    """Find the LLM calls in every Python file under ``root`` (a folder or one file).

    In a folder, names imported from other files in the folder are followed
    too (``from .prompts import SYSTEM``), whether or not those files are
    left out of the report by ``exclude`` or ``skip_tests``.
    """
    sources = _read_sources(root)
    project = _Project(sources)
    calls: list[CallSite] = []
    unparsed: list[str] = []
    read = 0
    for rel in sources:
        if (skip_tests and is_test_path(rel)) or _excluded(rel, exclude):
            continue
        read += 1
        module = project.module_at(rel)
        if module is None:
            unparsed.append(rel)
            continue
        calls.extend(_module_calls(module, project))
    return CallSiteResult(tuple(calls), read, tuple(unparsed))


def _read_sources(root: Path) -> dict[str, str]:
    """Every Python file under ``root`` (or ``root`` itself), by path relative to the folder."""
    if root.is_file():
        paths = [root]
        base = root.parent
    else:
        paths = [p for p in iter_source_files(root, exclude=()) if p.suffix in {".py", ".pyi"}]
        base = root
    sources: dict[str, str] = {}
    for path in paths:
        text = read_source(path)
        if text is not None:
            sources[path.relative_to(base).as_posix()] = text
    return sources


def _excluded(rel: str, exclude: Sequence[str]) -> bool:
    """True if the file or one of its folders matches an exclude pattern."""
    parts = rel.split("/")
    return any(is_excluded("/".join(parts[:k]), exclude) for k in range(1, len(parts) + 1))


def extract_calls(path: str, source: str) -> list[CallSite]:
    """Return the LLM calls in one Python file. Raises ``SyntaxError`` if it does not parse."""
    project = _Project({path: source})
    module = project.module_at(path, raise_errors=True)
    assert module is not None
    return _module_calls(module, project)


def _module_calls(module: "_Module", project: "_Project") -> list[CallSite]:
    calls = []
    for record in module.calls:
        names = _Resolver(record.scopes, record.call.lineno, module, project, record.owner)
        site = _call_site(module.path, record.call, names)
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
    functions: dict[str, "_Function"] = field(default_factory=dict)
    classes: dict[str, "_Class"] = field(default_factory=dict)
    annotations: dict[str, ast.expr] = field(default_factory=dict)
    """The type annotations of a function's parameters."""


@dataclass(frozen=True, slots=True)
class _AttrValue:
    """A value given to a class attribute, with the scopes it was written in."""

    line: int
    value: ast.expr
    scopes: tuple[_Scope, ...]
    method: str | None
    """The method holding ``self.x = ...``, or None for the class body."""


@dataclass(slots=True)
class _Class:
    """Class attributes: ``X = ...`` in the class body and ``self.x = ...`` in its methods."""

    name: str
    attrs: dict[str, list[_AttrValue]] = field(default_factory=dict)
    methods: dict[str, "_Function"] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _Owner:
    """The class and method a call sits in, and the method's ``self`` name."""

    cls: _Class
    method: str
    self_name: str


@dataclass(frozen=True, slots=True)
class _Function:
    """A function or method, to read the prompt it returns."""

    node: ast.FunctionDef | ast.AsyncFunctionDef
    scopes: tuple[_Scope, ...]
    """The scopes its body sees, its own last."""
    owner: _Owner | None
    kind: str
    """``function``, ``method``, ``classmethod`` or ``staticmethod``."""
    path: str


@dataclass(frozen=True, slots=True)
class _CallRecord:
    call: ast.Call
    scopes: tuple[_Scope, ...]
    owner: _Owner | None
    function: _Function | None
    """The function the call is written in, or None at module level."""


class _Collector(ast.NodeVisitor):
    """Walk a module once, recording assignments, imports, class attributes and calls."""

    def __init__(self, path: str, module: str, is_package: bool) -> None:
        self.path = path
        self.module = module
        self.is_package = is_package
        self.frames: list[_Scope | _Class] = [_Scope(is_module=True)]
        self.owners: list[_Owner | None] = [None]
        self.functions: list[_Function | None] = [None]
        self.calls: list[_CallRecord] = []
        self.imports: dict[str, tuple[str, str | None]] = {}
        """Local name -> (module, name in it); the name is None for ``import a.b``."""

    @property
    def scopes(self) -> tuple[_Scope, ...]:
        # Class bodies are not visible from their methods.
        return tuple(f for f in self.frames if isinstance(f, _Scope))

    @property
    def scope(self) -> _Scope | None:
        top = self.frames[-1]
        return top if isinstance(top, _Scope) else None

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> None:
        owner = self.owners[-1]
        parent = self.frames[-1]
        kind = "function"
        if isinstance(parent, _Class) and not isinstance(node, ast.Lambda):
            args = node.args.posonlyargs + node.args.args
            decorators = {d.id for d in node.decorator_list if isinstance(d, ast.Name)}
            kind = next((k for k in ("staticmethod", "classmethod") if k in decorators), "method")
            if args and kind != "staticmethod":
                owner = _Owner(parent, node.name, args[0].arg)
        scope = _Scope(is_module=False)
        every = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
        scope.annotations = {a.arg: a.annotation for a in every if a.annotation is not None}
        self.frames.append(scope)
        self.owners.append(owner)
        function: _Function | None = None
        if not isinstance(node, ast.Lambda):
            function = _Function(node, self.scopes, owner, kind, self.path)
            if isinstance(parent, _Class):
                parent.methods[node.name] = function
            else:
                parent.functions[node.name] = function
        self.functions.append(function)
        self.generic_visit(node)
        self.functions.pop()
        self.owners.pop()
        self.frames.pop()

    visit_FunctionDef = _function
    visit_AsyncFunctionDef = _function
    visit_Lambda = _function

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        cls = _Class(node.name)
        parent = self.frames[-1]
        if isinstance(parent, _Scope):
            parent.classes[node.name] = cls
        self.frames.append(cls)
        self.owners.append(None)
        self.generic_visit(node)
        self.owners.pop()
        self.frames.pop()

    def _assign(self, target: ast.expr, line: int, value: ast.expr) -> None:
        top = self.frames[-1]
        if isinstance(target, ast.Name):
            if isinstance(top, _Class):
                record = _AttrValue(line, value, self.scopes, None)
                top.attrs.setdefault(target.id, []).append(record)
            else:
                top.assigned.setdefault(target.id, []).append((line, value))
            return
        owner = self.owners[-1]
        if (
            owner is not None
            and isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == owner.self_name
        ):
            record = _AttrValue(line, value, self.scopes, owner.method)
            owner.cls.attrs.setdefault(target.attr, []).append(record)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._assign(target, node.lineno, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self._assign(node.target, node.lineno, node.value)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        scope = self.scope
        if scope is not None and isinstance(node.target, ast.Name) and isinstance(node.op, ast.Add):
            scope.added.setdefault(node.target.id, []).append((node.lineno, node.value))
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.asname is not None:
                self.imports[alias.asname] = (alias.name, None)
            else:
                first = alias.name.split(".")[0]
                self.imports[first] = (first, None)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        base = self._absolute(node.level, node.module)
        if base is None:
            return
        for alias in node.names:
            if alias.name != "*":
                self.imports[alias.asname or alias.name] = (base, alias.name)

    def _absolute(self, level: int, module: str | None) -> str | None:
        """The full module name of ``from ..x import y`` seen from this file."""
        if level == 0:
            return module
        parts = self.module.split(".") if self.module else []
        if not self.is_package:
            parts = parts[:-1]
        if level - 1 > len(parts):
            return None
        parts = parts[: len(parts) - (level - 1)]
        if module:
            parts += module.split(".")
        return ".".join(parts) if parts else None

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        scope = self.scope
        if (
            scope is not None
            and isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.attr in {"append", "extend"}
            and len(node.args) == 1
        ):
            value = node.args[0]
            if func.attr == "append":
                value = ast.List(elts=[value], ctx=ast.Load())
                ast.copy_location(value, node.args[0])
            scope.appended.setdefault(func.value.id, []).append((node.lineno, value))
        self.calls.append(_CallRecord(node, self.scopes, self.owners[-1], self.functions[-1]))
        self.generic_visit(node)


@dataclass(slots=True)
class _Module:
    """One parsed Python file."""

    path: str
    scope: _Scope
    imports: dict[str, tuple[str, str | None]]
    calls: list[_CallRecord]


def _dotted(path: str) -> tuple[str, bool]:
    """``app/prompts.py`` -> ("app.prompts", False); ``app/__init__.py`` -> ("app", True)."""
    parts = PurePosixPath(path).with_suffix("").parts
    if parts and parts[-1] == "__init__":
        return ".".join(parts[:-1]), True
    return ".".join(parts), False


class _Project:
    """The Python files of one folder, parsed on demand, to follow imports between them."""

    def __init__(self, sources: Mapping[str, str]) -> None:
        self.sources = sources
        self.by_name: dict[str, list[str]] = {}
        for path in sources:
            name, _ = _dotted(path)
            if name:
                self.by_name.setdefault(name, []).append(path)
        self.parsed: dict[str, _Module | None] = {}

    def module_at(self, path: str, raise_errors: bool = False) -> _Module | None:
        """The parsed file at ``path``; None if it does not parse."""
        if path not in self.parsed or raise_errors:
            try:
                tree = ast.parse(self.sources[path], filename=path)
            except SyntaxError:
                if raise_errors:
                    raise
                self.parsed[path] = None
                return None
            name, is_package = _dotted(path)
            collector = _Collector(path, name, is_package)
            collector.visit(tree)
            self.parsed[path] = _Module(
                path, collector.scopes[0], collector.imports, collector.calls
            )
        return self.parsed[path]

    def find(self, module: str) -> _Module | None:
        """The file of an imported module, by its full name or a unique folder suffix.

        Apps often run from a subfolder (``backend/app/x.py`` imports ``app.x``) or
        from ``src/``, so ``app.prompts`` also matches ``src/app/prompts.py`` when
        that is the only match.
        """
        paths = self.by_name.get(module)
        if paths is None:
            suffix = "." + module
            paths = [p for name, ps in self.by_name.items() if name.endswith(suffix) for p in ps]
        if len(paths) != 1:
            return None
        return self.module_at(paths[0])


@dataclass(frozen=True, slots=True)
class _Found:
    """What a name holds: its last value, what was added after it, and where to read both."""

    value: ast.expr
    added: list[ast.expr]
    where: "_Resolver"
    argument: bool = False
    """True when the name is a function parameter and the value is the caller's argument."""


class _Resolver:
    """Look up what a name holds at one place in the code, innermost scope first."""

    def __init__(
        self,
        scopes: tuple[_Scope, ...],
        line: int,
        module: _Module,
        project: _Project,
        owner: _Owner | None = None,
        arguments: Mapping[str, tuple[ast.expr, "_Resolver"]] | None = None,
    ) -> None:
        self.scopes = scopes
        self.line = line
        self.module = module
        self.project = project
        self.owner = owner
        self.arguments = arguments or {}
        """Parameters of the function being read, bound to the caller's arguments."""

    def value(self, expr: ast.expr) -> _Found | None:
        """The value of a name, ``self.attr``, or ``module.NAME``, if the code has it."""
        if isinstance(expr, ast.Name):
            return self._local(expr.id) or self._imported(expr.id)
        if isinstance(expr, ast.Attribute):
            if (
                self.owner is not None
                and isinstance(expr.value, ast.Name)
                and expr.value.id == self.owner.self_name
            ):
                return self._attribute(expr.attr)
            module = self._module_of(expr.value)
            if module is not None:
                return _Resolver.at_module(module, self.project)._local(expr.attr)
        return None

    @staticmethod
    def at_module(module: _Module, project: _Project) -> "_Resolver":
        """Read names at the end of a module, as code importing it sees them."""
        return _Resolver((module.scope,), 10**9, module, project)

    def _local(self, name: str) -> _Found | None:
        for depth, scope in enumerate(reversed(self.scopes)):
            innermost = depth == 0
            if depth == 1 and name in self.arguments:
                # A parameter not reassigned in the body: the caller's argument.
                expr, where = self.arguments[name]
                return _Found(expr, [], where, argument=True)
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
            return _Found(value, added, self)
        return None

    def _imported(self, name: str) -> _Found | None:
        """``from .prompts import SYSTEM``: the value of SYSTEM in prompts.py."""
        source = self.module.imports.get(name)
        if source is None or source[1] is None:
            return None
        module = self.project.find(source[0])
        if module is None or module is self.module:
            return None
        return _Resolver.at_module(module, self.project)._local(source[1])

    def _module_of(self, expr: ast.expr) -> _Module | None:
        """The file an expression like ``prompts`` or ``app.prompts`` names, if imported."""
        chain: list[str] = []
        while isinstance(expr, ast.Attribute):
            chain.append(expr.attr)
            expr = expr.value
        if not isinstance(expr, ast.Name):
            return None
        source = self.module.imports.get(expr.id)
        if source is None:
            return None
        base = source[0] if source[1] is None else f"{source[0]}.{source[1]}"
        name = ".".join([base, *reversed(chain)])
        module = self.project.find(name)
        return None if module is self.module else module

    def function(self, func: ast.expr) -> tuple[_Function, bool] | None:
        """The function a call runs, and whether the call passes its first parameter itself.

        Found for ``f(...)`` (in this file or imported), ``module.f(...)``,
        ``self.method(...)`` and ``ClassName.method(...)``.
        """
        if isinstance(func, ast.Name):
            for scope in reversed(self.scopes):
                if func.id in scope.functions:
                    return scope.functions[func.id], False
            source = self.module.imports.get(func.id)
            if source is not None and source[1] is not None:
                module = self.project.find(source[0])
                if module is not None and source[1] in module.scope.functions:
                    return module.scope.functions[source[1]], False
            return None
        if not isinstance(func, ast.Attribute):
            return None
        base = func.value
        if (
            self.owner is not None
            and isinstance(base, ast.Name)
            and base.id == self.owner.self_name
        ):
            method = self.owner.cls.methods.get(func.attr)
            if method is None:
                return None
            return method, method.kind != "staticmethod"
        cls = self._class(base)
        on_class = cls is not None
        if cls is None:
            cls, on_class = self._instance_class(base)
        if cls is not None:
            method = cls.methods.get(func.attr)
            if method is None:
                return None
            if on_class:
                return method, method.kind == "classmethod"
            return method, method.kind != "staticmethod"
        module = self._module_of(base)
        if module is not None and func.attr in module.scope.functions:
            return module.scope.functions[func.attr], False
        return None

    def _instance_class(self, expr: ast.expr) -> tuple["_Class | None", bool]:
        """The class of a parameter from its type annotation, or of ``x = ClassName(...)``.

        Returns the class and whether ``expr`` is the class itself (``type[X]``).
        """
        if not isinstance(expr, ast.Name) or not self.scopes:
            return None, False
        annotation = self.scopes[-1].annotations.get(expr.id)
        if annotation is not None:
            return self._annotation_class(annotation, 0)
        found = self._local(expr.id)
        if found is not None and isinstance(found.value, ast.Call):
            return found.where._class(found.value.func), False
        return None, False

    def _annotation_class(self, annotation: ast.expr, depth: int) -> tuple["_Class | None", bool]:
        """``X``, ``"X"``, ``X | None``, ``Optional[X]`` and ``type[X]`` -> X."""
        if depth > _MAX_DEPTH:
            return None, False
        if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
            try:
                parsed = ast.parse(annotation.value, mode="eval").body
            except SyntaxError:
                return None, False
            return self._annotation_class(parsed, depth + 1)
        if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
            for side in (annotation.left, annotation.right):
                found = self._annotation_class(side, depth + 1)
                if found[0] is not None:
                    return found
            return None, False
        if isinstance(annotation, ast.Subscript):
            outer = _chain(annotation.value)[-1:]
            if outer in (["type"], ["Type"]):
                return self._annotation_class(annotation.slice, depth + 1)[0], True
            if outer in (["Optional"], ["Union"], ["Annotated"]):
                inner = annotation.slice
                items = inner.elts if isinstance(inner, ast.Tuple) else [inner]
                for item in items[:1] if outer == ["Annotated"] else items:
                    found = self._annotation_class(item, depth + 1)
                    if found[0] is not None:
                        return found
            return None, False
        return self._class(annotation), False

    def _class(self, expr: ast.expr) -> "_Class | None":
        if isinstance(expr, ast.Attribute):
            module = self._module_of(expr.value)
            return module.scope.classes.get(expr.attr) if module is not None else None
        if not isinstance(expr, ast.Name):
            return None
        for scope in reversed(self.scopes):
            if expr.id in scope.classes:
                return scope.classes[expr.id]
        source = self.module.imports.get(expr.id)
        if source is not None and source[1] is not None:
            module = self.project.find(source[0])
            if module is not None:
                return module.scope.classes.get(source[1])
        return None

    def _attribute(self, name: str) -> _Found | None:
        """``self.name``: set earlier in the same method, else in ``__init__``, else the class.

        A value set only in other methods counts when there is exactly one.
        """
        assert self.owner is not None
        values = self.owner.cls.attrs.get(name, [])
        same = [v for v in values if v.method == self.owner.method and v.line <= self.line]
        init = [v for v in values if v.method == "__init__"]
        body = [v for v in values if v.method is None]
        other = [v for v in values if v.method not in {None, "__init__", self.owner.method}]
        for group in (same, init, body):
            if group:
                chosen = group[-1]
                break
        else:
            if len(other) != 1:
                return None
            chosen = other[0]
        where = _Resolver(chosen.scopes, chosen.line, self.module, self.project, self.owner)
        return _Found(chosen.value, [], where)


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
    if last == "count_tokens":
        return None
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


def _expand_kwargs(call: ast.Call, names: _Resolver) -> ast.Call:
    """``create(**params)`` with ``params = {"model": ..., "messages": ...}`` in the same function.

    The dict's keys become keywords of the call; keywords written in the call win.
    """
    if all(k.arg is not None for k in call.keywords):
        return call
    keywords = [k for k in call.keywords if k.arg is not None]
    written = {k.arg for k in keywords}
    for keyword in call.keywords:
        if keyword.arg is not None:
            continue
        found = names.value(keyword.value) if isinstance(keyword.value, ast.Name) else None
        if isinstance(keyword.value, ast.Dict):
            target = keyword.value
        elif found is not None and found.where is names and isinstance(found.value, ast.Dict):
            target = found.value
        else:
            continue
        for key, value in zip(target.keys, target.values, strict=True):
            if (
                isinstance(key, ast.Constant)
                and isinstance(key.value, str)
                and key.value not in written
            ):
                keywords.append(ast.keyword(arg=key.value, value=value))
                written.add(key.value)
    return ast.Call(func=call.func, args=call.args, keywords=keywords, lineno=call.lineno)


def _call_site(path: str, call: ast.Call, names: _Resolver) -> CallSite | None:
    call = _expand_kwargs(call, names)
    api = _api_of(call)
    if api is None:
        return None
    parts: list[PromptPart] = []
    model_expr = _keyword(call, "model", "model_name")
    model_names = names
    if api is Api.ANTHROPIC:
        _add_system(parts, _keyword(call, "system"), names)
        _add_messages(parts, _keyword(call, "messages"), names)
    elif api is Api.OPENAI_RESPONSES:
        _add_system(parts, _keyword(call, "instructions"), names)
        _add_input(parts, _keyword(call, "input"), names)
    elif api is Api.GEMINI:
        model_expr, model_names = _gemini_parts(call, parts, names, model_expr)
    elif api is Api.OPENAI_COMPLETIONS or (
        _keyword(call, "messages") is None and _keyword(call, "prompt") is not None
    ):
        _add_system(parts, _keyword(call, "system"), names)
        _add_text(parts, "prompt", _keyword(call, "prompt"), names)
    else:
        _add_messages(parts, _keyword(call, "messages"), names)
    model = _model_value(model_expr, model_names) if model_expr is not None else None
    return CallSite(
        path=path,
        line=call.lineno,
        api=api,
        call=_short(ast.unparse(call.func)),
        model=model,
        model_source=_short(ast.unparse(model_expr)) if model_expr is not None else None,
        parts=tuple(parts),
        output=_output_mode(call, names),
    )


# Keywords that set the output format, per API: OpenAI ``response_format``
# (chat) and ``text`` / ``text_format`` (responses), Ollama ``format``,
# Gemini ``config`` / ``generation_config`` (``response_mime_type``, ``response_schema``).
_FORMAT_KEYWORDS = (
    "response_format",
    "text_format",
    "text",
    "format",
    "config",
    "generation_config",
)


def _output_mode(call: ast.Call, names: _Resolver) -> str | None:
    """``tools``, ``json`` or None, from the call's own keywords (ADR 0052)."""
    for keyword in ("tools", "functions"):
        value = _keyword(call, keyword)
        if value is not None and not (isinstance(value, ast.Constant) and value.value is None):
            return "tools"
    parse = _chain(call.func)[-1:] == ["parse"]
    for keyword in _FORMAT_KEYWORDS:
        value = _keyword(call, keyword)
        if value is None:
            continue
        if parse and keyword in ("response_format", "text_format"):
            return "json"  # .parse(response_format=SomeModel) returns structured output.
        value = _follow(value, names)[0]
        if keyword != "format" and isinstance(value, ast.Constant | ast.JoinedStr):
            continue  # A plain string here is text, not a format setting.
        code = ast.unparse(value).lower()
        if keyword in ("config", "generation_config"):
            if "tools" in code:
                return "tools"
            if "application/json" in code or "response_schema" in code:
                return "json"
        elif "json" in code:
            return "json"
    return None


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
    target, _ = _follow(expr, names)
    if isinstance(target, ast.List | ast.Tuple):
        _add_messages(parts, expr, names)
    else:
        _add_text(parts, "user", expr, names)


def _gemini_parts(
    call: ast.Call, parts: list[PromptPart], names: _Resolver, model_expr: ast.expr | None
) -> tuple[ast.expr | None, _Resolver]:
    """Gemini: ``contents`` (keyword or first argument) and ``system_instruction``.

    With the older SDK the model and system prompt sit on the object:
    ``m = genai.GenerativeModel("gemini-1.5-flash", system_instruction=...)``
    and then ``m.generate_content(prompt)``. Returns the model expression and
    where to read it.
    """
    system: ast.expr | None = None
    system_names = names
    config = _keyword(call, "config")
    if config is not None:
        config, system_names = _follow(config, names)
        if isinstance(config, ast.Call):
            system = _keyword(config, "system_instruction")
        elif isinstance(config, ast.Dict):
            system = _dict_get(config, "system_instruction")
    func = call.func
    model_names = names
    if model_expr is None and isinstance(func, ast.Attribute):
        owner, where = _follow(func.value, names)
        if isinstance(owner, ast.Call) and _chain(owner.func)[-1:] == ["GenerativeModel"]:
            model_expr = _keyword(owner, "model_name", "model") or (
                owner.args[0] if owner.args else None
            )
            model_names = where
            if system is None:
                system, system_names = _keyword(owner, "system_instruction"), where
    _add_system(parts, system, system_names)
    contents = _keyword(call, "contents") or (call.args[0] if call.args else None)
    if contents is not None:
        target, where = _follow(contents, names)
        if isinstance(target, ast.List | ast.Tuple):
            for element in target.elts:
                if isinstance(element, ast.Dict) or _message_class(element) is not None:
                    _add_message(parts, element, where)
                else:
                    _add_text(parts, "user", element, where)
        else:
            _add_text(parts, "user", contents, names)
    return model_expr, model_names


def _add_messages(parts: list[PromptPart], expr: ast.expr | None, names: _Resolver) -> None:
    if expr is None:
        return
    elements = _list_elements(expr, names, 0)
    if elements is None:
        parts.append(PromptPart("unknown", None, expr.lineno, _short(ast.unparse(expr))))
        return
    for element, where in elements:
        _add_message(parts, element, where)


def _list_elements(
    expr: ast.expr, names: _Resolver, depth: int
) -> list[tuple[ast.expr, _Resolver]] | None:
    """The items of a list, following names, ``+`` and later appends.

    Each item comes with where to read it, since a list may come from another file.
    """
    if depth > _MAX_DEPTH:
        return None
    if isinstance(expr, ast.List | ast.Tuple):
        elements: list[tuple[ast.expr, _Resolver]] = []
        for element in expr.elts:
            if isinstance(element, ast.Starred):
                inner = _list_elements(element.value, names, depth + 1)
                elements.extend(inner if inner is not None else [(element.value, names)])
            else:
                elements.append((element, names))
        return elements
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
        left = _list_elements(expr.left, names, depth + 1)
        right = _list_elements(expr.right, names, depth + 1)
        if left is None and right is None:
            return None
        # A part we cannot read (``+ history``) stays in as one unknown item.
        return (left if left is not None else [(expr.left, names)]) + (
            right if right is not None else [(expr.right, names)]
        )
    if isinstance(expr, ast.Call):
        returned = _returned(expr, names)
        if returned is None:
            return None
        return _list_elements(returned[0], returned[1], depth + 1)
    found = names.value(expr)
    if found is None:
        return None
    result = _list_elements(found.value, found.where, depth + 1)
    if result is None:
        return None
    for extra in found.added:
        more = _list_elements(extra, found.where, depth + 1)
        result = result + (more if more is not None else [(extra, found.where)])
    return result


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
    target, names = _follow(element, names)
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


def _follow(expr: ast.expr, names: _Resolver) -> tuple[ast.expr, _Resolver]:
    """Follow a name to the value it was given, when there is one and nothing was added.

    Returns the value and where to read it (another file, for an imported name).
    """
    for _ in range(_MAX_DEPTH):
        if not isinstance(expr, ast.Name | ast.Attribute):
            return expr, names
        found = names.value(expr)
        if found is None or found.added:
            return expr, names
        expr, names = found.value, found.where
    return expr, names


def _string(expr: ast.expr, names: _Resolver) -> str | None:
    """The value of a plain string, through names; None for anything else."""
    target, _ = _follow(expr, names)
    if isinstance(target, ast.Constant) and isinstance(target.value, str):
        return target.value
    return None


def _model_value(expr: ast.expr, names: _Resolver) -> str | None:
    """A model ID written in the file: a string, a constant, or an env lookup's default."""
    target, names = _follow(expr, names)
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
    if found is not None:
        return found
    if isinstance(expr, ast.Name) and depth <= _MAX_DEPTH:
        bound = names.value(expr)
        if bound is not None and bound.argument:
            # Name the slot after the caller's code: {question}, not the parameter.
            return _template(bound.value, bound.where, depth + 1)
    return _slot(expr)


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
    target, _ = _follow(expr, names)
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
    if isinstance(expr, ast.Name | ast.Attribute):
        found = names.value(expr)
        if found is None:
            return None
        text = _known_template(found.value, found.where, depth + 1)
        if text is None:
            return None
        for extra in found.added:
            text += _template(extra, found.where, depth + 1)
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
            return _escape(sep).join(_filled(item, where, depth + 1) for item, where in items)
    if last in {"dedent", "cleandoc"} and len(call.args) == 1:
        inner = _known_template(call.args[0], names, depth + 1)
        if inner is None:
            return None
        return textwrap.dedent(inner) if last == "dedent" else inspect.cleandoc(inner)
    returned = _returned(call, names)
    if returned is None:
        return None
    return _known_template(returned[0], returned[1], depth + 1)


def _returned(call: ast.Call, names: _Resolver) -> tuple[ast.expr, _Resolver] | None:
    """What a call to a function of the app returns, read with the call's arguments.

    Only functions with a single ``return`` are read: ``def build(q): return f"Q: {q}"``
    called as ``build(question)`` gives ``Q: {question}``.
    """
    found = names.function(call.func)
    if found is None:
        return None
    function, passes_first = found
    returns = [
        n for n in _own_nodes(function.node) if isinstance(n, ast.Return) and n.value is not None
    ]
    if len(returns) != 1 or returns[0].value is None:
        return None
    arguments = _bind(function, passes_first, call, names)
    module = names.project.module_at(function.path)
    if arguments is None or module is None:
        return None
    ret = returns[0]
    assert ret.value is not None
    inner = _Resolver(function.scopes, ret.lineno, module, names.project, function.owner, arguments)
    return ret.value, inner


def _bind(
    function: _Function, passes_first: bool, call: ast.Call, names: _Resolver
) -> dict[str, tuple[ast.expr, _Resolver]] | None:
    """Bind a function's parameters to a call's arguments, then to their defaults.

    Arguments are read where the call is (``names``); defaults where the function is
    defined. None when the call uses ``*args``, since then we cannot tell which is which.
    """
    if any(isinstance(arg, ast.Starred) for arg in call.args):
        return None
    module = names.project.module_at(function.path)
    if module is None:
        return None
    node = function.node
    arguments: dict[str, tuple[ast.expr, _Resolver]] = {}
    params = node.args.posonlyargs + node.args.args
    if passes_first:
        params = params[1:]
    defaults = node.args.defaults
    outer = _Resolver(function.scopes[:-1], node.lineno, module, names.project, function.owner)
    positional = [p.arg for p in params]
    for param, default in zip(positional[len(positional) - len(defaults) :], defaults, strict=True):
        arguments[param] = (default, outer)
    for keyword_only, kw_default in zip(node.args.kwonlyargs, node.args.kw_defaults, strict=True):
        if kw_default is not None:
            arguments[keyword_only.arg] = (kw_default, outer)
    for param, arg in zip(positional, call.args, strict=False):
        arguments[param] = (arg, names)
    for keyword in call.keywords:
        if keyword.arg is not None:
            arguments[keyword.arg] = (keyword.value, names)
    return arguments


def _own_nodes(node: ast.AST) -> list[ast.AST]:
    """The nodes of a function body, without nested functions and classes."""
    found: list[ast.AST] = []
    stack = list(ast.iter_child_nodes(node))
    while stack:
        child = stack.pop()
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | ast.ClassDef):
            continue
        found.append(child)
        stack.extend(ast.iter_child_nodes(child))
    return found


def _raw_string(expr: ast.expr, names: _Resolver) -> str | None:
    """A plain string whose braces or % signs are placeholders (for .format and %)."""
    target, names = _follow(expr, names)
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
