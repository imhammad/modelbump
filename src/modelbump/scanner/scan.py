"""Scan a repository, or one file, for model IDs."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from modelbump.registry import Registry
from modelbump.scanner.context import DOCUMENTATION, Context, places
from modelbump.scanner.files import is_test_path, iter_source_files, read_source
from modelbump.scanner.ids import ModelIdFinder
from modelbump.scanner.resolve import resolve


@dataclass(frozen=True, slots=True)
class Finding:
    """One model ID at one place in the scanned code."""

    path: str
    """File path relative to the scan root, with ``/`` separators."""
    line: int
    column: int
    model_id: str
    """The ID exactly as written in the file."""
    registry_id: str | None
    """The registry ID it refers to (see :mod:`modelbump.scanner.resolve`), or None."""
    context: Context = Context.TEXT
    """Where in the file the ID is (see :mod:`modelbump.scanner.context`)."""
    detail: str | None = None
    """The call, name or key it belongs to, such as ``client.messages.create(model=)``."""


@dataclass(frozen=True, slots=True)
class ScanResult:
    """Everything one scan found."""

    findings: tuple[Finding, ...]
    files_scanned: int
    files_skipped: int
    """Files with a code or config name that were too big or binary."""


def scan_path(
    root: Path,
    registry: Registry,
    exclude: Sequence[str] = (),
    skip_comments: bool = False,
    skip_tests: bool = False,
) -> ScanResult:
    """Scan ``root`` (a folder or a single file) for model IDs.

    A file given directly is scanned whatever its name; a folder is walked
    with the rules in :mod:`modelbump.scanner.files`, skipping paths that match
    an ``exclude`` pattern. ``skip_comments`` leaves out IDs that only describe
    a model (comments, docstrings, sentences and price tables), and
    ``skip_tests`` leaves out test files and test folders.
    """
    finder = ModelIdFinder(model_id for _, model in registry for model_id in model.all_ids())
    if root.is_file():
        paths = [root]
        base = root.parent
    else:
        paths = list(iter_source_files(root, exclude))
        base = root
    if skip_tests:
        paths = [p for p in paths if not is_test_path(p.relative_to(base).as_posix())]
    findings: list[Finding] = []
    scanned = skipped = 0
    for path in paths:
        text = read_source(path)
        if text is None:
            skipped += 1
            continue
        scanned += 1
        matches = list(finder.find(text))
        if not matches:
            continue
        rel = path.relative_to(base).as_posix()
        spots = [(m.line, m.column, len(m.model_id)) for m in matches]
        for match, place in zip(matches, places(rel, text, spots), strict=True):
            if skip_comments and place.context in DOCUMENTATION:
                continue
            findings.append(
                Finding(
                    rel,
                    match.line,
                    match.column,
                    match.model_id,
                    resolve(match.model_id, registry),
                    place.context,
                    place.detail,
                )
            )
    return ScanResult(tuple(findings), scanned, skipped)
