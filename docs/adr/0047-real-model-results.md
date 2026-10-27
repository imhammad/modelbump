# ADR 0047: Pick fixed k + BH or sequential + e-BH by budget, and report regressions per test case

- **Status:** Accepted
- **Date:** 2026-10-27

## Context

The real-model run of [ADR 0046](0046-real-model-experiment.md) finished on Hammad's MacBook Air (M5, 16 GB): 9,000 answers from `ollama/qwen2.5:7b` and `ollama/qwen3:8b` in about 38 minutes, at no cost. Full numbers are on [the experiment's page](../research/stats-real.md). Four results matter for the engine:

1. **The false-alarm guarantees hold on real answers.** On the null pair (Qwen 2.5 against itself, 20 reshuffles), a single-run diff raised 2.6 false REGRESSED per 60-case run (up to 5). Fixed k = 50 + BH raised 0.05 per run, and sequential + e-BH raised none, in the null runs and in all 40 injected runs.
2. **With 50 answers per case, fixed k + BH finds more.** On injected drops it found 3.1 of 4 (30% of answers made fails) and 4.0 of 5 (60%), against 0.1 of 4 and 3.5 of 5 for sequential + e-BH. ADR 0046 predicted this: with 60 cases and q = 0.05 the sequential bar is m/q = 1,200, which 50 answers reach only for large drops. The simulation found the same thing ([ADR 0044](0044-simulation-study-of-the-stats-engine.md)): the answer cap, not the method, limits power.
3. **An upgrade that is better on average still breaks cases.** Qwen 3 passed at least as often as Qwen 2.5 in every task family (multiply 36% → 73%, sort 79% → 97%, ...), yet fixed k = 50 + BH and sequential + e-BH each flagged 3 test cases as REGRESSED. Sequential + e-BH also found 16 IMPROVED, 0 EQUIVALENT and 41 INCONCLUSIVE.
4. **Stopping saves a little at this cap.** On the real upgrade the sequential suite used 2,685 answers per model instead of 3,000 (10% fewer), and 2,530 (16% fewer) when it also stopped cases that looked fine, with the same 3 REGRESSED.

## Decision

- **Never use a single-run diff as a verdict.** It is kept only as a baseline in experiments.
- **The suite method follows the budget.** When the number of answers per case is fixed in advance and small (about 100 or fewer), the engine decides the suite with fixed k + BH. When answers can be bought one at a time with a cap of 200 or more, or the results are watched while the run goes on, it uses sequential + e-BH, which is safe to check after every answer. Phase 5's comparison command offers both, with this rule as its default.
- **Report regressions per test case, never only as an average.** The report names every REGRESSED case with its pass rates, because family and suite averages hide them (result 3).
- **Stopping cases that look fine stays off by default** ([ADR 0045](0045-scores-and-stopping-cases-that-look-fine.md)). It saved answers here without changing a verdict, but it also gives up EQUIVALENT verdicts, and the saving is small at a cap of 50.

## Alternatives considered

- **Sequential + e-BH everywhere, for its stronger guarantee:** it would miss most moderate drops at the budgets people actually spend (result 2).
- **Fixed k + BH everywhere:** it is not safe to check while answers come in (peeking gives 16-24% false alarms, ADR 0044), and it cannot stop early.
- **A smaller suite bar (for example m/(10q)):** the simulation showed it barely changes power, because the cap is what binds (ADR 0044).

## Consequences

- RQ2 has its real-answer results: the paper reports the null, injected and natural tables and the two figures (`methods.png`, `upgrade.png`) from one command.
- Phase 4 is complete; the engine ships in v0.3.0.
- **Threats to validity.** One model family (Qwen), 60 made-up cases in six families, temperature 0.7, at most 48 tokens, and Qwen 3's thinking turned off; Qwen 3 may do better with thinking on. Both models scored 0% on the letters family, so those 10 cases carry no information about change. Only 4 (and 5) of the 20 injected cases could lose 10 points, because Qwen 2.5 rarely passed the rest, so the injected power numbers rest on few cases. No case was proven EQUIVALENT: with 50 answers, a ±10-point margin is too tight to prove across 60 cases.
