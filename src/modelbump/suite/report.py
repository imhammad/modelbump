"""Reports for ``modelbump test``: a verdict per case, worst first, or full JSON."""

import json

from modelbump.stats import Verdict
from modelbump.suite.run import CaseRun, Method, SuiteRun

JSON_VERSION = 1
_ORDER = {
    Verdict.REGRESSED: 0,
    Verdict.INCONCLUSIVE: 1,
    Verdict.EQUIVALENT: 2,
    Verdict.IMPROVED: 3,
}


def method_line(result: SuiteRun) -> str:
    """What was compared, and how."""
    s = result.settings
    chosen = s.chosen
    how = (
        f"fixed k={s.runs} + BH" if chosen is Method.FIXED else f"sequential + e-BH, up to {s.runs}"
    )
    cases = len(result.cases)
    return (
        f"Compared {s.old} -> {s.new} on {cases} test {'case' if cases == 1 else 'cases'}: "
        f"{how} (q {s.q:.2f}, margin {s.margin:.2f}), "
        f"{s.reference} reference {'answer' if s.reference == 1 else 'answers'} per case"
        + (f", free text judged by {s.judge}." if s.judge is not None else ".")
    )


def run_summary(result: SuiteRun) -> str:
    """One line: how many cases got each verdict."""
    counts = result.counts
    parts = [f"{counts[v]} {v.value.lower()}" for v in _ORDER]
    line = f"Result: {', '.join(parts)}."
    if result.errors:
        line += f" {result.errors} could not be run."
    return line


def _sorted(result: SuiteRun) -> list[CaseRun]:
    return sorted(
        result.cases,
        key=lambda run: (run.error is not None, _ORDER[run.verdict], run.new_mean - run.old_mean),
    )


def render_run_text(result: SuiteRun) -> str:
    """One line per case, worst first, with the checks the new model failed most."""
    lines = [method_line(result)]
    for run in _sorted(result):
        case = run.case
        if run.error is not None:
            lines.append(f"NOT RUN      {case.id}  {case.oracle.kind.value}  {run.error}")
            continue
        lines.append(
            f"{run.verdict.value:<12} {case.id}  {case.oracle.kind.value}  "
            f"old {run.old_mean:.2f} -> new {run.new_mean:.2f}  ({len(run.new)} runs)"
        )
        failures = run.new_failures
        if failures and run.verdict is not Verdict.EQUIVALENT:
            top = ", ".join(f"{name} ({times}/{len(run.new)})" for name, times in failures[:2])
            lines.append(f"             new model failed: {top}")
    lines.append(run_summary(result))
    return "\n".join(lines) + "\n"


def render_run_json(result: SuiteRun) -> str:
    """Every case with every answer and score, for checking by hand and the judge step."""
    s = result.settings
    data = {
        "version": JSON_VERSION,
        "old": s.old,
        "new": s.new,
        "old_version": s.old_version,
        "new_version": s.new_version,
        "method": s.chosen.value,
        "runs": s.runs,
        "reference": s.reference,
        "q": s.q,
        "margin": s.margin,
        "temperature": s.temperature,
        "max_tokens": s.max_tokens,
        "judge": s.judge,
        "judge_version": s.judge_version,
        "counts": {v.value: result.counts[v] for v in _ORDER},
        "cases": [
            {
                "id": run.case.id,
                "kind": run.case.oracle.kind.value,
                "source": run.case.source,
                "verdict": None if run.error is not None else run.verdict.value,
                "error": run.error,
                "old_mean": round(run.old_mean, 4),
                "new_mean": round(run.new_mean, 4),
                "new_failures": dict(run.new_failures),
                "answers": [
                    {
                        "model": which,
                        "sample": answer.sample,
                        "score": round(answer.score.value, 4),
                        "failed": list(answer.score.failed),
                        "judge": answer.judge,
                        "text": answer.text,
                    }
                    for which, answers in (("old", run.old), ("new", run.new))
                    for answer in answers
                ],
            }
            for run in _sorted(result)
        ],
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
