# ADR 0041: Decide each test case from pass counts with a continuity-corrected Newcombe interval and an equivalence margin

- **Status:** Accepted
- **Date:** 2026-10-27

## Context

Phase 4 builds the stats engine: given answers from the old and the new model, it decides whether the new model is worse. LLM answers are random, so one answer per model proves nothing. A naive diff of one run flags changes that are only noise, and misses drops that happen 30% of the time.

The first step is one test case. Each model answers it k times, and an oracle marks each answer pass or fail. We need a rule that turns two pass counts, such as 9/10 and 4/10, into a verdict, with these properties:

1. **A known false-alarm rate.** When both models are equally good, it says REGRESSED at most alpha of the time, also for small k (5 to 30 answers is what a laptop can afford per item).
2. **It can say "same"**, not just "no difference found". Not finding a drop in 10 answers is not evidence that there is none.
3. **No new dependencies.** The runner has none beyond httpx ([ADR 0036](0036-runner-speaks-openai-compatible-http.md)); `scipy` would add a large compiled package for a few formulas.

## Decision

- **Interval:** Newcombe's hybrid score interval for the difference of two proportions, new rate minus old rate, built from **continuity-corrected Wilson intervals** (Newcombe, *Statistics in Medicine* 17(8):873–890, 1998, method 11). It needs only square roots and one normal quantile, which `statistics.NormalDist` in the standard library gives.
- **Level:** the interval is two-sided at 1 − 2·alpha (90% for alpha = 0.05), so each one-sided claim below is a test at level alpha. This is the usual link between a confidence interval and the two one-sided tests (TOST) for equivalence.
- **Verdict**, checked in this order, with margin δ:
    1. **EQUIVALENT** if the whole interval lies inside (−δ, +δ).
    2. **REGRESSED** if the whole interval lies below 0.
    3. **IMPROVED** if the whole interval lies above 0.
    4. **INCONCLUSIVE** otherwise: more answers are needed.
- Equivalence comes first on purpose: a drop smaller than the margin is not a regression, even when there is enough data to see it.
- **Defaults:** alpha = 0.05, δ = 0.10 (10 points of pass rate). Both are options, because the right margin depends on the app.
- **Command:** `modelbump stats item OLD NEW`, for example `modelbump stats item 9/10 4/10`, prints the rates, the interval and the verdict.

## Checking the error rates

The tests compute error rates **exactly**, by adding up the binomial probability of every possible pair of counts. Before choosing the method we ran the same check on a grid of true pass rates (0.01 to 0.99) for every k from 1 to 60 and alpha 0.01, 0.05 and 0.10:

| Method | Worst false-alarm rate, alpha = 0.05 | Chance of catching a drop from 90% to 60%, k = 10 / 30 / 50 |
|--------|------------------------------------|------------------------------------------------------------|
| Newcombe without continuity correction (method 10) | 5.8% (k = 10), above alpha | 47% / 89% / 98% |
| Newcombe with continuity correction (method 11, chosen) | at most alpha for every k checked; 4.4% at k = 50 | 29% / 82% / 97% |

The uncorrected interval is more powerful at small k but goes above alpha. Since a controlled false-alarm rate is the claim the paper makes (RQ2), we pick the corrected one and win the power back in the next step with sequential sampling, which stops early when the answer is clear. Wrong EQUIVALENT claims, checked with the new model exactly δ worse, also stayed at or below alpha.

## Alternatives considered

- **Fisher's exact test or Boschloo's test:** exact, but they only test "no difference". They give no interval, so no equivalence verdict, and they need `scipy` or a lot of our own code.
- **Wald interval (rate ± z·standard error):** the textbook formula, but its error rate is far above alpha at small k and it breaks at 0/k and k/k, which are common for test cases that always pass.
- **Bootstrap:** works for any score, but is random itself and unreliable at k = 10.
- **Only a significance test, no margin:** cannot tell "same" from "not enough data", which the repair step (Phase 6) needs to know which items a fix must not break.

## Consequences

- The engine is pure Python with no new dependency, and it is easy to check by hand.
- At k = 10, two models that both pass every time are still INCONCLUSIVE (interval about ±28 points). About 50 answers each are needed to call them EQUIVALENT at δ = 0.10. This cost is what the sequential step (P4-2) is meant to cut.
- Only pass/fail scores are handled. Continuous scores (for example a judge's 1–10 rating) come later.
- One test case at a time. Testing a 300-item suite at alpha = 0.05 per item would raise about 15 false alarms, so a later step adds Benjamini–Hochberg control across items.
