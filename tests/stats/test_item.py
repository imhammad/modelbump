"""Tests for the item-level verdict (ADR 0041)."""

from math import comb, sqrt
from statistics import NormalDist

import pytest

from modelbump.stats import (
    Interval,
    Verdict,
    compare_counts,
    compare_scores,
    difference_interval,
    wilson_interval,
)


def _pmf(runs: int, rate: float) -> list[float]:
    return [comb(runs, k) * rate**k * (1 - rate) ** (runs - k) for k in range(runs + 1)]


def _chance_of(
    verdict: Verdict, runs: int, old_rate: float, new_rate: float, alpha: float
) -> float:
    """Exact chance of a verdict when both models answer `runs` times."""
    old_pmf, new_pmf = _pmf(runs, old_rate), _pmf(runs, new_rate)
    return sum(
        old_pmf[a] * new_pmf[b]
        for a in range(runs + 1)
        for b in range(runs + 1)
        if compare_counts(a, runs, b, runs, alpha=alpha).verdict is verdict
    )


@pytest.mark.parametrize(("passes", "runs"), [(81, 263), (15, 148), (1, 29), (7, 10)])
def test_wilson_bounds_solve_the_continuity_corrected_score_equation(
    passes: int, runs: int
) -> None:
    # Each bound b solves |passes - runs*b| - 1/2 = z * sqrt(runs * b * (1 - b)).
    alpha = 0.025
    z = NormalDist().inv_cdf(1 - alpha)
    interval = wilson_interval(passes, runs, alpha=alpha)
    for bound in (interval.low, interval.high):
        gap = abs(passes - runs * bound) - 0.5
        assert gap == pytest.approx(z * sqrt(runs * bound * (1 - bound)), rel=1e-9)


def test_wilson_interval_stays_inside_zero_and_one() -> None:
    assert wilson_interval(0, 10).low == 0.0
    assert wilson_interval(10, 10).high == 1.0
    assert 0.0 < wilson_interval(1, 10).low < 0.1


def test_difference_interval_is_symmetric_when_models_swap() -> None:
    forward = difference_interval(9, 10, 4, 10)
    backward = difference_interval(4, 10, 9, 10)
    assert forward.low == pytest.approx(-backward.high)
    assert forward.high == pytest.approx(-backward.low)


def test_difference_interval_contains_the_observed_difference() -> None:
    interval = difference_interval(30, 40, 38, 40)
    assert interval.low < 0.2 < interval.high


def test_clear_drop_is_regressed() -> None:
    result = compare_counts(9, 10, 4, 10)
    assert result.verdict is Verdict.REGRESSED
    assert result.difference == pytest.approx(-0.5)
    assert result.interval.high < 0
    assert result.confidence == pytest.approx(0.9)


def test_clear_gain_is_improved() -> None:
    assert compare_counts(30, 40, 38, 40).verdict is Verdict.IMPROVED


def test_same_answers_need_enough_runs_to_be_equivalent() -> None:
    assert compare_counts(10, 10, 10, 10).verdict is Verdict.INCONCLUSIVE
    assert compare_counts(50, 50, 50, 50).verdict is Verdict.EQUIVALENT


def test_small_drop_inside_the_margin_is_equivalent_not_regressed() -> None:
    # 1,000 runs each: a 3-point drop is clearly there but smaller than 10 points.
    result = compare_counts(900, 1000, 870, 1000)
    assert result.interval.high < 0
    assert result.verdict is Verdict.EQUIVALENT
    assert compare_counts(900, 1000, 870, 1000, margin=0.0).verdict is Verdict.REGRESSED


def test_noisy_small_sample_is_inconclusive() -> None:
    assert compare_counts(6, 10, 5, 10).verdict is Verdict.INCONCLUSIVE


def test_compare_scores_counts_true_as_pass() -> None:
    result = compare_scores([True] * 9 + [False], [True] * 4 + [False] * 6)
    assert (result.old_passes, result.old_runs, result.new_passes, result.new_runs) == (
        9,
        10,
        4,
        10,
    )
    assert result.verdict is Verdict.REGRESSED


def test_runs_can_differ_between_models() -> None:
    result = compare_counts(18, 20, 4, 10)
    assert result.old_rate == pytest.approx(0.9)
    assert result.verdict is Verdict.REGRESSED


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ((0, 0, 1, 1), "at least 1 run"),
        ((11, 10, 1, 1), "between 0 and 10"),
        ((1, 1, -1, 1), "between 0 and 1"),
    ],
)
def test_bad_counts_are_rejected(args: tuple[int, int, int, int], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        compare_counts(*args)


@pytest.mark.parametrize(("alpha", "margin"), [(0, 0.1), (0.5, 0.1), (0.05, -0.1), (0.05, 1)])
def test_bad_settings_are_rejected(alpha: float, margin: float) -> None:
    with pytest.raises(ValueError):
        compare_counts(5, 10, 5, 10, alpha=alpha, margin=margin)


def test_interval_rejects_low_above_high() -> None:
    with pytest.raises(ValueError, match="above high"):
        Interval(0.5, 0.1)


@pytest.mark.parametrize("runs", [3, 10, 20, 30])
@pytest.mark.parametrize("alpha", [0.01, 0.05])
def test_false_alarm_rate_is_at_most_alpha(runs: int, alpha: float) -> None:
    # Both models pass at the same true rate, so any REGRESSED is a false alarm.
    worst = max(
        _chance_of(Verdict.REGRESSED, runs, rate, rate, alpha) for rate in (0.1, 0.3, 0.5, 0.7, 0.9)
    )
    assert worst <= alpha


@pytest.mark.parametrize("runs", [10, 30, 50])
def test_false_equivalence_rate_is_at_most_alpha(runs: int) -> None:
    # The new model is worse by exactly the margin, so EQUIVALENT is wrong.
    worst = max(
        _chance_of(Verdict.EQUIVALENT, runs, rate, rate - 0.1, 0.05) for rate in (0.3, 0.6, 0.9)
    )
    assert worst <= 0.05


def test_power_grows_with_runs() -> None:
    powers = [_chance_of(Verdict.REGRESSED, runs, 0.9, 0.6, 0.05) for runs in (10, 30, 50)]
    assert powers == sorted(powers)
    assert powers[-1] > 0.95


def test_regression_p_value_is_small_for_a_clear_drop_and_one_without_a_drop() -> None:
    from modelbump.stats import regression_p_value

    p = regression_p_value(9, 10, 4, 10)
    assert 0.01 < p < 0.05
    assert compare_counts(9, 10, 4, 10, alpha=p * 1.01, margin=0.0).verdict is Verdict.REGRESSED
    assert compare_counts(9, 10, 4, 10, alpha=p * 0.99, margin=0.0).verdict is Verdict.INCONCLUSIVE
    assert regression_p_value(5, 10, 5, 10) == 1.0
    assert regression_p_value(30, 30, 0, 30) == pytest.approx(0.0, abs=1e-9)
