"""Candidate patches written by a local model, from the answers that regressed (ADR 0063).

For each LLM call with a REGRESSED case in a ``modelbump test --format json``
report, a proposer model sees the app's prompt, the old model's reference
answer and a few of the new model's failing answers with the checks they
failed. It answers with one patch as JSON. Several samples give several
candidates. Each candidate is checked against the suite before it is kept, so
every written candidate can be shown and tested as it is (ADR 0062).

Proposing only writes candidates. Nothing here says a candidate works: the
repair loop tests them on fresh answers (ADR 0064).

Strategies (ADR 0065): ``evidence`` (the default, above) and ``naive``, a
baseline that sees only the prompt and the two model names. The third,
``iterative``, needs model answers and lives in ``optimize.py``.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from modelbump.repair.patch import (
    Edit,
    PatchError,
    PromptPatch,
    apply_patches,
    call_of,
    patches_to_json,
)
from modelbump.runner import ChatRequest, ChatResult, Message, Runner, RunnerError
from modelbump.suite.file import Suite, SuiteCase

DEFAULT_PROPOSER = "ollama/gemma3:12b"
DEFAULT_CANDIDATES = 5
TEMPERATURE = 0.8
MAX_TOKENS = 600
FAILURES_SHOWN = 3
MESSAGE_CHARS = 4000
ANSWER_CHARS = 800

SYSTEM = (
    "You fix prompts for software that calls a large language model. "
    "You reply with JSON only, no other text."
)


class Strategy(StrEnum):
    """How candidates are written (ADR 0065)."""

    EVIDENCE = "evidence"
    """From the reference answer and the failing answers (ModelBump's own)."""
    NAIVE = "naive"
    """Baseline: "make this prompt work with the new model", from the prompt alone."""
    ITERATIVE = "iterative"
    """Baseline: OPRO/COPRO-style rounds guided by screening scores only."""


@dataclass(frozen=True, slots=True)
class Evidence:
    """What the proposer is shown for one call."""

    call: str
    cases: int
    """Test cases of this call in the suite."""
    regressed: tuple[str, ...]
    """Ids of the call's REGRESSED cases."""
    messages: tuple[tuple[str, str], ...]
    """The app's prompt, from the first REGRESSED case."""
    reference: str
    failures: tuple[tuple[str, tuple[str, ...]], ...]
    """New-model answers that did not pass, with the checks each failed."""

    @property
    def edits_allowed(self) -> bool:
        """Edits only where "exactly once in every case" can tell prompt text from inputs."""
        return self.cases >= 2


@dataclass(frozen=True, slots=True)
class Candidate:
    sample: int
    patch: PromptPatch
    why: str


@dataclass(frozen=True, slots=True)
class Proposals:
    """The candidates for one call, and the answers that were refused, with the reason."""

    evidence: Evidence
    candidates: tuple[Candidate, ...]
    refused: tuple[tuple[int, str], ...]
    trace: tuple[tuple[int, int, float], ...] = ()
    """For the iterative strategy: (round, sample, screening mean) of each candidate."""


def _failed(answer: Mapping[str, Any]) -> tuple[str, ...]:
    checks = [str(name) for name in answer.get("failed", [])]
    if answer.get("judge") == "FAIL":
        checks.append("the judge failed it")
    return tuple(checks)


def regressed_calls(suite: Suite, report: Mapping[str, Any]) -> list[Evidence]:
    """One entry per call with a REGRESSED case, in suite order.

    ``report`` is a ``modelbump test --format json`` report of this suite, run
    without a patch. Raises ``ValueError`` if it does not fit.
    """
    by_id = {case.id: case for case in suite.cases}
    cases = report.get("cases")
    if not isinstance(cases, list):
        raise ValueError("the report has no cases: use `modelbump test --format json`")
    regressed: dict[str, list[Mapping[str, Any]]] = {}
    for item in cases:
        if item.get("id") not in by_id:
            raise ValueError(f"the report's case {item.get('id')} is not in the suite")
        if item.get("patched_messages"):
            raise ValueError("the report comes from a patched run: propose from a run without one")
        if item.get("verdict") == "REGRESSED":
            regressed.setdefault(call_of(by_id[item["id"]]), []).append(item)
    per_call: dict[str, int] = {}
    for case in suite.cases:
        per_call[call_of(case)] = per_call.get(call_of(case), 0) + 1
    found: list[Evidence] = []
    for call in dict.fromkeys(call_of(case) for case in suite.cases):
        items = regressed.get(call)
        if not items:
            continue
        first: SuiteCase = by_id[items[0]["id"]]
        failures: list[tuple[str, tuple[str, ...]]] = []
        for item in items:
            for answer in item.get("answers", []):
                if answer.get("model") != "new" or float(answer.get("score", 1)) >= 1:
                    continue
                text = str(answer.get("text", ""))
                if text not in (shown for shown, _ in failures):
                    failures.append((text, _failed(answer)))
        found.append(
            Evidence(
                call=call,
                cases=per_call[call],
                regressed=tuple(str(item["id"]) for item in items),
                messages=first.messages,
                reference=str(items[0].get("reference_answer") or ""),
                failures=tuple(failures[:FAILURES_SHOWN]),
            )
        )
    return found


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "\n[... cut ...]"


def prompt_lines(evidence: Evidence) -> list[str]:
    lines: list[str] = []
    for role, text in evidence.messages:
        lines += [
            f"--- {'user' if role == 'prompt' else role} message ---",
            _cut(text, MESSAGE_CHARS),
            "",
        ]
    return lines


KEEP_THE_TASK = (
    "Keep the task exactly the same: do not change what the prompt asks for, and do not "
    "give the answer away. The app sends this prompt with many other inputs, so write "
    "nothing specific to this input."
)


def reply_lines(evidence: Evidence) -> list[str]:
    lines = [
        "",
        "Reply with only a JSON object with these keys:",
        '- "add_system": an instruction to add at the end of the system message, or "".',
    ]
    if evidence.edits_allowed:
        lines.append(
            '- "edits": a list of {"find": ..., "replace": ...} objects, or []. Copy each '
            '"find" exactly from the instructions above; it must appear there once, and '
            "never inside the input."
        )
    else:
        lines.append('- "edits": always [] for this prompt; use "add_system" only.')
    lines.append('- "why": one sentence on what the change fixes.')
    return lines


def proposer_request(
    model: str, lines: Sequence[str], sample: int, model_version: str
) -> ChatRequest:
    return ChatRequest(
        model,
        (Message("system", SYSTEM), Message("user", "\n".join(lines))),
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
        seed=sample,
        sample=sample,
        model_version=model_version,
    )


def proposal_request(
    evidence: Evidence, old: str, new: str, model: str, sample: int, model_version: str = ""
) -> ChatRequest:
    """The request that asks ``model`` for one patch to ``evidence``'s prompt."""
    lines = [
        f"An app sends the prompt below to an LLM. It moved from the model {old} to {new}, "
        "and the new model's answers now fail checks that the old model's answers passed.",
        "",
        *prompt_lines(evidence),
        "An answer from the old model (it passes):",
        _cut(evidence.reference, ANSWER_CHARS),
        "",
        "Answers from the new model (they fail):",
    ]
    for number, (text, failed) in enumerate(evidence.failures, start=1):
        why = f" [failed: {'; '.join(failed)}]" if failed else ""
        lines.append(f"{number}. {_cut(text, ANSWER_CHARS)}{why}")
    lines += [
        "",
        "Propose one small change to the prompt so that the new model's answers pass again. "
        + KEEP_THE_TASK,
        *reply_lines(evidence),
    ]
    return proposer_request(model, lines, sample, model_version)


def naive_request(
    evidence: Evidence, old: str, new: str, model: str, sample: int, model_version: str = ""
) -> ChatRequest:
    """The naive baseline: the prompt and the model names, no answers (ADR 0065)."""
    lines = [
        f"An app sends the prompt below to an LLM. It was written for the model {old}, "
        f"and the app now uses {new} instead.",
        "",
        *prompt_lines(evidence),
        f"Propose one small change to the prompt so that it works well with {new}. "
        + KEEP_THE_TASK,
        *reply_lines(evidence),
    ]
    return proposer_request(model, lines, sample, model_version)


def check_answer(
    suite: Suite,
    evidence: Evidence,
    candidates: Sequence[Candidate],
    sample: int,
    outcome: ChatResult | RunnerError,
    model: str,
) -> Candidate | str:
    """A proposer's answer as a checked, new candidate, or why it is refused."""
    if isinstance(outcome, RunnerError):
        return f"the model call failed: {outcome}"
    parsed = parse_proposal(outcome.text, evidence, f"proposed by {model}, sample {sample}")
    if isinstance(parsed, str):
        return parsed
    patch, why = parsed
    try:
        apply_patches(suite, (patch,))
    except PatchError as error:
        if not (patch.edits and patch.add_system):
            return f"does not fit the suite: {error}"
        patch = _without_edits(patch.call, patch.add_system, patch.note, str(error))
    for other in candidates:
        if (other.patch.edits, other.patch.add_system) == (patch.edits, patch.add_system):
            return f"the same as sample {other.sample}"
    return Candidate(sample, patch, why)


def parse_proposal(text: str, evidence: Evidence, note: str) -> tuple[PromptPatch, str] | str:
    """The patch and its reason in a proposer's answer, or why it cannot be used."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        return "no JSON object in the answer"
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return "the JSON could not be read"
    add_system = data.get("add_system") or ""
    raw_edits = data.get("edits") or []
    why = str(data.get("why") or "").strip()
    if not isinstance(add_system, str) or not isinstance(raw_edits, list):
        return "add_system must be text and edits a list"
    edits: list[Edit] = []
    for item in raw_edits:
        if not isinstance(item, dict) or not isinstance(item.get("find"), str):
            return "an edit is not a find/replace object"
        edits.append(Edit(item["find"], str(item.get("replace") or "")))
    if edits and not evidence.edits_allowed:
        if not add_system.strip():
            return "only edits, and this call has one test case (add_system only)"
        edits = []
    try:
        patch = PromptPatch(evidence.call, tuple(edits), add_system.strip(), note)
    except PatchError as error:
        if not edits or not add_system.strip():
            return str(error)
        patch = _without_edits(evidence.call, add_system, note, str(error))
    return patch, why


def _without_edits(call: str, add_system: str, note: str, error: str) -> PromptPatch:
    """Keep a proposal's add_system when its edits are unusable (ADR 0067)."""
    return PromptPatch(call, (), add_system.strip(), f"{note}; edits dropped: {error}")


async def propose(
    suite: Suite,
    report: Mapping[str, Any],
    runner: Runner,
    *,
    model: str = DEFAULT_PROPOSER,
    count: int = DEFAULT_CANDIDATES,
    model_version: str = "",
    strategy: Strategy = Strategy.EVIDENCE,
) -> list[Proposals]:
    """Up to ``count`` checked, distinct candidate patches for each call that regressed."""
    if count < 1:
        raise ValueError(f"count must be at least 1, got {count}")
    if strategy is Strategy.ITERATIVE:
        raise ValueError("the iterative strategy needs model answers: use optimize()")
    make = naive_request if strategy is Strategy.NAIVE else proposal_request
    old, new = str(report.get("old", "the old model")), str(report.get("new", "the new model"))
    found = regressed_calls(suite, report)
    requests = [
        make(evidence, old, new, model, sample, model_version)
        for evidence in found
        for sample in range(count)
    ]
    outcomes = await runner.run_each(requests)
    results: list[Proposals] = []
    for index, evidence in enumerate(found):
        candidates: list[Candidate] = []
        refused: list[tuple[int, str]] = []
        for sample in range(count):
            outcome = outcomes[index * count + sample]
            checked = check_answer(suite, evidence, candidates, sample, outcome, model)
            if isinstance(checked, str):
                refused.append((sample, checked))
            else:
                candidates.append(checked)
        results.append(Proposals(evidence, tuple(candidates), tuple(refused)))
    return results


def slug(call: str) -> str:
    """A file name for a call: ``src/support.py:24`` -> ``src_support.py-24``."""
    return call.replace("/", "_").replace("\\", "_").replace(":", "-")


def write_proposals(
    results: Sequence[Proposals],
    folder: Path,
    model: str,
    model_version: str = "",
    strategy: Strategy = Strategy.EVIDENCE,
) -> list[Path]:
    """One patch file per candidate, and ``proposals.json`` with what was refused and why."""
    folder.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    summary: list[dict[str, Any]] = []
    for result in results:
        # Candidates from an earlier run for this call would look like this run's.
        for stale in folder.glob(f"{slug(result.evidence.call)}.[0-9][0-9].json"):
            stale.unlink()
        files = []
        for candidate in result.candidates:
            path = folder / f"{slug(result.evidence.call)}.{candidate.sample:02d}.json"
            path.write_text(patches_to_json((candidate.patch,)), encoding="utf-8")
            written.append(path)
            files.append({"file": path.name, "sample": candidate.sample, "why": candidate.why})
        summary.append(
            {
                "call": result.evidence.call,
                "cases": result.evidence.cases,
                "regressed": list(result.evidence.regressed),
                "edits_allowed": result.evidence.edits_allowed,
                "candidates": files,
                "refused": [{"sample": s, "reason": r} for s, r in result.refused],
                "trace": [
                    {"round": r, "sample": n, "screen_mean": round(mean, 4)}
                    for r, n, mean in result.trace
                ],
            }
        )
    data = {
        "version": 1,
        "strategy": strategy.value,
        "proposer": model,
        "proposer_version": model_version,
        "calls": summary,
    }
    (folder / "proposals.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return written
