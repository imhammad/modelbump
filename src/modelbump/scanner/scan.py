"""Scan a repository, or one file, for model IDs."""

from dataclasses import dataclass
from pathlib import Path

from modelbump.registry import Registry
from modelbump.scanner.files import iter_source_files, read_source
from modelbump.scanner.ids import ModelIdFinder


@dataclass(frozen=True, slots=True)
class Finding:
    """One model ID at one place in the scanned code."""

    path: str
    """File path relative to the scan root, with ``/`` separators."""
    line: int
    column: int
    model_id: str
    in_registry: bool


@dataclass(frozen=True, slots=True)
class ScanResult:
    """Everything one scan found."""

    findings: tuple[Finding, ...]
    files_scanned: int
    files_skipped: int
    """Files with a code or config name that were too big or binary."""


def scan_path(root: Path, registry: Registry) -> ScanResult:
    """Scan ``root`` (a folder or a single file) for model IDs.

    A file given directly is scanned whatever its name; a folder is walked
    with the rules in :mod:`modelbump.scanner.files`.
    """
    finder = ModelIdFinder(model_id for _, model in registry for model_id in model.all_ids())
    if root.is_file():
        paths = [root]
        base = root.parent
    else:
        paths = list(iter_source_files(root))
        base = root
    findings: list[Finding] = []
    scanned = skipped = 0
    for path in paths:
        text = read_source(path)
        if text is None:
            skipped += 1
            continue
        scanned += 1
        rel = path.relative_to(base).as_posix()
        findings.extend(
            Finding(rel, m.line, m.column, m.model_id, m.in_registry) for m in finder.find(text)
        )
    return ScanResult(tuple(findings), scanned, skipped)
