"""Property tests for the stats engine, with Hypothesis (ADR 0044).

Each test states a rule that must hold for every input, and Hypothesis tries
hundreds of inputs, including edge cases such as 0/k and k/k, to break it.
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from modelbump.stats import (
    SequentialTest,
    Verdict,
    benjamini_hochberg,
    compare_counts,
    difference_interval,
    e_benjamini_hochberg,
    regression_p_value,
    wilson_interval,
)

runs = st.integers(min_value=1, max_value=60)
alphas = st.sampled_from([0.01, 0.025, 0.05, 0.1, 0.2])
margins = st.sampled_from([0.0, 0.05, 0.1, 0.2])


@st.composite
def counts(draw: st.DrawFn) -> tuple[int, int, int, int]:
    old_runs, new_runs = draw(runs), draw(runs)
    old = draw(st.integers(min_value=0, max_value=old_runs))
    new = draw(st.integers(min_value=0, max_value=new_runs))
    return old, old_runs, new, new_runs


@given(counts(), alphas)
def test_wilson_interval_holds_the_observed_rate(
    c: tuple[int, int, int, int], alpha: float
) -> None:
    passes, n = c[0], c[1]
    interval = wilson_interval(passes, n, alpha)
    assert 0.0 <= interval.low <= passes / n <= interval.high <= 1.0


@given(counts(), alphas)
def test_difference_interval_holds_the_observed_difference(
    c: tuple[int, int, int, int], alpha: float
) -> None:
    old, old_runs, new, new_runs = c
    interval = difference_interval(old, old_runs, new, new_runs, alpha)
    difference = new / new_runs - old / old_runs
    assert -1.0 <= interval.low <= difference + 1e-12
    assert difference - 1e-12 <= interval.high <= 1.0


@given(counts(), alphas, margins)
def test_swapping_the_models_swaps_regressed_and_improved(
    c: tuple[int, int, int, int], alpha: float, margin: float
) -> None:
    old, old_runs, new, new_runs = c
    forward = compare_counts(old, old_runs, new, new_runs, alpha=alpha, margin=margin).verdict
    backward = compare_counts(new, new_runs, old, old_runs, alpha=alpha, margin=margin).verdict
    swapped = {Verdict.REGRESSED: Verdict.IMPROVED, Verdict.IMPROVED: Verdict.REGRESSED}
    assert backward == swapped.get(forward, forward)


@given(counts(), alphas, margins)
def test_never_regressed_when_the_new_model_did_at_least_as_well(
    c: tuple[int, int, int, int], alpha: float, margin: float
) -> None:
    old, old_runs, new, new_runs = c
    verdict = compare_counts(old, old_runs, new, new_runs, alpha=alpha, margin=margin).verdict
    if new / new_runs >= old / old_runs:
        assert verdict is not Verdict.REGRESSED


@given(counts(), alphas)
def test_one_more_new_pass_never_makes_the_new_model_look_worse(
    c: tuple[int, int, int, int], alpha: float
) -> None:
    old, old_runs, new, new_runs = c
    if new < new_runs:
        before = difference_interval(old, old_runs, new, new_runs, alpha)
        after = difference_interval(old, old_runs, new + 1, new_runs, alpha)
        assert after.low >= before.low - 1e-12
        assert after.high >= before.high - 1e-12


@settings(max_examples=60)
@given(counts(), alphas)
def test_p_value_agrees_with_the_interval(c: tuple[int, int, int, int], alpha: float) -> None:
    old, old_runs, new, new_runs = c
    p = regression_p_value(old, old_runs, new, new_runs)
    below = difference_interval(old, old_runs, new, new_runs, alpha).high < 0
    if p < alpha * 0.999:
        assert below
    if p > alpha * 1.001:
        assert not below


@given(st.lists(st.tuples(st.booleans(), st.booleans()), max_size=80))
def test_wealths_stay_positive_and_mirror_when_models_swap(rounds: list[tuple[bool, bool]]) -> None:
    forward, backward = SequentialTest(max_runs=1000), SequentialTest(max_runs=1000)
    for old, new in rounds:
        if forward.done:
            break
        forward.add(old, new)
        backward.add(new, old)
        a, b = forward.evidence, backward.evidence
        assert min(a.regressed, a.improved, a.equivalent) > 0
        assert abs(a.regressed - b.improved) <= 1e-9 * max(1.0, a.regressed)
        assert abs(a.equivalent - b.equivalent) <= 1e-9 * max(1.0, a.equivalent)


@given(st.lists(st.floats(min_value=0, max_value=1), min_size=1, max_size=50), alphas)
def test_bh_rejects_a_set_of_smallest_p_values(p_values: list[float], q: float) -> None:
    rejected = benjamini_hochberg(p_values, q)
    if any(rejected):
        largest_rejected = max(p for p, r in zip(p_values, rejected, strict=True) if r)
        assert all(r for p, r in zip(p_values, rejected, strict=True) if p < largest_rejected)


@given(st.lists(st.floats(min_value=0, max_value=1e4), min_size=1, max_size=50), alphas)
def test_e_bh_rejects_a_set_of_largest_e_values_each_above_one_over_q(
    e_values: list[float], q: float
) -> None:
    rejected = e_benjamini_hochberg(e_values, q)
    kept = [e for e, r in zip(e_values, rejected, strict=True) if r]
    if kept:
        smallest_rejected = min(kept)
        assert smallest_rejected >= 1 / q
        assert all(r for e, r in zip(e_values, rejected, strict=True) if e > smallest_rejected)


@given(st.lists(st.floats(min_value=0, max_value=1e4), min_size=1, max_size=50))
def test_a_bigger_q_never_rejects_fewer(e_values: list[float]) -> None:
    assert sum(e_benjamini_hochberg(e_values, 0.01)) <= sum(e_benjamini_hochberg(e_values, 0.1))


unit_scores = st.floats(min_value=0, max_value=1, allow_nan=False)


@given(st.lists(st.tuples(unit_scores, unit_scores), max_size=60))
def test_score_wealths_stay_positive_and_mirror_when_models_swap(
    rounds: list[tuple[float, float]],
) -> None:
    forward, backward = SequentialTest(max_runs=1000), SequentialTest(max_runs=1000)
    for old, new in rounds:
        if forward.done:
            break
        forward.add(old, new)
        backward.add(new, old)
        a, b = forward.evidence, backward.evidence
        assert min(a.regressed, a.improved, a.equivalent) > 0
        assert abs(a.regressed - b.improved) <= 1e-9 * max(1.0, a.regressed)
