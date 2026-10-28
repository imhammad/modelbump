"""Generated test inputs: a model writes values for a call's slots (ADR 0051).

Most calls in real apps get no inputs from the app's own code (ADR 0050), so
a model writes them. It sees the call's templates and the slot names, and
answers with a JSON array of value sets. Each set becomes a test case marked
with the model that wrote it, so a generated input is never mistaken for one
the app's developers chose.

The default writer is a local model through Ollama: free, and the app's
prompts never leave the machine. Requests are seeded and go through the
runner's cache, so the same command gives the same inputs again.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass, replace

from modelbump.runner import ChatRequest, Message, Runner, RunnerError
from modelbump.synth.callsites import CallSite, render
from modelbump.synth.cases import CaseResult, SiteCases, TestCase

DEFAULT_GENERATOR = "ollama/qwen2.5:7b"
TEMPERATURE = 0.8
MAX_ROUNDS = 3
"""Requests per call at most: a round that gives too few new value sets asks again."""
MAX_TOKENS_PER_CASE = 250

SYSTEM = (
    "You write test inputs for software that calls a large language model. "
    "You reply with JSON only, no other text."
)


@dataclass(frozen=True, slots=True)
class Generation:
    """What generating inputs did."""

    result: CaseResult
    asked: int
    """Calls the model was asked to write inputs for."""
    added: int
    """Generated cases added."""
    skipped: tuple[tuple[CallSite, str], ...]
    """Calls with slots that got no or too few generated cases, and why."""


def needs_inputs(entry: SiteCases, count: int) -> bool:
    """True when a call has slots, every message is readable, and fewer than ``count`` cases."""
    site = entry.site
    readable = bool(site.parts) and all(part.template is not None for part in site.parts)
    complete_cases = sum(case.complete for case in entry.cases)
    return readable and bool(site.slots) and complete_cases < count


def generation_request(site: CallSite, count: int, model: str, sample: int) -> ChatRequest:
    """The request that asks ``model`` for ``count`` value sets for ``site``'s slots."""
    slots = list(site.slots)
    lines = [
        f"An app sends the prompt below to an LLM ({site.api.value}, "
        f"model {site.model or 'unknown'}), from {site.path}:{site.line}.",
        "Each {slot} is filled in by the app at run time. Doubled braces {{ }} are literal.",
        "",
    ]
    for part in site.parts:
        lines += [f"--- {part.role} message ---", part.template or "", ""]
    lines += [
        f"Write {count} different sets of values for the slots {', '.join(slots)}.",
        "Make them realistic and varied: typical inputs, short and long ones, and unusual "
        "or tricky ones the app could really get. Each value is the exact text that replaces "
        "its slot.",
        f"Reply with only a JSON array of {count} objects. Each object has exactly the keys "
        f"{json.dumps(slots)}, and every value is a string.",
    ]
    return ChatRequest(
        model,
        (Message("system", SYSTEM), Message("user", "\n".join(lines))),
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS_PER_CASE * count,
        seed=sample,
        sample=sample,
    )


def parse_values(text: str, slots: Sequence[str]) -> list[dict[str, str]]:
    """The value sets in a model's answer; sets that miss a slot are dropped.

    The answer may wrap the array in prose or a code fence. Numbers and booleans
    become text; other kinds of value drop their set. Extra keys are ignored.
    """
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end < start:
        return []
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    found: list[dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        values: dict[str, str] = {}
        for slot in slots:
            value = item.get(slot)
            if isinstance(value, bool):
                values[slot] = str(value).lower()
            elif isinstance(value, str | int | float):
                values[slot] = str(value)
            else:
                break
        else:
            found.append(values)
    return found


def fill(site: CallSite, values: dict[str, str]) -> CallSite:
    """The call site with every slot replaced by its value."""
    parts = tuple(
        replace(part, template=_escape(render(part.template, values)))
        if part.template is not None
        else part
        for part in site.parts
    )
    return replace(site, parts=parts)


async def add_generated(
    result: CaseResult,
    runner: Runner,
    count: int,
    model: str = DEFAULT_GENERATOR,
    model_version: str = "",
) -> Generation:
    """Add generated cases until each call with slots has ``count`` complete cases.

    ``model_version`` pins the writer's weights in the cache key (ADR 0039).
    Calls whose messages cannot all be read are left out: their cases could
    never be complete. A failed request skips its call; the others go on.
    """
    entries = list(result.sites)
    pending = {i: count - sum(c.complete for c in e.cases) for i, e in enumerate(entries)}
    pending = {i: n for i, n in pending.items() if needs_inputs(entries[i], count)}
    asked = len(pending)
    reasons: dict[int, str] = {}
    added = 0
    for round_number in range(MAX_ROUNDS):
        if not pending:
            break
        order = sorted(pending)
        requests = [
            replace(
                generation_request(entries[i].site, pending[i], model, round_number),
                model_version=model_version,
            )
            for i in order
        ]
        outcomes = await runner.run_each(requests)
        for i, outcome in zip(order, outcomes, strict=True):
            if isinstance(outcome, RunnerError):
                reasons[i] = f"the model call failed: {outcome}"
                del pending[i]
                continue
            entry = entries[i]
            new_cases = list(entry.cases)
            for values in parse_values(outcome.text, entry.site.slots):
                if pending[i] == 0:
                    break
                case = TestCase(
                    fill(entry.site, values),
                    f"generated by {model}, sample {round_number}",
                    tuple((slot, values[slot]) for slot in entry.site.slots),
                    generated_by=model,
                )
                if any(case.site == other.site for other in new_cases):
                    continue
                new_cases.append(case)
                pending[i] -= 1
                added += 1
            entries[i] = SiteCases(entry.site, tuple(new_cases))
            if pending[i] == 0:
                del pending[i]
    for i, missing in pending.items():
        reasons[i] = f"{missing} fewer than asked: the answers had too few usable value sets"
    skipped = tuple((entries[i].site, reasons[i]) for i in sorted(reasons))
    new_result = CaseResult(tuple(entries), result.files_read, result.unparsed)
    return Generation(new_result, asked, added, skipped)


def _escape(text: str) -> str:
    return text.replace("{", "{{").replace("}", "}}")


__all__ = [
    "DEFAULT_GENERATOR",
    "MAX_ROUNDS",
    "Generation",
    "add_generated",
    "fill",
    "generation_request",
    "needs_inputs",
    "parse_values",
]
