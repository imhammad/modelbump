"""The iterative baseline: prompt optimisation guided by scores only (ADR 0065).

In the style of OPRO (Yang et al., "Large Language Models as Optimizers",
arXiv:2309.03409) and DSPy's COPRO optimiser (Khattab et al., "DSPy",
arXiv:2310.03714): the proposer never sees an answer. In round 0 it writes
changes from the prompt alone (as the naive baseline). Each candidate is
screened, and every later round shows the proposer the changes tried so far
with their scores, worst first, and asks for a better one.

Screening uses the same samples as the repair loop's screen, so the loop
reads those answers from the cache. The pool of candidates then goes through
the same loop as every other strategy, so the confirmation on fresh answers
and its guarantee are unchanged.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from modelbump.repair.loop import first_error, mean_score
from modelbump.repair.patch import PromptPatch, apply_patches, call_of
from modelbump.repair.propose import (
    DEFAULT_PROPOSER,
    KEEP_THE_TASK,
    Candidate,
    Evidence,
    Proposals,
    check_answer,
    prompt_lines,
    proposer_request,
    regressed_calls,
    reply_lines,
)
from modelbump.runner import ChatRequest, Runner
from modelbump.suite.file import Suite
from modelbump.suite.run import Method, Settings, run_suite_on_models

DEFAULT_ROUNDS = 3
DEFAULT_PER_ROUND = 2
DEFAULT_SCREEN_RUNS = 10


def _describe(patch: PromptPatch) -> str:
    parts = []
    if patch.add_system:
        parts.append(f"add_system {json.dumps(patch.add_system, ensure_ascii=False)}")
    for edit in patch.edits:
        parts.append(
            f"edit {json.dumps(edit.find, ensure_ascii=False)} -> "
            f"{json.dumps(edit.replace, ensure_ascii=False)}"
        )
    return "; ".join(parts)


def iterative_request(
    evidence: Evidence,
    old: str,
    new: str,
    model: str,
    sample: int,
    tried: Sequence[tuple[PromptPatch, float]],
    scores: tuple[float, float],
    model_version: str = "",
) -> ChatRequest:
    """One proposal, shown the changes tried so far with their scores (worst first).

    ``scores`` is (old model, unpatched new model) on the screening answers.
    """
    lines = [
        f"An app sends the prompt below to an LLM. It was written for the model {old}, "
        f"and the app now uses {new} instead.",
        "",
        *prompt_lines(evidence),
        f"Answers are scored from 0 to 1. On this prompt {old} scores {scores[0]:.2f} and "
        f"{new} scores {scores[1]:.2f}.",
    ]
    if tried:
        lines += ["", f"Changes tried so far, with the score {new} got with each, worst first:"]
        for patch, score in sorted(tried, key=lambda item: item[1]):
            lines.append(f"- score {score:.2f}: {_describe(patch)}")
        lines += [
            "",
            f"Propose one new small change, different from these, that makes {new} score "
            "higher. " + KEEP_THE_TASK,
        ]
    else:
        lines += [
            "",
            f"Propose one small change to the prompt so that {new} scores higher. " + KEEP_THE_TASK,
        ]
    lines += reply_lines(evidence)
    return proposer_request(model, lines, sample, model_version)


async def optimize_call(
    suite: Suite,
    evidence: Evidence,
    runner: Runner,
    settings: Settings,
    *,
    model: str = DEFAULT_PROPOSER,
    rounds: int = DEFAULT_ROUNDS,
    per_round: int = DEFAULT_PER_ROUND,
    screen_runs: int = DEFAULT_SCREEN_RUNS,
    model_version: str = "",
) -> Proposals:
    """``rounds`` rounds of ``per_round`` proposals for one call, each screened."""
    if min(rounds, per_round, screen_runs) < 1:
        raise ValueError("rounds, per_round and screen_runs must each be at least 1")
    cases = Suite(tuple(case for case in suite.cases if call_of(case) == evidence.call))
    screen = replace(settings, runs=screen_runs, method=Method.FIXED, offset=0)
    base = await run_suite_on_models(cases, runner, screen)
    error = first_error(base)
    if error is not None:
        return Proposals(evidence, (), ((0, f"the screen failed: {error}"),))
    scores = (mean_score(base, "old"), mean_score(base, "new"))
    candidates: list[Candidate] = []
    refused: list[tuple[int, str]] = []
    trace: list[tuple[int, int, float]] = []
    tried: list[tuple[PromptPatch, float]] = []
    for round_number in range(rounds):
        first = round_number * per_round
        requests = [
            iterative_request(
                evidence,
                settings.old,
                settings.new,
                model,
                sample,
                tried,
                scores,
                model_version,
            )
            for sample in range(first, first + per_round)
        ]
        outcomes = await runner.run_each(requests)
        for sample, outcome in zip(range(first, first + per_round), outcomes, strict=True):
            checked = check_answer(suite, evidence, candidates, sample, outcome, model)
            if isinstance(checked, str):
                refused.append((sample, checked))
                continue
            run = await run_suite_on_models(
                cases, runner, screen, apply_patches(cases, (checked.patch,))
            )
            error = first_error(run)
            if error is not None:
                refused.append((sample, f"the screen failed: {error}"))
                return Proposals(evidence, tuple(candidates), tuple(refused), tuple(trace))
            mean = mean_score(run, "new")
            candidates.append(checked)
            tried.append((checked.patch, mean))
            trace.append((round_number, sample, mean))
    return Proposals(evidence, tuple(candidates), tuple(refused), tuple(trace))


async def optimize(
    suite: Suite,
    report: Mapping[str, Any],
    runner: Runner,
    settings: Settings,
    **options: Any,
) -> list[Proposals]:
    """The iterative strategy for every call with a REGRESSED case in ``report``."""
    return [
        await optimize_call(suite, evidence, runner, settings, **options)
        for evidence in regressed_calls(suite, report)
    ]
