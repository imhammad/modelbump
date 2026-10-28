"""Reports for ``modelbump oracles``: the oracle picked for each call, and why."""

import json
from collections import Counter

from modelbump.oracles.choose import OracleChoice, OutputKind, choose_oracle
from modelbump.synth.callsites import CallSite, CallSiteResult

JSON_VERSION = 1

CHECKS = {
    OutputKind.JSON: (
        "valid JSON",
        "same type and keys as before",
        "values the old model always gave are kept",
    ),
    OutputKind.LABEL: ("one of the labels", "same label as before"),
    OutputKind.TEXT: (
        "not empty",
        "not a refusal",
        "length like before",
        "keeps list and code format",
        "keeps a word or sentence limit in the prompt",
    ),
    OutputKind.TOOLS: (),
}
"""The checks of each kind, in words, for the report (see ``oracles.score``)."""


def choices(result: CallSiteResult) -> list[tuple[CallSite, OracleChoice]]:
    """Each call with the oracle picked for it."""
    return [(call, choose_oracle(call)) for call in result.calls]


def oracles_summary(result: CallSiteResult) -> str:
    """One line: how many calls got each kind of oracle."""
    counts = Counter(choice.kind for _, choice in choices(result))
    calls = len(result.calls)
    kinds = ", ".join(f"{counts[kind]} {kind.value}" for kind in OutputKind if counts[kind])
    line = f"Picked oracles for {calls} LLM {'call' if calls == 1 else 'calls'}"
    line += f": {kinds}." if kinds else "."
    if counts[OutputKind.TOOLS]:
        line += " Tool calls are not scored yet."
    return line


def render_oracles_text(result: CallSiteResult) -> str:
    """Each call, its oracle, the reason, and the checks that oracle runs."""
    lines: list[str] = []
    for call, choice in choices(result):
        lines.append(f"{call.path}:{call.line}  {call.api.value}  {choice.kind.value}")
        lines.append(f"  why: {choice.reason}")
        if CHECKS[choice.kind]:
            lines.append(f"  checks: {', '.join(CHECKS[choice.kind])}")
    lines.append(oracles_summary(result))
    return "\n".join(lines) + "\n"


def render_oracles_json(result: CallSiteResult) -> str:
    """Each call's oracle, for the next steps."""
    data = {
        "version": JSON_VERSION,
        "calls": [
            {
                "path": call.path,
                "line": call.line,
                "api": call.api.value,
                "model": call.model,
                "kind": choice.kind.value,
                "reason": choice.reason,
                "labels": list(choice.labels),
                "checks": list(CHECKS[choice.kind]),
            }
            for call, choice in choices(result)
        ],
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
