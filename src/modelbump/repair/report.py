"""Reports for ``modelbump repair run``: one block per call, or full JSON (ADR 0064)."""

import json
from collections.abc import Sequence

from modelbump.repair.loop import CallRepair, LoopSettings
from modelbump.suite.run import Settings

JSON_VERSION = 1


def loop_line(settings: Settings, loop: LoopSettings) -> str:
    """What was compared, and how candidates were screened and confirmed."""
    best = "the best candidate" if loop.top == 1 else f"the best {loop.top} candidates"
    return (
        f"Repair {settings.old} -> {settings.new}: screen each candidate on "
        f"{loop.screen_runs} runs, confirm {best} on {loop.confirm_runs} fresh runs "
        f"(alpha {loop.alpha:.2f}, margin {loop.margin:.2f}, max gap {loop.max_gap:.2f})"
        + (f", free text judged by {settings.judge}." if settings.judge is not None else ".")
    )


def repair_summary(results: Sequence[CallRepair]) -> str:
    repaired = sum(r.patch is not None for r in results)
    return (
        f"Result: {repaired} of {len(results)} {'call' if len(results) == 1 else 'calls'} repaired."
    )


def _status(result: CallRepair) -> str:
    if result.patch is not None:
        return "REPAIRED"
    if not result.screened:
        return "NO CANDIDATES"
    if not result.confirmations and not result.skipped:
        return "NOT RUN"
    return "NOT REPAIRED"


def render_repair_text(
    results: Sequence[CallRepair], settings: Settings, loop: LoopSettings
) -> str:
    lines = [loop_line(settings, loop)]
    for result in results:
        lines.append(f"{_status(result):<13} {result.call}  ({result.cases} test cases)")
        if result.unpatched_mean is not None and result.old_mean is not None:
            lines.append(
                f"              screen: old {result.old_mean:.2f}, "
                f"unpatched new {result.unpatched_mean:.2f}"
            )
        for screened in result.screened:
            how = f"new {screened.new_mean:.2f}" if screened.error is None else screened.error
            lines.append(f"                {screened.file}: {how}")
        for file in result.skipped:
            screened = next(s for s in result.screened if s.file == file)
            lines.append(
                f"              confirm {file}: skipped, screen {screened.new_mean:.2f} is more "
                f"than {loop.max_gap:.2f} below old"
            )
        for confirmation in result.confirmations:
            verdict = "accepted" if confirmation.accepted else "rejected"
            lines.append(f"              confirm {confirmation.file}: {verdict}")
            if confirmation.error is not None:
                lines.append(f"                not run: {confirmation.error}")
            for check in confirmation.checks:
                sign = ">" if check.ok else "<="
                lines.append(
                    f"                {check.case_id}: old {check.old_passes}/{check.runs}, "
                    f"patched new {check.new_passes}/{check.runs}, "
                    f"lower bound {check.low:+.2f} {sign} -{loop.margin:.2f}"
                )
    lines.append(repair_summary(results))
    return "\n".join(lines) + "\n"


def render_repair_json(
    results: Sequence[CallRepair], settings: Settings, loop: LoopSettings
) -> str:
    data = {
        "version": JSON_VERSION,
        "old": settings.old,
        "new": settings.new,
        "old_version": settings.old_version,
        "new_version": settings.new_version,
        "judge": settings.judge,
        "judge_version": settings.judge_version,
        "reference": settings.reference,
        "temperature": settings.temperature,
        "max_tokens": settings.max_tokens,
        "screen_runs": loop.screen_runs,
        "confirm_runs": loop.confirm_runs,
        "top": loop.top,
        "alpha": loop.alpha,
        "margin": loop.margin,
        "max_gap": loop.max_gap,
        "calls": [
            {
                "call": r.call,
                "status": _status(r),
                "cases": r.cases,
                "regressed": list(r.regressed),
                "old_mean": r.old_mean,
                "unpatched_mean": r.unpatched_mean,
                "screened": [
                    {"file": s.file, "new_mean": round(s.new_mean, 4), "error": s.error}
                    for s in r.screened
                ],
                "confirmations": [
                    {
                        "file": c.file,
                        "accepted": c.accepted,
                        "error": c.error,
                        "checks": [
                            {
                                "case": k.case_id,
                                "old_passes": k.old_passes,
                                "new_passes": k.new_passes,
                                "runs": k.runs,
                                "low": round(k.low, 4),
                                "ok": k.ok,
                            }
                            for k in c.checks
                        ],
                    }
                    for c in r.confirmations
                ],
                "skipped": list(r.skipped),
                "accepted": None if r.accepted is None else r.accepted.file,
            }
            for r in results
        ],
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
