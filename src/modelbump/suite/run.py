"""Run a suite on the old and the new model and decide each case (ADR 0053).

For each case the old model first answers ``reference`` times; those answers
build the oracle's reference and are never scored. Then both models answer
the same requests (same seeds, sample numbers ``reference`` onwards), each
answer is scored in [0, 1], and the stats engine decides the case:

- **fixed:** every case gets ``runs`` answers per model, then a verdict per
  case with Benjamini-Hochberg on the regression claims (ADRs 0041, 0044).
- **sequential:** answers come one round at a time and a case stops as soon
  as its verdict is clear, with e-BH across the suite (ADRs 0042, 0043).
- **auto** (default) follows ADR 0047: fixed for up to 100 runs, else sequential.

With a patched suite (ADR 0062) the new model is sent the patched messages,
while the reference, the oracle and the judge keep the app's own prompt.
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import cast

from modelbump.oracles import OutputKind, Reference, Score, build_reference, score
from modelbump.oracles.judge import judge_request, parse_verdict, with_judge
from modelbump.runner import ChatRequest, ChatResult, Message, Runner, RunnerError
from modelbump.runner.types import Role
from modelbump.stats import (
    DEFAULT_FDR,
    DEFAULT_MARGIN,
    SequentialTest,
    Verdict,
    benjamini_hochberg,
    compare_counts,
    decide_suite,
    regression_p_value,
)
from modelbump.suite.file import Suite, SuiteCase

DEFAULT_RUNS = 50
DEFAULT_REFERENCE = 3
DEFAULT_TEMPERATURE = 0.7
DEFAULT_MAX_TOKENS = 400
FIXED_UP_TO = 100
"""ADR 0047: fixed k + BH up to this many runs per case, sequential + e-BH above."""


class Method(StrEnum):
    AUTO = "auto"
    FIXED = "fixed"
    SEQUENTIAL = "sequential"


@dataclass(frozen=True, slots=True)
class Settings:
    """How to run the comparison."""

    old: str
    new: str
    runs: int = DEFAULT_RUNS
    """Answers per model per case (the most, for sequential)."""
    reference: int = DEFAULT_REFERENCE
    method: Method = Method.AUTO
    q: float = DEFAULT_FDR
    margin: float = DEFAULT_MARGIN
    temperature: float = DEFAULT_TEMPERATURE
    max_tokens: int = DEFAULT_MAX_TOKENS
    old_think: str | None = None
    new_think: str | None = None
    old_version: str = ""
    new_version: str = ""
    judge: str | None = None
    """The model that judges free-text answers (ADR 0054), or None for property checks only."""
    judge_version: str = ""

    def __post_init__(self) -> None:
        if self.runs < 1:
            raise ValueError(f"runs must be at least 1, got {self.runs}")
        if self.reference < 1:
            raise ValueError(f"reference must be at least 1, got {self.reference}")

    @property
    def chosen(self) -> Method:
        """The method actually used: AUTO resolved by ADR 0047's rule."""
        if self.method is not Method.AUTO:
            return self.method
        return Method.FIXED if self.runs <= FIXED_UP_TO else Method.SEQUENTIAL


@dataclass(frozen=True, slots=True)
class Answer:
    """One scored answer."""

    sample: int
    text: str
    score: Score
    judge: str | None = None
    """``PASS``, ``FAIL`` or ``unclear`` when a judge read the answer, else None."""


@dataclass(slots=True)
class CaseRun:
    """Everything one case got: the reference, the scored answers and the verdict."""

    case: SuiteCase
    patched: SuiteCase | None = None
    """What the new model is sent when a patch changed this case (ADR 0062)."""
    reference: Reference | None = None
    reference_answers: list[str] = field(default_factory=list)
    old: list[Answer] = field(default_factory=list)
    new: list[Answer] = field(default_factory=list)
    verdict: Verdict = Verdict.INCONCLUSIVE
    error: str | None = None
    """Why the case could not be run (a request failed or the budget ran out)."""

    @property
    def sent_to_new(self) -> SuiteCase:
        """The case as the new model gets it: patched, or the app's own."""
        return self.patched if self.patched is not None else self.case

    @property
    def old_mean(self) -> float:
        return sum(a.score.value for a in self.old) / len(self.old) if self.old else 0.0

    @property
    def new_mean(self) -> float:
        return sum(a.score.value for a in self.new) / len(self.new) if self.new else 0.0

    @property
    def new_failures(self) -> list[tuple[str, int]]:
        """The checks the new answers failed, most often first."""
        return Counter(name for a in self.new for name in a.score.failed).most_common()


@dataclass(frozen=True, slots=True)
class SuiteRun:
    settings: Settings
    cases: tuple[CaseRun, ...]

    @property
    def counts(self) -> Counter[Verdict]:
        return Counter(run.verdict for run in self.cases if run.error is None)

    @property
    def errors(self) -> int:
        return sum(run.error is not None for run in self.cases)

    @property
    def regressed(self) -> bool:
        return self.counts[Verdict.REGRESSED] > 0

    @property
    def patched(self) -> int:
        """How many cases the new model got with a patch."""
        return sum(run.patched is not None for run in self.cases)


def request(case: SuiteCase, settings: Settings, which: str, sample: int) -> ChatRequest:
    """The request for one answer from the old (``which="old"``) or new model."""
    old = which == "old"
    messages = tuple(
        Message(cast(Role, "user" if role == "prompt" else role), text)
        for role, text in case.messages
    )
    return ChatRequest(
        model=settings.old if old else settings.new,
        messages=messages,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
        seed=sample,
        sample=sample,
        reasoning_effort=settings.old_think if old else settings.new_think,
        model_version=settings.old_version if old else settings.new_version,
    )


def _texts(outcomes: Sequence[ChatResult | RunnerError]) -> list[str]:
    for outcome in outcomes:
        if isinstance(outcome, RunnerError):
            raise outcome
    return [cast(ChatResult, outcome).text for outcome in outcomes]


async def _set_reference(run: CaseRun, runner: Runner, settings: Settings) -> None:
    requests = [request(run.case, settings, "old", i) for i in range(settings.reference)]
    answers = _texts(await runner.run_each(requests))
    run.reference_answers = answers
    run.reference = build_reference(run.case.oracle, answers, run.case.prompt)


def judged(run: CaseRun, settings: Settings) -> bool:
    """True when this case's answers go to the judge: free text, with a judge set."""
    return settings.judge is not None and run.case.oracle.kind is OutputKind.TEXT


async def _judge(
    run: CaseRun, runner: Runner, settings: Settings, answers: list[Answer]
) -> list[Answer]:
    """The answers with the judge's verdict in their score (free-text cases only)."""
    if not judged(run, settings) or not answers:
        return answers
    assert settings.judge is not None
    reference = run.reference_answers[0]
    # The judge reads the app's own prompt, even for a patched case: a patch must
    # not be able to pass by changing the task.
    requests = [
        judge_request(run.case.messages, reference, a.text, settings.judge, settings.judge_version)
        for a in answers
    ]
    replies = _texts(await runner.run_each(requests))
    out = []
    for answer, reply in zip(answers, replies, strict=True):
        verdict = parse_verdict(reply)
        label = "unclear" if verdict is None else ("PASS" if verdict else "FAIL")
        out.append(Answer(answer.sample, answer.text, with_judge(answer.score, verdict), label))
    return out


def _scored(run: CaseRun, samples: Sequence[int], texts: Sequence[str]) -> list[Answer]:
    assert run.reference is not None
    return [
        Answer(sample, text, score(run.reference, text))
        for sample, text in zip(samples, texts, strict=True)
    ]


async def _fixed(runs: Sequence[CaseRun], runner: Runner, settings: Settings) -> None:
    samples = list(range(settings.reference, settings.reference + settings.runs))
    for run in runs:
        try:
            await _set_reference(run, runner, settings)
            requests = [request(run.case, settings, "old", s) for s in samples]
            requests += [request(run.sent_to_new, settings, "new", s) for s in samples]
            texts = _texts(await runner.run_each(requests))
            answers = await _judge(run, runner, settings, _scored(run, samples * 2, texts))
        except RunnerError as error:
            run.error = str(error)
            continue
        run.old = answers[: len(samples)]
        run.new = answers[len(samples) :]
    done = [run for run in runs if run.error is None]
    k = settings.runs
    passes = [
        (round(sum(a.score.value for a in r.old)), round(sum(a.score.value for a in r.new)))
        for r in done
    ]
    p_values = [regression_p_value(old, k, new, k) for old, new in passes]
    rejected = benjamini_hochberg(p_values, settings.q) if done else []
    for run, (old, new), is_regressed in zip(done, passes, rejected, strict=True):
        verdict = compare_counts(old, k, new, k, margin=settings.margin).verdict
        if is_regressed:
            run.verdict = Verdict.REGRESSED
        elif verdict in (Verdict.EQUIVALENT, Verdict.IMPROVED):
            run.verdict = verdict
        else:
            run.verdict = Verdict.INCONCLUSIVE


async def _sequential(runs: Sequence[CaseRun], runner: Runner, settings: Settings) -> None:
    tests: list[tuple[CaseRun, SequentialTest]] = []
    m = len(runs)
    for run in runs:
        # Stopping at m/q is enough for e-BH to reject this case on its own (ADR 0043).
        test = SequentialTest(alpha=settings.q / m, margin=settings.margin, max_runs=settings.runs)
        try:
            await _set_reference(run, runner, settings)
            sample = settings.reference
            while not test.done:
                pair = [
                    request(run.case, settings, "old", sample),
                    request(run.sent_to_new, settings, "new", sample),
                ]
                old_text, new_text = _texts(await runner.run_each(pair))
                old, new = await _judge(
                    run, runner, settings, _scored(run, [sample, sample], [old_text, new_text])
                )
                run.old.append(old)
                run.new.append(new)
                test.add(old.score.value, new.score.value)
                sample += 1
        except RunnerError as error:
            run.error = str(error)
            continue
        tests.append((run, test))
    if tests:
        verdicts = decide_suite([test.evidence for _, test in tests], settings.q)
        for (run, _), verdict in zip(tests, verdicts, strict=True):
            run.verdict = verdict


async def run_suite_on_models(
    suite: Suite, runner: Runner, settings: Settings, patched: Suite | None = None
) -> SuiteRun:
    """Answer, score and decide every case of the suite.

    ``patched`` is the same suite with patches applied (ADR 0062): the new model
    gets its messages, everything else uses ``suite``.
    """
    if not suite.cases:
        raise ValueError("the suite has no test cases")
    runs = [CaseRun(case) for case in suite.cases]
    if patched is not None:
        if [c.id for c in patched.cases] != [c.id for c in suite.cases]:
            raise ValueError("the patched suite must have the same cases in the same order")
        for run, case in zip(runs, patched.cases, strict=True):
            if case.messages != run.case.messages:
                run.patched = case
    if settings.chosen is Method.FIXED:
        await _fixed(runs, runner, settings)
    else:
        await _sequential(runs, runner, settings)
    return SuiteRun(settings, tuple(runs))
