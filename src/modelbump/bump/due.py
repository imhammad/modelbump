"""Which models in a repository are due for a bump (ADR 0072).

``modelbump bump-all`` and the scheduled GitHub Action bump every model that
is retired or shuts down within a window, to the replacement the registry
suggests, one pull request per model, the way Dependabot opens one per
package. A model is due when the code uses it (not only a comment names it),
it is retired or shuts down within ``within`` days, and the registry suggests
a replacement that is not retired itself. Models that are due but cannot be
bumped are listed with the reason.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from modelbump.registry import Registry
from modelbump.scanner import ScanResult, Severity, assess, scan_path
from modelbump.scanner.context import DOCUMENTATION

DEFAULT_WITHIN = 90


@dataclass(frozen=True, slots=True)
class DueModel:
    """A model the code uses that shuts down soon, and what to do about it."""

    old: str
    """The registry ID."""
    new: str | None
    """The suggested replacement, or None when the model cannot be bumped."""
    shutdown: date
    days_left: int
    places: int
    """How many places in the code use it (comments not counted)."""
    reason: str | None = None
    """Why it cannot be bumped, when ``new`` is None."""


def due_models(
    root: Path,
    registry: Registry,
    today: date,
    within: int = DEFAULT_WITHIN,
    exclude: Sequence[str] = (),
    result: ScanResult | None = None,
) -> list[DueModel]:
    """Every model under ``root`` that is due, soonest shutdown first.

    ``result`` is a scan of ``root`` already made, so a caller that plans the
    bumps too scans the repository once (ADR 0073).
    """
    if result is None:
        result = scan_path(root, registry, exclude)
    counts: dict[str, int] = {}
    for finding in result.findings:
        if finding.registry_id is None or finding.context in DOCUMENTATION:
            continue
        counts[finding.registry_id] = counts.get(finding.registry_id, 0) + 1
    due: list[DueModel] = []
    for old, places in counts.items():
        found = assess(old, registry, today, within)
        if found.severity not in (Severity.RETIRED, Severity.RETIRING_SOON):
            continue
        assert found.shutdown is not None and found.days_left is not None
        new, reason = found.replacement, None
        if new is None:
            reason = "the registry suggests no replacement; bump it by hand with --to"
        elif assess(new, registry, today).severity is Severity.RETIRED:
            new, reason = None, f"the suggested replacement {found.replacement} is retired too"
        due.append(DueModel(old, new, found.shutdown, found.days_left, places, reason))
    return sorted(due, key=lambda model: (model.shutdown, model.old))


def due_line(model: DueModel) -> str:
    """``claude-3-haiku-20240307 -> claude-haiku-4-5-20251001 (shut down 2026-04-20, 2 places)``."""
    when = (
        f"shut down {model.shutdown}"
        if model.days_left <= 0
        else f"shuts down {model.shutdown}, in {model.days_left} days"
    )
    places = f"{model.places} {'place' if model.places == 1 else 'places'}"
    target = model.new if model.new is not None else "?"
    return f"{model.old} -> {target} ({when}, {places})"
