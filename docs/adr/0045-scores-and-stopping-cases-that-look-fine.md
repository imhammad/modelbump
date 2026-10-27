# ADR 0045: Accept scores between 0 and 1, and optionally stop test cases that look fine

- **Status:** Accepted
- **Date:** 2026-10-27

## Context

Two gaps were left open by the earlier stats ADRs:

1. **Only pass/fail.** [ADR 0042](0042-sequential-stopping-by-betting.md) took one pass/fail per answer. Many oracles give a score instead: a judge's 1–10 rating rescaled to 0–1, the share of JSON fields that match, a similarity score. Turning those into pass/fail with a cut-off throws information away.
2. **Small drops in a suite.** The simulation study ([ADR 0044](0044-simulation-study-of-the-stats-engine.md)) found that the answer cap limits power on 15-point drops, not the bar. With a cap of 500, stopping cases whose REGRESSED wealth falls below 0.1 found 28.6 of 30 regressed cases with no false alarms, at about the cost of fixed k = 300 + BH (27.8 found, 0.8 false alarms).

## Decision

- **Scores:** `SequentialTest.add(old_score, new_score)` takes any number from 0 to 1. `True`/`False` still work, as 1 and 0. Each round records x = new_score − old_score, which lies in [−1, 1], with mean d, the difference in mean score. The bets are unchanged: their caps already keep every factor positive for any x in [−1, 1], and under each null E[x] keeps the same sign, so Ville's inequality still gives each claim an error of at most alpha. Nothing in the maths changes. Only the type of the input does.
- **The margin is in score units** (0.10 = a tenth of the score range).
- **`old_passes` and `new_passes` become sums of scores.** For pass/fail they are still the pass counts.
- **Stopping cases that look fine ("futility stopping")**: `SequentialTest`, `run_sequential` and `run_suite` take `futility` (off by default) and `futility_after` (default 20). Once at least `futility_after` rounds are done and no claim is proven, a case whose REGRESSED wealth is below `futility` stops with INCONCLUSIVE and `looks_fine = True`. Stopping is allowed at any time, so the guarantees of ADRs 0042 and 0043 hold. The rule only changes cost and power.
- **It stays off by default** until the real-model experiment (P4-6) shows it pays off there too. `modelbump stats simulate-suite --max-runs 500 --futility 0.1` shows it.
- **Fixed-k stays pass/fail.** The interval of [ADR 0041](0041-item-verdict-from-pass-counts.md) is for counts. Scores use the sequential test.

## Results from simulation

1,000 runs per row, alpha = 0.05, margin 0.10, cap 200. Scores come from a Beta distribution with the given mean and a + b = 10 (`draw_score`), which spreads less than pass/fail with the same mean.

| Old → new mean | Pass/fail: verdicts | Answers | Scores: verdicts | Answers |
|----------------|---------------------|---------|------------------|---------|
| 0.5 → 0.5 | REGRESSED 2.8%, EQUIVALENT 0% | 194 | REGRESSED 0%, EQUIVALENT 99.9% | 69 |
| 0.9 → 0.9 | REGRESSED 1.3%, EQUIVALENT 43.9% | 182 | REGRESSED 0%, EQUIVALENT 100% | 53 |
| 0.6 → 0.5 (exactly the margin) | REGRESSED 38.1%, EQUIVALENT 0% | 162 | REGRESSED 98.7%, EQUIVALENT 1.3% | 97 |
| 0.9 → 0.8 (exactly the margin) | REGRESSED 65.5% | 144 | REGRESSED 99.8%, EQUIVALENT 0.2% | 92 |
| 0.9 → 0.6 | REGRESSED 100% | 40 | REGRESSED 100% | 31 |

Wrong REGRESSED stayed at or below 2.8% and wrong EQUIVALENT (the "exactly the margin" rows) at or below 1.3%. Scores reach a verdict with fewer answers because they vary less. How much less depends on the real oracle, so the gain on real models is measured in P4-6, not assumed.

## Alternatives considered

- **Cut scores into pass/fail at a threshold:** works with the old code, but the threshold is arbitrary and the study above shows how much power it costs.
- **A separate test for continuous scores (for example a t-test):** its guarantee needs roughly normal scores and a fixed sample size. The betting test needs only that scores lie in [0, 1].
- **Futility on by default:** it saves answers, but it also cuts EQUIVALENT verdicts (137 against 166 in ADR 0044), which the repair step needs. We decide after real models.

## Consequences

- Phase 5 oracles can return any score in [0, 1], and the engine needs no change.
- Suites can trade EQUIVALENT verdicts for cheaper detection of small drops with one option.
- The futility bar 0.1 is close to the lowest the 10-bet mixture usually drops to without real evidence, so with no difference cases often stop only after many answers. That is a reason to tune it on real data.
