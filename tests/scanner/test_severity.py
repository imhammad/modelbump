"""Tests for the severity of a finding on a given day."""

from datetime import date

import pytest

from modelbump.registry import load_registry
from modelbump.scanner import Assessment, Severity, assess

# claude-3-haiku-20240307: announced 2026-02-19, shut down 2026-04-20.
HAIKU = "claude-3-haiku-20240307"


@pytest.mark.parametrize(
    ("day", "severity", "days_left"),
    [
        (date(2026, 2, 18), Severity.UNKNOWN, None),  # before the notice
        (date(2026, 2, 19), Severity.RETIRING_SOON, 60),  # notice day
        (date(2026, 4, 19), Severity.RETIRING_SOON, 1),
        (date(2026, 4, 20), Severity.RETIRED, 0),  # shutdown day
        (date(2026, 10, 22), Severity.RETIRED, -185),
    ],
)
def test_severity_follows_the_timeline(
    day: date, severity: Severity, days_left: int | None
) -> None:
    result = assess(HAIKU, load_registry(), day)
    assert result.severity is severity
    assert result.days_left == days_left


def test_far_shutdown_is_deprecated_and_window_is_adjustable() -> None:
    registry = load_registry()
    assert assess(HAIKU, registry, date(2026, 2, 19), soon_days=30).severity is Severity.DEPRECATED
    assert assess(HAIKU, registry, date(2026, 2, 19), soon_days=60).severity is (
        Severity.RETIRING_SOON
    )


def test_assessment_carries_dates_and_replacement() -> None:
    assert assess(HAIKU, load_registry(), date(2026, 4, 1)) == Assessment(
        Severity.RETIRING_SOON,
        shutdown=date(2026, 4, 20),
        shutdown_is_earliest=False,
        days_left=19,
        replacement="claude-haiku-4-5-20251001",
    )


def test_ids_without_a_retirement_are_unknown() -> None:
    registry = load_registry()
    assert assess(None, registry, date(2026, 10, 22)) == Assessment(Severity.UNKNOWN)
    assert assess("gpt-9-turbo", registry, date(2026, 10, 22)) == Assessment(Severity.UNKNOWN)


def test_google_dates_are_earliest_possible() -> None:
    result = assess("gemini-3.1-flash-lite", load_registry(), date(2026, 10, 22))
    assert result.severity is Severity.DEPRECATED
    assert result.shutdown_is_earliest
