# ADR 0064: Screen candidates on the test's answers, then accept one only if fresh answers show every case of its call is no worse

- **Status:** Accepted
- **Date:** 2026-10-30

## Context

`repair propose` writes several candidate patches per regressed call ([ADR 0063](0063-candidate-patches-from-a-local-model.md)). The master plan's rule for the repair loop: accept an edit only if it fixes the regressions *and* breaks nothing that worked before. Two traps:

- **Picking the best of several on the same answers is biased.** With 5 candidates and 10 answers each, the one that looks best is partly the luckiest. A test on those same answers would overstate it (the winner's curse).
- **"Not REGRESSED" is not evidence.** With few answers almost nothing is REGRESSED. A loop that accepts any patch with no detected regression would accept patches it simply did not test enough.

## Decision

`modelbump repair run SUITE PROPOSALS --from OLD --to NEW` runs, for each call in the `repair propose` folder:

1. **Screen.** The unpatched new model and every candidate answer `--screen-runs` times (default 10) on **all** test cases of the call, on the same samples as `modelbump test` (reference first, then 3, 4, ...). The old model's answers and the unpatched new ones are mostly cached. Candidates are ranked by the patched new model's mean score over the call's cases. Ties keep the proposer's order.
2. **Confirm.** The best candidate runs again on **fresh samples** (from 10,000 on, which no test or screen uses): `--confirm-runs` answers (default 100) from the old model and from the patched new model, on every case of the call, with the same reference and judge as `modelbump test`.
3. **Accept** only if, **on every case of the call**, the lower end of the one-sided interval for (patched new − old) at level alpha is above −margin (the Newcombe interval of [ADR 0041](0041-item-verdict-from-pass-counts.md), defaults alpha 0.05 and margin 0.10). This is a non-inferiority test against the **old** model. It covers both goals at once: the regressed cases are fixed (back to within the margin of the old model), and the call's other cases are not broken.
4. `--confirm-top N` confirms up to N candidates in screening order, each at alpha / N (Bonferroni), and stops at the first accepted one. The default is 1.
5. Accepted patches go to one patch file (`--output`, default `modelbump-repair.json`), ready for `modelbump test --patch`. The text report shows each call's screen means and each confirmed case's pass counts and lower bound. `--report` writes all of it as JSON. The exit code is 1 when a call is not repaired.
6. `Settings.offset` moves the scored samples, so confirmation reuses all of `modelbump test`'s code (reference, scoring, judge, cache) and only changes the seeds.

**The guarantee, per call:** the chance that the loop accepts a patch under which some test case of the call is more than `margin` worse than the old model is at most about alpha. Three facts give it. The confirming answers are new draws that screening never saw, so picking a lucky candidate does not bias the confirmation. Each case must pass its own level-alpha test, so a bad case gets through with chance at most alpha whatever the other cases do (an intersection-union test, which needs no correction across cases). Trying N candidates at alpha / N each keeps the total at alpha. "About" is there because the interval is approximate. ADR 0041 checked it exactly for up to 60 answers.

## Alternatives considered

- **Accept when nothing REGRESSED:** cheap, but it accepts patches that were not tested enough.
- **Accept the screening winner if it is EQUIVALENT on the screening answers:** biased by the selection. A held-out confirmation costs more answers but is the standard fix.
- **Compare the patched new model with the unpatched new model** (to check that cases which were fine stay fine): that misses a patch that leaves a regression half fixed, and it needs a third set of answers. Comparing every case with the old model answers both questions.
- **Sequential confirmation (ADR 0042):** would stop early on clear cases. The betting test tracks REGRESSED, IMPROVED and both equivalence halves, not this one-sided margin test. Fixed k keeps the guarantee simple to state, and the sequential version can come later.
- **Splitting alpha across calls:** each call is its own change in the PR and is reported separately, so the guarantee is stated per call.

## Consequences

- With the defaults, a call costs about `screen_runs × cases × candidates` new answers to screen and `2 × 100 × cases` to confirm, plus judging for free-text cases.
- **100 answers is about the least for this test.** With both models at 90%, the lower bound is −0.08 at 100 answers and −0.12 at 50. So 50 answers can only accept a case where both models pass about 95% or more.
- The guarantee covers the inputs in the suite. A call with one test case is checked on that input only. The RQ3 experiment gives each corpus call more cases.
- A patch that is right but still rejected stays a candidate. The loop says "not repaired", never "no fix exists".
