"""Turn a scan into a report: text for people, JSON for scripts, SARIF for GitHub (ADR 0025)."""

import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any

from modelbump import __version__
from modelbump.registry import Registry
from modelbump.scanner.context import Context
from modelbump.scanner.scan import Finding, ScanResult
from modelbump.scanner.severity import DEFAULT_SOON_DAYS, Assessment, Severity, assess

SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
INFORMATION_URI = "https://github.com/imhammad/modelbump"
DOCS_URI = "https://imhammad.github.io/modelbump/architecture/scanner/"


class OutputFormat(StrEnum):
    """Report formats for ``modelbump scan --format``."""

    TEXT = "text"
    JSON = "json"
    SARIF = "sarif"


@dataclass(frozen=True, slots=True)
class AssessedFinding:
    """A finding together with what the registry says about it."""

    finding: Finding
    assessment: Assessment


@dataclass(frozen=True, slots=True)
class Report:
    """A scan, assessed on one day."""

    result: ScanResult
    items: tuple[AssessedFinding, ...]
    checked_on: date
    soon_days: int
    fail_within: int | None
    root_uri: str = ""
    """Where the scan root is, relative to the repository (``""`` or ``"sub/dir/"``).

    SARIF paths must be relative to the repository, while the other formats
    show paths relative to the scan root.
    """

    @property
    def counts(self) -> Counter[Severity]:
        """How many findings have each severity."""
        return Counter(item.assessment.severity for item in self.items)

    @property
    def failing(self) -> tuple[AssessedFinding, ...]:
        """Findings that are retired or shut down within ``fail_within`` days."""
        if self.fail_within is None:
            return ()
        limit = self.fail_within
        return tuple(
            item
            for item in self.items
            if item.assessment.days_left is not None and item.assessment.days_left <= limit
        )


def build_report(
    result: ScanResult,
    registry: Registry,
    checked_on: date,
    soon_days: int = DEFAULT_SOON_DAYS,
    fail_within: int | None = None,
    root_uri: str = "",
) -> Report:
    """Assess every finding of ``result`` on ``checked_on``."""
    items = tuple(
        AssessedFinding(f, assess(f.registry_id, registry, checked_on, soon_days))
        for f in result.findings
    )
    return Report(result, items, checked_on, soon_days, fail_within, root_uri)


# Text ------------------------------------------------------------------------


def render_text(report: Report) -> str:
    """One line per finding, then a summary line (and a failure line)."""
    lines = []
    for item in report.items:
        finding = item.finding
        written = finding.model_id
        if finding.registry_id is not None and finding.registry_id != written:
            written += f" (= {finding.registry_id})"
        line = (
            f"{finding.path}:{finding.line}:{finding.column}  {written}  "
            f"{item.assessment.severity.name}  {describe(item.assessment)}"
        )
        place = where(finding)
        if place:
            line += f"  [{place}]"
        lines.append(line)
    lines.append(summary_line(report))
    failure = failure_line(report)
    if failure:
        lines.append(failure)
    return "\n".join(lines) + "\n"


def summary_line(report: Report) -> str:
    """For example ``Found 3 model IDs in 2 files (scanned 5 files): 1 RETIRED, 2 UNKNOWN.``"""
    result = report.result
    files = f"scanned {plural(result.files_scanned, 'file')}"
    if result.files_skipped:
        files += f", skipped {result.files_skipped} too big or binary"
    if not report.items:
        return f"No model IDs found ({files})."
    ids = plural(len(report.items), "model ID")
    in_files = plural(len({item.finding.path for item in report.items}), "file")
    counts = report.counts
    levels = ", ".join(f"{counts[s]} {s.name}" for s in Severity if counts[s])
    return f"Found {ids} in {in_files} ({files}): {levels}."


def failure_line(report: Report) -> str | None:
    """The line explaining a failed scan, or None if it passed."""
    failing = len(report.failing)
    if not failing:
        return None
    verb = "is" if failing == 1 else "are"
    return (
        f"Failed: {plural(failing, 'model ID')} {verb} retired "
        f"or shut down within {plural(report.fail_within or 0, 'day')}."
    )


def describe(assessment: Assessment) -> str:
    """A short sentence about a finding's shutdown and replacement."""
    if assessment.shutdown is None or assessment.days_left is None:
        return "no retirement announced"
    days = assessment.days_left
    if days <= 0:
        text = f"shut down on {assessment.shutdown}"
        if assessment.shutdown_is_earliest:
            text = f"shut down no earlier than {assessment.shutdown}"
    else:
        when = "no earlier than" if assessment.shutdown_is_earliest else "on"
        text = f"shuts down {when} {assessment.shutdown} (in {plural(days, 'day')})"
    if assessment.replacement:
        text += f"; suggested replacement {assessment.replacement}"
    return text


def where(finding: Finding) -> str | None:
    """Where the ID sits, in words: ``assigned to MODEL``, ``in a comment``, ..."""
    context, detail = finding.context, finding.detail
    if context is Context.COMMENT:
        return "in a comment"
    if context is Context.DOCSTRING:
        return "in a docstring"
    if detail is None:
        return None
    if context is Context.CALL_ARGUMENT:
        return f"in {detail}"
    if context is Context.ASSIGNMENT:
        return f"assigned to {detail}"
    return f"value of {detail}"


def plural(count: int, word: str) -> str:
    """``1 file``, ``2 files``."""
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


# JSON ------------------------------------------------------------------------


def render_json(report: Report) -> str:
    """Every finding and its assessment, for scripts and the replay experiment."""
    counts = report.counts
    data: dict[str, Any] = {
        "tool": "modelbump",
        "version": __version__,
        "checked_on": report.checked_on.isoformat(),
        "soon_days": report.soon_days,
        "fail_within": report.fail_within,
        "failed": bool(report.failing),
        "files_scanned": report.result.files_scanned,
        "files_skipped": report.result.files_skipped,
        "summary": {s.value: counts[s] for s in Severity},
        "findings": [_finding_json(item) for item in report.items],
    }
    return json.dumps(data, indent=2) + "\n"


def _finding_json(item: AssessedFinding) -> dict[str, Any]:
    finding, assessment = item.finding, item.assessment
    return {
        "path": finding.path,
        "line": finding.line,
        "column": finding.column,
        "model_id": finding.model_id,
        "registry_id": finding.registry_id,
        "severity": assessment.severity.value,
        "shutdown": assessment.shutdown.isoformat() if assessment.shutdown else None,
        "shutdown_is_earliest": assessment.shutdown_is_earliest,
        "days_left": assessment.days_left,
        "replacement": assessment.replacement,
        "context": finding.context.value,
        "detail": finding.detail,
    }


# SARIF -----------------------------------------------------------------------

# UNKNOWN findings are not problems, so they are left out of SARIF: GitHub
# would show each one as an alert (ADR 0025).
_SARIF_RULES: Sequence[tuple[Severity, str, str, str]] = (
    (
        Severity.RETIRED,
        "error",
        "Model is retired",
        "The provider has shut this model down, so API calls to it fail.",
    ),
    (
        Severity.RETIRING_SOON,
        "warning",
        "Model retires soon",
        "The provider shuts this model down within the warning window.",
    ),
    (
        Severity.DEPRECATED,
        "note",
        "Model is deprecated",
        "The provider has announced a shutdown date for this model.",
    ),
)


def rule_id(severity: Severity) -> str:
    """SARIF rule ID for a severity, for example ``modelbump/retired``."""
    return f"modelbump/{severity.value.replace('_', '-')}"


def render_sarif(report: Report) -> str:
    """SARIF 2.1.0, the format GitHub code scanning reads.

    Paths start with ``root_uri``, so they are relative to the repository
    when ``modelbump scan`` runs from the repository root.
    """
    rules = [
        {
            "id": rule_id(severity),
            "name": name.title().replace(" ", ""),
            "shortDescription": {"text": name},
            "fullDescription": {"text": full},
            "helpUri": DOCS_URI,
            "defaultConfiguration": {"level": level},
        }
        for severity, level, name, full in _SARIF_RULES
    ]
    index = {severity: i for i, (severity, *_rest) in enumerate(_SARIF_RULES)}
    levels = {severity: level for severity, level, *_rest in _SARIF_RULES}
    results = []
    for item in report.items:
        severity = item.assessment.severity
        if severity not in index:
            continue
        finding = item.finding
        results.append(
            {
                "ruleId": rule_id(severity),
                "ruleIndex": index[severity],
                "level": levels[severity],
                "message": {
                    "text": f"{finding.model_id}{_where_suffix(finding)}: "
                    f"{describe(item.assessment)} (checked on {report.checked_on})."
                },
                "properties": {"context": finding.context.value, "detail": finding.detail},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {
                                "uri": report.root_uri + finding.path,
                                "uriBaseId": "%SRCROOT%",
                            },
                            "region": {
                                "startLine": finding.line,
                                "startColumn": finding.column,
                                "endColumn": finding.column + len(finding.model_id),
                            },
                        }
                    }
                ],
            }
        )
    sarif = {
        "$schema": SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "ModelBump",
                        "version": __version__,
                        "informationUri": INFORMATION_URI,
                        "rules": rules,
                    }
                },
                "results": results,
            }
        ],
    }
    return json.dumps(sarif, indent=2) + "\n"


def _where_suffix(finding: Finding) -> str:
    place = where(finding)
    return f" ({place})" if place else ""


RENDERERS = {
    OutputFormat.TEXT: render_text,
    OutputFormat.JSON: render_json,
    OutputFormat.SARIF: render_sarif,
}
