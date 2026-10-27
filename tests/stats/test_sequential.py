"""Tests for sequential stopping (ADR 0042)."""

import random

import pytest

from modelbump.stats import (
    SequentialResult,
    SequentialTest,
    Verdict,
    compare_counts,
    draw_score,
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


# ---------------------------------------------------------------- scores (ADR 0045)


def _simulate_scores(old_mean: float, new_mean: float, seed: int) -> SequentialResult:
    rng = random.Random(f"scores-{seed}")
    return run_sequential(
        lambda: (draw_score(rng, old_mean, True), draw_score(rng, new_mean, True))
    )


@pytest.mark.parametrize(("old", "new"), [(-0.1, 0.5), (0.5, 1.5)])
def test_scores_outside_zero_and_one_are_rejected(old: float, new: float) -> None:
    with pytest.raises(ValueError, match="score must be between 0 and 1"):
        SequentialTest().add(old, new)


def test_scores_between_zero_and_one_are_summed() -> None:
    test = SequentialTest()
    test.add(0.25, 0.75)
    test.add(True, False)
    assert (test.old_passes, test.new_passes, test.runs) == (1.25, 0.75, 2)


@pytest.mark.parametrize("mean_score", [0.5, 0.9])
def test_scores_with_the_same_mean_give_few_false_alarms(mean_score: float) -> None:
    alarms = sum(
        _simulate_scores(mean_score, mean_score, seed).verdict is Verdict.REGRESSED
        for seed in range(300)
    )
    assert alarms / 300 <= 0.05


def test_scores_can_show_equivalence_where_pass_fail_cannot() -> None:
    # Same means; scores vary less than pass/fail, so equivalence is reachable.
    assert _simulate_scores(0.9, 0.9, seed=1).verdict is Verdict.EQUIVALENT
    rng = random.Random(1)
    pass_fail = run_sequential(lambda: (rng.random() < 0.9, rng.random() < 0.9))
    assert pass_fail.verdict is Verdict.INCONCLUSIVE


def test_scores_catch_a_drop_in_the_mean() -> None:
    assert _simulate_scores(0.9, 0.6, seed=2).verdict is Verdict.REGRESSED


# ---------------------------------------------------------------- futility (ADR 0045)


def test_a_case_that_looks_fine_stops_early_without_a_verdict() -> None:
    result = run_sequential(lambda: (False, True), futility=0.1, max_runs=500)
    # A gain proves IMPROVED before the futility check matters.
    assert result.verdict is Verdict.IMPROVED
    # No difference on average: the REGRESSED wealth drifts down and the case stops.
    flips = iter([(True, True), (False, True), (True, True), (True, False)] * 100)
    looking_fine = run_sequential(lambda: next(flips), futility=0.2, max_runs=400)
    assert looking_fine.looks_fine
    assert looking_fine.verdict is Verdict.INCONCLUSIVE
    assert looking_fine.runs == 170
    assert looking_fine.evidence.regressed < 0.2
    assert not looking_fine.stopped_early


def test_futility_waits_for_futility_after_rounds() -> None:
    test = SequentialTest(futility=0.99, futility_after=5)
    for _ in range(4):
        test.add(False, True)
    assert not test.looks_fine
    test.add(False, True)
    assert test.looks_fine
    assert test.done
    with pytest.raises(ValueError, match="already stopped"):
        test.add(True, True)


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        ({"futility": 0.0}, "futility"),
        ({"futility": 1.0}, "futility"),
        ({"futility_after": 0}, "futility_after"),
    ],
)
def test_bad_futility_settings_are_rejected(settings: dict[str, float], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        SequentialTest(**settings)  # type: ignore[arg-type]
