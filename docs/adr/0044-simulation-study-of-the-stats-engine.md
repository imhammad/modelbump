# ADR 0044: Check the stats engine with a seeded simulation study and property tests, against a single-run diff and fixed-k baselines

- **Status:** Accepted
- **Date:** 2026-10-27

## Context

ADRs [0041](0041-item-verdict-from-pass-counts.md), [0042](0042-sequential-stopping-by-betting.md) and [0043](0043-suite-control-with-e-bh.md) each give an error guarantee and a few numbers. RQ2 asks whether sequential testing detects regressions at bounded cost with a controlled false-alarm rate. Answering it needs one study that:

- compares the engine with what people do today, which is to run each prompt once and diff the answers, and with a fixed number of answers per test case;
- gives the same numbers on any machine, from one command;
- runs before any real model is involved, so that bugs in the statistics cannot hide behind model noise.

## Decision

- **Simulated models with known pass rates.** Made-up test cases have a true pass rate for the old and the new model, so every wrong verdict can be counted. Every random draw takes its seed from the code, so `uv run python -m research.stats_sim.run` writes the same CSV files on every machine. It takes about 2 minutes, and `--quick` takes seconds.
- **Four experiments:**
    1. **Item:** one test case, old pass rate 60%, 90% or 100%, drops of 0 to 50 points. Methods: a single-run diff (REGRESSED if the old answer passed and the new one failed), fixed k = 10, 30 and 100 (computed exactly, not simulated), and the sequential test with a cap of 200 answers (1,000 runs per cell).
    2. **Peeking:** the fixed-k interval checked after every answer, up to 200.
    3. **Suite:** 300 test cases, 20 suites per row. Methods: single run, fixed k = 30 with and without BH, fixed k = 170 with BH (about the same budget as the sequential suite), and sequential with and without e-BH.
    4. **Stopping:** what limits power on small drops: the bar a case must reach, or the cap on answers? And does stopping cases that look fine help? This is the "smarter stopping rule" ADR 0043 promised to try.
- **The study lives in `research/stats_sim/`**, a new folder. Nothing in Paper 1's research code changes. `matplotlib` is already in the research dependency group.
- **Property tests with Hypothesis** (`tests/stats/test_properties.py`) check rules that must hold for every input, for example: swapping the models swaps REGRESSED and IMPROVED; the new model is never REGRESSED when it did at least as well; one more pass never makes it look worse; the wealths stay positive; BH and e-BH reject a top set. Hypothesis is a new dev dependency.
- **Fixed-k p-values:** `regression_p_value` finds the smallest alpha at which the ADR 0041 interval lies wholly below 0, so fixed-k suites can use BH.

## Results

Full tables are in [the study's page](../research/stats-sim.md). The main findings, at alpha = q = 0.05 and margin 10 points:

1. **A single-run diff is not a test.** When nothing changed, it says REGRESSED for 24% of test cases at a 60% pass rate (9% at 90%). In a 300-case suite that is 37 false alarms on average.
2. **The fixed-k and sequential tests keep their promise for one case.** The worst false REGRESSED in the whole grid was 4.0%.
3. **Peeking breaks the fixed-k test:** 24.4% (60% pass rate) and 16.3% (90%) false alarms.
4. **The sequential test adapts its cost.** With the old model at 90%, it used 22 answers for a 50-point drop and 40 for a 30-point drop, where fixed k = 100 always uses 100. At a 10-point drop it found more (67% against 58%) but used more answers (142). When nothing changed, it ran to the cap (181 answers on average).
5. **At the same budget, fixed k + BH beats sequential + e-BH on small drops.** In suites with 30 cases worse by 15 points, fixed k = 170 + BH found 22.4 and sequential + e-BH found 17.2, at about 51,000 answers per model each. False alarms were 0.35 per suite (FDR 1.4%) against 0.05 (0.2%). e-BH is much stricter than it needs to be on these suites, whose cases are independent. It pays for staying valid under any dependence and any stopping. On 30-point drops both found all 30.
6. **The cap limits power, not the bar.** Lowering the bar tenfold changed nothing (17.0 → 17.2 found). Raising the cap to 500 found 28.6 of 30, but at 114,554 answers. **Stopping cases that look fine** (REGRESSED wealth below 0.1 after at least 20 answers) kept the 28.6 and cut the cost to 89,888. Fixed k = 300 + BH at the same budget found 27.8, with 0.8 false alarms per suite against 0. Stopping those cases early is still valid, because any stopping rule keeps the wealths e-values. The cost is fewer EQUIVALENT verdicts (137 against 166), because those cases stop before they can prove equivalence.

## Consequences

- RQ2's simulation part reproduces from one command, and the paper's numbers come from `results.json`.
- Honest framing for the paper: the sequential engine's strengths are a guarantee that survives peeking and dependence, and early stops on clear drops. It is not cheaper than a well-chosen fixed k on small drops in independent suites, unless cases that look fine stop early.
- **Follow-up:** add "stop cases that look fine" and a cap of 500 as options of `run_suite`, then test them on real model pairs (P4-6) before making them the default.
- The simulation assumes independent answers and pass/fail scores. Real models break both: answers to one prompt are correlated, and some oracles give scores. P4-5 (scores between 0 and 1) and P4-6 (real model pairs) cover that.
