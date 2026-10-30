"""The repair loop: screen candidate patches, then confirm the best on fresh answers (ADR 0064).

For each LLM call that regressed, with candidates from ``repair propose``:

1. **Screen.** Every candidate runs on all of the call's test cases for a few
   answers (``screen_runs``), on the same samples as the test that found the
   regression, so the old model's answers come from the cache. Candidates
   are ranked by the patched new model's mean score.
2. **Confirm.** The best candidate (or the best ``top``) runs again on
   samples no earlier run used: ``confirm_runs`` fresh answers from each
   model on every case of the call. It is accepted only if, on **every**
   case, the patched new model is shown to be no worse than the old model by
   more than ``margin``: the lower end of the one-sided interval for
   (new - old) at level ``alpha / top`` is above ``-margin``.

The guarantee, per call: the chance of accepting a patch under which some
test case of the call is more than ``margin`` worse than the old model is at
most about ``alpha``. Screening may pick a candidate that only looked good by
luck, but the confirming answers are new draws that screening never saw.
Every case must pass its own test (an intersection-union test), so no
correction across the call's cases is needed; trying ``top`` candidates
splits ``alpha`` between them (Bonferroni). The guarantee covers the inputs
in the suite, not inputs the suite does not have.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from modelbump.repair.patch import PatchError, PromptPatch, apply_patches, call_of, read_patches
from modelbump.runner import Runner
from modelbump.stats import difference_interval
from modelbump.suite.file import Suite
from modelbump.suite.run import Method, Settings, SuiteRun, run_suite_on_models

DEFAULT_SCREEN_RUNS = 10
DEFAULT_CONFIRM_RUNS = 100
DEFAULT_CONFIRM_TOP = 1
CONFIRM_OFFSET = 10_000
"""Confirming answers start this many samples after the reference: fresh seeds."""


@dataclass(frozen=True, slots=True)
class CallCandidates:
    """One call's candidates from ``repair propose``, by file name."""

    call: str
    regressed: tuple[str, ...]
    candidates: tuple[tuple[str, PromptPatch], ...]


@dataclass(frozen=True, slots=True)
class Screened:
    file: str
    patch: PromptPatch
    new_mean: float
    """The patched new model's mean score over the call's cases."""
    error: str | None = None


@dataclass(frozen=True, slots=True)
class CaseCheck:
    """One case in a confirmation: pass counts and the interval's lower end."""

    case_id: str
    old_passes: int
    new_passes: int
    runs: int
    low: float
    ok: bool


@dataclass(frozen=True, slots=True)
class Confirmation:
    file: str
    checks: tuple[CaseCheck, ...]
    error: str | None = None

    @property
    def accepted(self) -> bool:
        return self.error is None and bool(self.checks) and all(c.ok for c in self.checks)


@dataclass(frozen=True, slots=True)
class CallRepair:
    """What the loop did for one call."""

    call: str
    regressed: tuple[str, ...]
    cases: int
    unpatched_mean: float | None
    """The unpatched new model's mean score on the screening samples."""
    old_mean: float | None
    screened: tuple[Screened, ...]
    """Best first; candidates that could not be run last."""
    confirmations: tuple[Confirmation, ...]

    @property
    def accepted(self) -> Confirmation | None:
        return next((c for c in self.confirmations if c.accepted), None)

    @property
    def patch(self) -> PromptPatch | None:
        chosen = self.accepted
        if chosen is None:
            return None
        return next(s.patch for s in self.screened if s.file == chosen.file)


@dataclass(frozen=True, slots=True)
class LoopSettings:
    screen_runs: int = DEFAULT_SCREEN_RUNS
    confirm_runs: int = DEFAULT_CONFIRM_RUNS
    top: int = DEFAULT_CONFIRM_TOP
    alpha: float = 0.05
    margin: float = 0.10

    def __post_init__(self) -> None:
        if min(self.screen_runs, self.confirm_runs, self.top) < 1:
            raise ValueError("screen runs, confirm runs and top must each be at least 1")
        if not 0 < self.alpha < 0.5:
            raise ValueError(f"alpha must be between 0 and 0.5, got {self.alpha}")
        if not 0 < self.margin < 1:
            raise ValueError(f"margin must be between 0 and 1, got {self.margin}")


def read_candidates(folder: Path, suite: Suite) -> list[CallCandidates]:
    """The candidates in a ``repair propose`` folder, each checked against the suite."""
    summary = folder / "proposals.json"
    if not summary.is_file():
        raise ValueError(f"{folder} has no proposals.json: run `modelbump repair propose` first")
    try:
        data = json.loads(summary.read_text(encoding="utf-8"))
        calls = data["calls"]
        found: list[CallCandidates] = []
        for item in calls:
            candidates: list[tuple[str, PromptPatch]] = []
            for entry in item["candidates"]:
                (patch,) = read_patches(folder / str(entry["file"]))
                apply_patches(suite, (patch,))
                candidates.append((str(entry["file"]), patch))
            found.append(
                CallCandidates(
                    str(item["call"]),
                    tuple(str(r) for r in item["regressed"]),
                    tuple(candidates),
                )
            )
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise ValueError(f"{summary} cannot be read: {error}") from error
    except PatchError as error:
        raise ValueError(f"a candidate in {folder} cannot be used: {error}") from error
    except ValueError as error:  # a patch file with more than one patch
        raise ValueError(f"a candidate in {folder} is not a one-patch file: {error}") from error
    return found


def _mean(run: SuiteRun, which: str) -> float:
    means = [r.new_mean if which == "new" else r.old_mean for r in run.cases]
    return sum(means) / len(means)


def _error(run: SuiteRun) -> str | None:
    return next((r.error for r in run.cases if r.error is not None), None)


def check_case(
    case_id: str,
    old_scores: Sequence[float],
    new_scores: Sequence[float],
    alpha: float,
    margin: float,
) -> CaseCheck:
    """Non-inferiority of the patched new model on one case, from fixed-k scores."""
    runs = len(old_scores)
    old, new = round(sum(old_scores)), round(sum(new_scores))
    low = difference_interval(old, runs, new, runs, alpha).low
    return CaseCheck(case_id, old, new, runs, low, low > -margin)


async def repair_call(
    suite: Suite,
    entry: CallCandidates,
    runner: Runner,
    settings: Settings,
    loop: LoopSettings,
) -> CallRepair:
    """Screen the call's candidates, then confirm the best on fresh answers."""
    cases = Suite(tuple(case for case in suite.cases if call_of(case) == entry.call))
    if not cases.cases:
        raise ValueError(f"no case in the suite for call {entry.call}")
    screen = replace(settings, runs=loop.screen_runs, method=Method.FIXED, offset=0)
    unpatched = await run_suite_on_models(cases, runner, screen)
    clean = _error(unpatched) is None
    screened: list[Screened] = []
    for file, patch in entry.candidates:
        run = await run_suite_on_models(cases, runner, screen, apply_patches(cases, (patch,)))
        error = _error(run)
        screened.append(Screened(file, patch, _mean(run, "new") if error is None else 0.0, error))
    # Best patched mean first; ties keep the proposer's order. Failed runs go last.
    screened.sort(key=lambda s: (s.error is not None, -s.new_mean))
    confirm = replace(settings, runs=loop.confirm_runs, method=Method.FIXED, offset=CONFIRM_OFFSET)
    alpha = loop.alpha / loop.top
    confirmations: list[Confirmation] = []
    for chosen in [s for s in screened if s.error is None][: loop.top]:
        run = await run_suite_on_models(
            cases, runner, confirm, apply_patches(cases, (chosen.patch,))
        )
        error = _error(run)
        checks = (
            ()
            if error is not None
            else tuple(
                check_case(
                    r.case.id,
                    [a.score.value for a in r.old],
                    [a.score.value for a in r.new],
                    alpha,
                    loop.margin,
                )
                for r in run.cases
            )
        )
        confirmation = Confirmation(chosen.file, checks, error)
        confirmations.append(confirmation)
        if confirmation.accepted:
            break
    return CallRepair(
        call=entry.call,
        regressed=entry.regressed,
        cases=len(cases.cases),
        unpatched_mean=_mean(unpatched, "new") if clean else None,
        old_mean=_mean(unpatched, "old") if clean else None,
        screened=tuple(screened),
        confirmations=tuple(confirmations),
    )


async def repair_suite(
    suite: Suite,
    calls: Sequence[CallCandidates],
    runner: Runner,
    settings: Settings,
    loop: LoopSettings,
) -> list[CallRepair]:
    """Run the loop for every call, in order."""
    return [await repair_call(suite, entry, runner, settings, loop) for entry in calls]
