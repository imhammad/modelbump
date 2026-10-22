"""Tests for the text, JSON and SARIF reports."""

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from modelbump import __version__
from modelbump.registry import load_registry
from modelbump.scanner import Severity, scan_path
from modelbump.scanner.report import (
    Report,
    build_report,
    render_json,
    render_sarif,
    render_text,
    rule_id,
)

DAY = date(2026, 10, 22)


@pytest.fixture
def report(tmp_path: Path) -> Report:
    (tmp_path / "app.py").write_text(
        'A = "claude-3-haiku-20240307"\nB = "gpt-9-turbo"\nC = "gpt-5.1"\n'
    )
    registry = load_registry()
    return build_report(scan_path(tmp_path, registry), registry, DAY, fail_within=30)


def test_report_counts_and_failing(report: Report) -> None:
    assert report.counts == {Severity.RETIRED: 1, Severity.UNKNOWN: 1, Severity.DEPRECATED: 1}
    assert [item.finding.model_id for item in report.failing] == ["claude-3-haiku-20240307"]


def test_text_report_ends_with_summary_and_failure(report: Report) -> None:
    lines = render_text(report).splitlines()
    assert lines[-2] == (
        "Found 3 model IDs in 1 file (scanned 1 file): 1 RETIRED, 1 DEPRECATED, 1 UNKNOWN."
    )
    assert lines[-1] == "Failed: 1 model ID is retired or shut down within 30 days."


def test_json_report(report: Report) -> None:
    data = json.loads(render_json(report))
    assert data["version"] == __version__
    assert data["checked_on"] == "2026-10-22"
    assert (data["soon_days"], data["fail_within"], data["failed"]) == (90, 30, True)
    assert data["summary"] == {"retired": 1, "retiring_soon": 0, "deprecated": 1, "unknown": 1}
    assert data["findings"][0] == {
        "path": "app.py",
        "line": 1,
        "column": 6,
        "model_id": "claude-3-haiku-20240307",
        "registry_id": "claude-3-haiku-20240307",
        "severity": "retired",
        "shutdown": "2026-04-20",
        "shutdown_is_earliest": False,
        "days_left": -185,
        "replacement": "claude-haiku-4-5-20251001",
    }
    assert data["findings"][1]["shutdown"] is None


def sarif_results(report: Report) -> list[dict[str, Any]]:
    run = json.loads(render_sarif(report))["runs"][0]
    results: list[dict[str, Any]] = run["results"]
    return results


def test_sarif_report_structure(report: Report) -> None:
    sarif = json.loads(render_sarif(report))
    assert sarif["version"] == "2.1.0"
    driver = sarif["runs"][0]["tool"]["driver"]
    assert (driver["name"], driver["version"]) == ("ModelBump", __version__)
    assert [rule["id"] for rule in driver["rules"]] == [
        "modelbump/retired",
        "modelbump/retiring-soon",
        "modelbump/deprecated",
    ]


def test_sarif_leaves_out_unknown_ids(report: Report) -> None:
    results = sarif_results(report)
    assert [(r["ruleId"], r["level"]) for r in results] == [
        ("modelbump/retired", "error"),
        ("modelbump/deprecated", "note"),
    ]
    first = results[0]
    assert first["ruleIndex"] == 0
    assert first["message"]["text"] == (
        "claude-3-haiku-20240307: shut down on 2026-04-20; suggested replacement "
        "claude-haiku-4-5-20251001 (checked on 2026-10-22)."
    )
    location = first["locations"][0]["physicalLocation"]
    assert location["artifactLocation"] == {"uri": "app.py", "uriBaseId": "%SRCROOT%"}
    assert location["region"] == {"startLine": 1, "startColumn": 6, "endColumn": 29}
    assert results[1]["ruleIndex"] == 2


def test_rule_ids() -> None:
    assert rule_id(Severity.RETIRING_SOON) == "modelbump/retiring-soon"
