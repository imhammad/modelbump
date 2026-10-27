# ADR 0042: Stop asking as soon as the verdict is clear, with test-by-betting wealths that are safe to check after every answer

- **Status:** Accepted
- **Date:** 2026-10-27

## Context

[ADR 0041](0041-item-verdict-from-pass-counts.md) decides one test case from a fixed number of answers k. Choosing k is hard. A total break shows after a few answers, but a 10-point drop needs 180 answers per model for 80% power. A fixed k big enough for small drops wastes answers on the easy cases, and on a laptop every answer is several seconds.

The obvious shortcut is to check the ADR 0041 interval after every answer and stop at the first REGRESSED. That is not safe. In our simulation (two models that both pass 70% of the time, up to 200 answers, alpha = 0.05), this "peeking" said REGRESSED in **22%** of runs, not 5%. The interval's guarantee holds only for a k chosen in advance.

We need a rule that can be checked after every answer, can stop at any time, and still keeps each wrong claim at or below alpha.

## Decision

- **One round = one answer from each model.** We record x = new_pass − old_pass, which is −1, 0 or +1. Its mean is d, the true difference in pass rate.
- **Testing by betting** (Shafer, *JRSS-A* 184(2), 2021; Waudby-Smith and Ramdas, *JRSS-B* 86(1), 2024). For each claim we keep a wealth that starts at 1 and is multiplied each round by 1 + λ·y. Here y is how much the round goes against that claim's null hypothesis:

    | Claim | Null hypothesis | y |
    |-------|-----------------|---|
    | REGRESSED | d ≥ 0 | −x |
    | IMPROVED | d ≤ 0 | x |
    | EQUIVALENT, lower half | d ≤ −margin | x + margin |
    | EQUIVALENT, upper half | d ≥ +margin | margin − x |

    Under its null, E[y] ≤ 0, so the wealth is a nonnegative supermartingale. **Ville's inequality** then says the chance that it *ever* reaches 1/alpha is at most alpha. That is what makes checking after every answer safe.
- **A claim is proven** when its wealth reaches 1/alpha (20 for alpha = 0.05). EQUIVALENT needs both halves to reach it, which is the two one-sided tests (TOST) again. The order matches ADR 0041: EQUIVALENT first, then REGRESSED, then IMPROVED.
- **Bet sizes:** each wealth is the average of 10 fixed bets, λ = cap·k/10 for k = 1…10. The cap is 0.5 for REGRESSED and IMPROVED and 0.95/(1 − margin) for the equivalence halves, which keeps every factor above zero. An average of supermartingales is still one, so the guarantee holds. Averaging means we do not need to guess the effect size, at a small cost compared with the best single bet.
- **A limit:** after `max_runs` answers per model (default 200) the test stops with INCONCLUSIVE.
- **Code:** `SequentialTest` (feed rounds one at a time, read the verdict at any time) and `run_sequential(next_round)`. The command `modelbump stats simulate OLD_RATE NEW_RATE` shows one run with made-up models.

## Results from simulation

2,000 simulated test cases per row, alpha = 0.05, margin = 0.10, at most 200 answers per model (seed 7):

| True pass rate, old → new | Right verdict | Mean answers per model | 90% of runs stopped by |
|---------------------------|---------------|------------------------|------------------------|
| 100% → 0% | REGRESSED 100% | 11 | 11 |
| 100% → 50% | REGRESSED 100% | 22 | 28 |
| 90% → 60% | REGRESSED 100% | 40 | 61 |
| 70% → 40% | REGRESSED 100% | 46 | 77 |
| 100% → 100% | EQUIVALENT 100% | 43 | 43 |
| 95% → 95% | EQUIVALENT 89% | 126 | 197 |

For comparison, the fixed-k rule of ADR 0041 needs **180 answers per model** to catch a 10-point drop (90% → 80%) 80% of the time. Sized that way, it would spend 180 on every row above. The sequential rule spends 11 to 46 on the clear drops.

Wrong claims stayed at or below alpha:

- Wrong REGRESSED with the same pass rate for both models (10%, 30%, 50%, 70% and 90%): 1.0% to 2.6%.
- Wrong EQUIVALENT with the new model exactly 10 points worse: 0% to 2.8% (the highest at 100% → 90%).

## Alternatives considered

- **Group-sequential designs (Pocock, O'Brien–Fleming):** the classic clinical-trial answer. They need the number of looks fixed in advance and boundaries computed numerically. Betting allows a look after every answer and is a few lines of code.
- **Wald's SPRT:** optimal for two simple hypotheses, for example 90% against 80%. But we do not know the old model's pass rate in advance, and our nulls are composite.
- **Adaptive bet sizes (predictable plug-in, aGRAPA):** we tried a simple version in a prototype. It was faster on some cases but much worse at showing equivalence (9% against 46% for 90% → 90%), so we kept the fixed mixture.
- **Peeking at the fixed-k interval:** unsafe, as shown above.

## Consequences

- Clear cases are cheap. Close calls, where the true difference is near 0 or near the margin, still use the whole `max_runs`. The suite-level step (P4-3) and the budget ([ADR 0038](0038-budget-in-tokens-and-requests.md)) keep that in check.
- The guarantee needs the rounds to be independent. Each answer must be a fresh sample, so the cache key must include the sample number ([ADR 0037](0037-response-cache-in-sqlite.md)), which it does.
- Each claim is controlled separately at alpha, as in ADR 0041. Control across many test cases comes in P4-3.
- Only pass/fail scores for now. Betting works for any bounded score, so continuous scores in [0, 1] can use the same wealths later.
