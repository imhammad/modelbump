"""An LLM judge for free-text answers (ADR 0054).

Property checks (ADR 0052) catch empty answers, refusals and lost formats,
but not a wrong or useless answer. For a text case the judge reads the
app's prompt, one old-model reference answer and the answer to check, and
says PASS (it does the job at least as well as the reference) or FAIL.

The judge is a third model, from another family than the two being compared,
so it does not favour its own answers. It sees old and new answers the same
way and never knows which model wrote one, so any bias it has applies to both.
Its agreement with people is measured in the calibration step.
"""

import re
from collections.abc import Sequence

from modelbump.oracles.score import Check, Score
from modelbump.runner import ChatRequest, Message

DEFAULT_JUDGE = "ollama/gemma3:12b"
JUDGE_MAX_TOKENS = 8
JUDGE_CHECK = "judge: as good as the reference"
HARD_CHECKS = ("not empty", "not a refusal")
"""Property checks that still set the score to 0 when the judge is used."""

SYSTEM = (
    "You grade answers that an AI model gave inside an app. You see the app's prompt, "
    "a reference answer that the app accepted, and a candidate answer. "
    "PASS means the candidate does what the prompt asks at least as well as the "
    "reference: it is correct, it answers the request, and it follows the prompt's "
    "instructions (length, format, tone). Wording may differ. "
    "The reference is one acceptable answer, not the only one: PASS a candidate that "
    "makes another valid choice, or that is more correct than the reference. "
    "If the prompt asks for something new (a description, a plan, a pitch, questions, "
    "code), adding content is the job: do not fail an answer for details the prompt "
    "does not contain. "
    "If the prompt gives source text to work from (a document, a thread, a summary, "
    "data), FAIL an answer that states facts that are not in that source, or that "
    "misstates what it says: who did what, what is done or still pending, numbers and names. "
    "FAIL means it is wrong, misses part of the request, or breaks an instruction. "
    "Reply with one word: PASS or FAIL."
)

_VERDICT = re.compile(r"\b(PASS|FAIL)\b", re.IGNORECASE)


def judge_request(
    messages: Sequence[tuple[str, str]],
    reference: str,
    answer: str,
    model: str = DEFAULT_JUDGE,
    model_version: str = "",
) -> ChatRequest:
    """The request that asks the judge about one answer. Temperature 0, seed 0."""
    prompt = "\n\n".join(f"[{role}]\n{text}" for role, text in messages)
    user = (
        f"## The app's prompt\n{prompt}\n\n"
        f"## Reference answer\n{reference}\n\n"
        f"## Candidate answer\n{answer}\n\n"
        "Does the candidate PASS or FAIL?"
    )
    return ChatRequest(
        model=model,
        messages=(Message("system", SYSTEM), Message("user", user)),
        temperature=0.0,
        max_tokens=JUDGE_MAX_TOKENS,
        seed=0,
        model_version=model_version,
    )


def parse_verdict(text: str) -> bool | None:
    """True for PASS, False for FAIL, None when the reply says neither (or both)."""
    found = {match.upper() for match in _VERDICT.findall(text)}
    if len(found) != 1:
        return None
    return found == {"PASS"}


def with_judge(result: Score, verdict: bool | None) -> Score:
    """A text score with the judge's verdict.

    The judge decides the score (1 or 0), except that an empty answer or a
    refusal scores 0 whatever it says. The other property checks stay in the
    list, to explain a FAIL, but do not change the score. A reply that is
    neither PASS nor FAIL leaves the property score as it was.
    """
    if verdict is None:
        return Score(result.value, (*result.checks, Check("judge: no clear verdict", False)))
    hard_failed = any(c.name in HARD_CHECKS and not c.passed for c in result.checks)
    value = 1.0 if verdict and not hard_failed else 0.0
    return Score(value, (*result.checks, Check(JUDGE_CHECK, verdict)))
