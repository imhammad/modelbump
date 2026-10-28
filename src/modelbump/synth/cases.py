"""Test inputs for an app's LLM calls, from the values its own code passes in (ADR 0050).

A call site from :mod:`modelbump.synth.callsites` has slots such as
``{ticket}`` where the app puts in a value at run time. When the call sits in
a function, the app's tests and examples often call that function with real
values: ``classify(client, "The app crashes on login")``, or a
``pytest.mark.parametrize`` row. Each such call is a test case: the call
site read again with the function's parameters bound to that caller's
arguments. A case is *complete* when every slot got a value, so its messages
can be sent to a model as they are.

This module uses the resolver of :mod:`modelbump.synth.callsites`, so a value
is followed the same way a prompt is: through names, constants, imports and
the app's own functions.
"""

import ast
import itertools
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from modelbump.scanner.files import is_test_path
from modelbump.synth.callsites import (
    CallSite,
    _bind,
    _call_site,
    _CallRecord,
    _chain,
    _excluded,
    _follow,
    _Function,
    _known_template,
    _Module,
    _Project,
    _read_sources,
    _Resolver,
    _short,
    render,
    slot_names,
)

MAX_ROWS = 50
"""At most this many parametrize rows are read per test function."""


@dataclass(frozen=True, slots=True)
class TestCase:
    """One set of inputs for a call site, found where the app's code calls it."""

    site: CallSite
    """The call site with its templates filled in from this caller."""
    source: str
    """Where the values come from: ``tests/test_support.py:12``."""
    values: tuple[tuple[str, str], ...]
    """The call site's slots that got a value, with the value, in slot order."""
    generated_by: str | None = None
    """The model that wrote the values (ADR 0051), or None for values from the app's code."""

    __test__ = False  # not a pytest test class

    @property
    def complete(self) -> bool:
        """True when every message has its full text, with no slot left."""
        return self.site.complete and not self.site.slots

    @property
    def messages(self) -> tuple[tuple[str, str], ...]:
        """``(role, text)`` for each message, ready to send. Only for complete cases."""
        if not self.complete:
            raise ValueError("A case with open slots has no final messages.")
        return tuple((part.role, render(part.template or "", {})) for part in self.site.parts)


@dataclass(frozen=True, slots=True)
class SiteCases:
    """A call site and the test cases found for it."""

    site: CallSite
    cases: tuple[TestCase, ...]


@dataclass(frozen=True, slots=True)
class CaseResult:
    """Everything one search for test cases found."""

    sites: tuple[SiteCases, ...]
    files_read: int
    unparsed: tuple[str, ...] = ()

    @property
    def cases(self) -> tuple[TestCase, ...]:
        return tuple(case for site in self.sites for case in site.cases)


def find_cases(root: Path, exclude: Sequence[str] = (), skip_tests: bool = False) -> CaseResult:
    """Find each LLM call under ``root`` and the test cases its app's code gives it.

    ``exclude`` and ``skip_tests`` choose which call sites are listed. Callers are
    looked for in every Python file, tests above all, whatever those options say.
    """
    project = _Project(_read_sources(root))
    listed: list[tuple[_Module, _CallRecord, CallSite]] = []
    unparsed: list[str] = []
    read = 0
    for path in project.sources:
        if (skip_tests and is_test_path(path)) or _excluded(path, exclude):
            continue
        read += 1
        module = project.module_at(path)
        if module is None:
            unparsed.append(path)
            continue
        for record in module.calls:
            names = _Resolver(record.scopes, record.call.lineno, module, project, record.owner)
            site = _call_site(module.path, record.call, names)
            if site is not None:
                listed.append((module, record, site))
    callers = _callers(project, {id(r.function) for _, r, _ in listed if r.function is not None})
    sites = []
    for module, record, site in listed:
        found: list[TestCase] = []
        if record.function is not None and site.slots:
            for caller, names, passes_first, line in callers.get(id(record.function), []):
                case = _case(module, record, site, caller, names, passes_first, line)
                if case is not None and all(case.site != c.site for c in found):
                    found.append(case)
        sites.append(SiteCases(site, tuple(found)))
    return CaseResult(tuple(sites), read, tuple(unparsed))


def _callers(
    project: _Project, wanted: set[int]
) -> dict[int, list[tuple[ast.Call, _Resolver, bool, int]]]:
    """Every call, in every file, of the functions in ``wanted`` (by id).

    A call inside a test with ``pytest.mark.parametrize`` comes once per row,
    with the test's parameters bound to that row. Each call comes with the line
    its values are on: the call, or the parametrize row.
    """
    found: dict[int, list[tuple[ast.Call, _Resolver, bool, int]]] = {}
    for path in project.sources:
        module = project.module_at(path)
        if module is None:
            continue
        for record in module.calls:
            for names, line in _caller_resolvers(module, record, project):
                target = names.function(record.call.func)
                if target is not None and id(target[0]) in wanted:
                    found.setdefault(id(target[0]), []).append(
                        (record.call, names, target[1], line)
                    )
    return found


def _caller_resolvers(
    module: _Module, record: _CallRecord, project: _Project
) -> Iterator[tuple[_Resolver, int]]:
    """Where to read a caller's arguments: once, or once per parametrize row."""
    line = record.call.lineno
    rows = list(_parametrize_rows(module, record.function, project))
    if not rows:
        yield _Resolver(record.scopes, line, module, project, record.owner), line
        return
    for row in rows:
        row_line = min(expr.lineno for expr, _ in row.values())
        yield _Resolver(record.scopes, line, module, project, record.owner, row), row_line


def _parametrize_rows(
    module: _Module, function: _Function | None, project: _Project
) -> Iterator[dict[str, tuple[ast.expr, _Resolver]]]:
    """The rows of ``@pytest.mark.parametrize`` decorators, as parameter bindings.

    Several decorators multiply, as in pytest. Rows that cannot be read are skipped.
    """
    if function is None:
        return
    outer = _Resolver(function.scopes[:-1], function.node.lineno, module, project, function.owner)
    tables: list[list[dict[str, tuple[ast.expr, _Resolver]]]] = []
    for decorator in function.node.decorator_list:
        if not isinstance(decorator, ast.Call) or _chain(decorator.func)[-1:] != ["parametrize"]:
            continue
        table = _parametrize_table(decorator, outer)
        if table:
            tables.append(table)
    for combination in itertools.islice(itertools.product(*tables), MAX_ROWS) if tables else ():
        row: dict[str, tuple[ast.expr, _Resolver]] = {}
        for part in combination:
            row.update(part)
        yield row


def _parametrize_table(
    decorator: ast.Call, outer: _Resolver
) -> list[dict[str, tuple[ast.expr, _Resolver]]]:
    if len(decorator.args) < 2:
        return []
    names_expr, values_expr = decorator.args[0], decorator.args[1]
    if isinstance(names_expr, ast.Constant) and isinstance(names_expr.value, str):
        names = [n.strip() for n in names_expr.value.split(",") if n.strip()]
    elif isinstance(names_expr, ast.List | ast.Tuple) and all(
        isinstance(e, ast.Constant) and isinstance(e.value, str) for e in names_expr.elts
    ):
        names = [str(e.value) for e in names_expr.elts if isinstance(e, ast.Constant)]
    else:
        return []
    found = outer.value(values_expr) if isinstance(values_expr, ast.Name) else None
    values, where = (found.value, found.where) if found is not None else (values_expr, outer)
    if not isinstance(values, ast.List | ast.Tuple):
        return []
    table = []
    for row in values.elts[:MAX_ROWS]:
        if isinstance(row, ast.Call) and _chain(row.func)[-1:] == ["param"]:
            items = list(row.args)
        elif len(names) > 1 and isinstance(row, ast.Tuple | ast.List):
            items = list(row.elts)
        else:
            items = [row]
        if len(names) > 1 and len(items) == 1 and isinstance(items[0], ast.Tuple | ast.List):
            items = list(items[0].elts)  # pytest.param((a, b)) is rare, but cheap to read
        if len(items) != len(names):
            continue
        table.append({name: (item, where) for name, item in zip(names, items, strict=True)})
    return table


def _case(
    module: _Module,
    record: _CallRecord,
    site: CallSite,
    caller: ast.Call,
    names: _Resolver,
    passes_first: bool,
    line: int,
) -> TestCase | None:
    """Read a call site again with its function's parameters bound to one caller's values."""
    assert record.function is not None
    arguments = _bind(record.function, passes_first, caller, names)
    if arguments is None:
        return None
    filled_names = _Resolver(
        record.scopes, record.call.lineno, module, names.project, record.owner, arguments
    )
    filled = _call_site(module.path, record.call, filled_names)
    if filled is None:
        return None
    values = []
    for slot in site.slots:
        if slot not in arguments or slot in filled.slots:
            continue
        expr, where = arguments[slot]
        if where is not names:
            continue  # a default value: the plain call site could have it too
        text = _value_text(expr, where)
        if text is not None:
            values.append((slot, text))
    if not values:
        return None
    return TestCase(filled, f"{names.module.path}:{line}", tuple(values))


def _value_text(expr: ast.expr, names: _Resolver) -> str | None:
    """A short text for a known value: the string, a number, or the code of a literal list.

    None when the value is not in the code (a variable of the caller, say).
    """
    text = _known_template(expr, names, 0)
    if text is not None:
        return render(text, {}) if not slot_names(text) else None
    target, _ = _follow(expr, names)
    if isinstance(target, ast.Constant) and not isinstance(target.value, bool):
        return str(target.value)
    if isinstance(target, ast.List | ast.Tuple | ast.Dict | ast.Set):
        return _short(ast.unparse(target))
    return None


__all__ = ["MAX_ROWS", "CaseResult", "SiteCases", "TestCase", "find_cases"]
