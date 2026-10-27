"""Tests for suite-level false-alarm control (ADR 0043)."""

import pytest

from modelbump.stats import (
    Evidence,
    Verdict,
    benjamini_hochberg,
    decide_suite,
    e_benjamini_hochberg,
    run_sequential,
    run_suite,
    simulated_suite,
)


def test_bh_rejects_only_what_passes_the_step_up_rule() -> None:
    assert benjamini_hochberg([0.01, 0.04, 0.03, 0.2], q=0.05) == [True, False, False, False]


def test_bh_is_step_up_so_a_late_pass_carries_the_earlier_ones() -> None:
    # 0.03 > 0.05 * 1/4 on its own, but 0.045 <= 0.05 * 4/4 rejects all four.
    assert benjamini_hochberg([0.03, 0.035, 0.04, 0.045], q=0.05) == [True] * 4


def test_bh_keeps_the_input_order() -> None:
    assert benjamini_hochberg([0.9, 0.001], q=0.05) == [False, True]


def test_e_bh_rejects_the_largest_e_values_that_clear_m_over_qk() -> None:
    # m = 4, q = 0.05: the top one needs 80, the top two need 40 each.
    assert e_benjamini_hochberg([100, 50, 1, 1], q=0.05) == [True, True, False, False]
    assert e_benjamini_hochberg([30, 30, 30, 30], q=0.05) == [True] * 4
    assert e_benjamini_hochberg([30, 1, 1, 1], q=0.05) == [False] * 4


def test_e_bh_never_rejects_e_values_below_one_over_q() -> None:
    assert not any(e_benjamini_hochberg([19.9] * 50, q=0.05))


@pytest.mark.parametrize("q", [0.0, 1.0])
def test_bad_q_is_rejected(q: float) -> None:
    with pytest.raises(ValueError, match="q must be"):
        benjamini_hochberg([0.5], q=q)
    with pytest.raises(ValueError, match="q must be"):
        e_benjamini_hochberg([1.0], q=q)


def test_bad_p_and_e_values_are_rejected() -> None:
    with pytest.raises(ValueError, match="p-values"):
        benjamini_hochberg([1.5])
    with pytest.raises(ValueError, match="negative"):
        e_benjamini_hochberg([-1.0])


def test_decide_suite_puts_equivalence_first() -> None:
    strong, weak = 1e6, 0.5
    evidence = [
        Evidence(regressed=strong, improved=weak, equivalent=strong),
        Evidence(regressed=strong, improved=weak, equivalent=weak),
        Evidence(regressed=weak, improved=strong, equivalent=weak),
        Evidence(regressed=weak, improved=weak, equivalent=weak),
    ]
    assert decide_suite(evidence) == [
        Verdict.EQUIVALENT,
        Verdict.REGRESSED,
        Verdict.IMPROVED,
        Verdict.INCONCLUSIVE,
    ]


def test_run_suite_finds_clear_regressions_without_false_alarms() -> None:
    suite = simulated_suite(size=40, regressed=10, drop=0.3, seed=1)
    result = run_suite(suite.items)
    found = result.named(Verdict.REGRESSED)
    assert sorted(found) == [f"case-{i:03d}" for i in range(1, 11)]
    assert all(suite.really_worse(name) for name in found)
    assert sum(result.counts.values()) == 40
    assert result.total_runs == sum(item.runs for item in result.items)


def test_run_suite_gives_no_false_alarms_where_per_item_tests_do() -> None:
    suite_alarms = uncorrected_alarms = 0
    for seed in range(1, 4):
        result = run_suite(simulated_suite(size=100, regressed=0, drop=0.3, seed=seed).items)
        suite_alarms += len(result.named(Verdict.REGRESSED))
        for next_round in simulated_suite(
            size=100, regressed=0, drop=0.3, seed=seed
        ).items.values():
            uncorrected_alarms += run_sequential(next_round).verdict is Verdict.REGRESSED
    assert suite_alarms == 0
    assert uncorrected_alarms > 0


def test_run_suite_needs_test_cases() -> None:
    with pytest.raises(ValueError, match="no test cases"):
        run_suite({})


def test_simulated_suite_knows_which_cases_are_worse() -> None:
    suite = simulated_suite(size=5, regressed=2, drop=0.5, seed=4)
    assert [suite.really_worse(name) for name in suite.items] == [True, True, False, False, False]
    old, new = suite.true_rates["case-001"]
    assert new == pytest.approx(max(0.0, old - 0.5))


def test_simulated_suite_repeats_with_the_same_seed() -> None:
    first = simulated_suite(size=3, regressed=1, drop=0.3, seed=9)
    second = simulated_suite(size=3, regressed=1, drop=0.3, seed=9)
    assert [first.items[n]() for n in first.items] == [second.items[n]() for n in second.items]


@pytest.mark.parametrize(
    ("size", "regressed", "drop", "message"),
    [(5, 6, 0.3, "regressed"), (5, -1, 0.3, "regressed"), (5, 1, 0.0, "drop"), (5, 1, 1.5, "drop")],
)
def test_simulated_suite_rejects_bad_settings(
    size: int, regressed: int, drop: float, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        simulated_suite(size, regressed, drop, seed=1)
