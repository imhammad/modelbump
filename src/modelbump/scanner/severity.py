"""How urgent a finding is, on a given day (ADR 0024)."""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from modelbump.registry import Registry

DEFAULT_SOON_DAYS = 90


class Severity(StrEnum):
    """Urgency levels, most urgent first."""

    RETIRED = "retired"
    """The shutdown day has passed: calls to this model fail now."""
    RETIRING_SOON = "retiring_soon"
    """The model shuts down within the warning window (90 days by default)."""
    DEPRECATED = "deprecated"
    """A shutdown is announced, but further away than the warning window."""
    UNKNOWN = "unknown"
    """No retirement is announced, so the registry has nothing to say."""


@dataclass(frozen=True, slots=True)
class Assessment:
    """What the registry says about one registry ID on one day."""

    severity: Severity
    shutdown: date | None = None
    shutdown_is_earliest: bool = False
    days_left: int | None = None
    """Days from the check day to the shutdown; 0 or less once retired."""
    replacement: str | None = None


def assess(
    registry_id: str | None,
    registry: Registry,
    today: date,
    soon_days: int = DEFAULT_SOON_DAYS,
) -> Assessment:
    """Assess ``registry_id`` as it stood on ``today``.

    A model whose deprecation was announced after ``today`` is UNKNOWN, since
    nobody could have known about it yet. This makes replays of past days
    honest (``modelbump scan --today``). The current plan is used even when an
    earlier plan was in force on ``today``.
    """
    found = registry.get(registry_id) if registry_id is not None else None
    if found is None:
        return Assessment(Severity.UNKNOWN)
    model = found[1]
    if model.announced is not None and today < model.announced:
        return Assessment(Severity.UNKNOWN)
    days_left = (model.shutdown - today).days
    if days_left <= 0:
        severity = Severity.RETIRED
    elif days_left <= soon_days:
        severity = Severity.RETIRING_SOON
    else:
        severity = Severity.DEPRECATED
    return Assessment(
        severity, model.shutdown, model.shutdown_is_earliest, days_left, model.replacement
    )
