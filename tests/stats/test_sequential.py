"""Tests for sequential stopping (ADR 0042)."""

import random

import pytest

from modelbump.stats import (
    SequentialResult,
    SequentialTest,
    Verdict,
    compare_counts,
    run_sequential,
)


def _simulate(old_rate: float, new_rate: float, seed: int) -> SequentialResult:
    rng = random.Random(seed)
    return run_sequential(lambda: (rng.random() < old_rate, rng.random() < new_rate))


def _share(verdict: Verdict, old_rate: float, new_rate: float, reps: int) -> float:
    hits = sum(_simulate(old_rate, new_rate, seed).verdict is verdict for seed in range(reps))
    return hits / reps


def test_a_total_break_stops_after_11_answers() -> None:
    result = run_sequential(lambda: (True, False))
    assert result.verdict is Verdict.REGRESSED
    assert result.runs == 11
    assert result.stopped_early
    assert result.evidence.regressed >= 20


def test_two_models_that_always_pass_are_equivalent_after_43_answers() -> None:
    result = run_sequential(lambda: (True, True))
    assert result.verdict is Verdict.EQUIVALENT
    assert result.runs == 43
    assert (result.old_passes, result.new_passes) == (43, 43)


def test_a_total_gain_is_improved() -> None:
    assert run_sequential(lambda: (False, True)).verdict is Verdict.IMPROVED


def test_without_a_margin_equivalence_is_never_claimed() -> None:
    result = run_sequential(lambda: (True, True), margin=0.0, max_runs=500)
    assert result.verdict is Verdict.INCONCLUSIVE
    assert result.runs == 500
    assert not result.stopped_early


def test_max_runs_stops_a_close_call() -> None:
    flips = iter([(True, False), (False, True)] * 50)
    result = run_sequential(lambda: next(flips), max_runs=100)
    assert result.verdict is Verdict.INCONCLUSIVE
    assert result.runs == 100


def test_adding_after_the_test_stopped_is_an_error() -> None:
    test = SequentialTest(max_runs=1)
    test.add(True, True)
    assert test.done
    with pytest.raises(ValueError, match="already stopped"):
        test.add(True, True)


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        ({"alpha": 0.0}, "alpha"),
        ({"alpha": 0.5}, "alpha"),
        ({"margin": 1.0}, "margin"),
        ({"max_runs": 0}, "max_runs"),
    ],
)
def test_bad_settings_are_rejected(settings: dict[str, float], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        SequentialTest(**settings)  # type: ignore[arg-type]


def test_evidence_stays_positive_whatever_the_answers() -> None:
    rng = random.Random(0)
    test = SequentialTest(margin=0.3, max_runs=300)
    while not test.done:
        test.add(rng.random() < 0.5, rng.random() < 0.5)
        evidence = test.evidence
        assert min(evidence.regressed, evidence.improved, evidence.equivalent) > 0


@pytest.mark.parametrize("rate", [0.1, 0.5, 0.9])
def test_false_alarm_rate_is_at_most_alpha_even_though_we_look_every_time(rate: float) -> None:
    # Same true pass rate: any REGRESSED is a false alarm.
    assert _share(Verdict.REGRESSED, rate, rate, reps=400) <= 0.05


@pytest.mark.parametrize("old_rate", [0.6, 1.0])
def test_false_equivalence_rate_is_at_most_alpha(old_rate: float) -> None:
    # The new model is worse by exactly the margin, so EQUIVALENT is wrong.
    assert _share(Verdict.EQUIVALENT, old_rate, old_rate - 0.1, reps=400) <= 0.05


def test_peeking_at_the_fixed_k_interval_would_raise_many_false_alarms() -> None:
    # Why this module exists: checking P4-1 after every answer is not safe.
    alarms = 0
    reps = 200
    for seed in range(reps):
        rng = random.Random(seed)
        old = new = 0
        for runs in range(1, 201):
            old += rng.random() < 0.7
            new += rng.random() < 0.7
            if compare_counts(old, runs, new, runs).verdict is Verdict.REGRESSED:
                alarms += 1
                break
    assert alarms / reps > 0.10


def test_a_30_point_drop_is_caught_in_far_fewer_answers_than_a_fixed_design() -> None:
    # A fixed design sized for a 10-point drop at 80% power needs 180 answers per model.
    runs = []
    for seed in range(200):
        result = _simulate(0.9, 0.6, seed)
        assert result.verdict is Verdict.REGRESSED
        runs.append(result.runs)
    assert sum(runs) / len(runs) < 60
