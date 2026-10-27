# ADR 0046: Test the stats engine on real local models with computed answers, a null pair and injected regressions

- **Status:** Accepted
- **Date:** 2026-10-27

## Context

The simulation study ([ADR 0044](0044-simulation-study-of-the-stats-engine.md)) uses made-up answers that are independent and identically distributed. Real model answers are not: one prompt's answers are correlated, some cases always pass, and the pass rate depends on the wording. RQ2 needs evidence on real answers, with three constraints:

- **No money** ([ADR 0036](0036-runner-speaks-openai-compatible-http.md)), so only local models through Ollama. The pair already on Hammad's Mac is `ollama/qwen2.5:7b` → `ollama/qwen3:8b`.
- **Ground truth.** For a real model pair we do not know which cases truly got worse. Without truth we cannot count false alarms or misses.
- **A laptop budget.** A 7-8B model answers a short prompt in about a second, so thousands of answers take hours, not days.

## Decision

- **Test cases with computed answers** (`research/stats_real/tasks.py`): six families of short tasks: multiply, count a letter, reverse a word, weekday of a date, sort five words, join last letters. Python computes every right answer, so the oracle is exact and nothing is labelled by hand. The families are of different difficulty for 7-8B models, which spreads pass rates. All prompts are made up, so nothing private is sent. Default: 10 cases per family, 60 in all.
- **Answers:** temperature 0.7, at most 48 tokens, a system message asking for the answer only, and Qwen 3's thinking turned off (`reasoning_effort = none`). The sample number is also the seed, so each answer is reproducible, and the cache ([ADR 0037](0037-response-cache-in-sqlite.md)) makes a stopped run resume where it left off.
- **Three comparisons:**
    1. **Null:** Qwen 2.5 against itself, using two separate sets of 50 answers per case. Nothing changed, so every REGRESSED is a false alarm. It is repeated over 20 seeded reshuffles of the 100 answers.
    2. **Injected:** the null pair, but for every third case each new answer is turned into a fail with chance 0.3, or separately 0.6. We know exactly which cases got worse. Cases whose drop would be under 10 points (because they rarely passed) do not count as misses.
    3. **Natural:** Qwen 2.5 (old) against Qwen 3 (new), the real upgrade, with no ground truth. We report how the methods agree, and the pass rate of each family.
- **Methods compared** on the same answers: single-run diff, fixed k = 10 with no suite control, fixed k = 50 + BH, sequential + e-BH ([ADR 0043](0043-suite-control-with-e-bh.md)) with a cap of 50, and the same with stopping of cases that look fine ([ADR 0045](0045-scores-and-stopping-cases-that-look-fine.md)). The sequential methods use the answers in sample order and stop early, so their cost is the answers they actually used.
- **Budget:** 60 cases × (100 Qwen 2.5 + 50 Qwen 3) = 9,000 answers. `--quick` (12 cases, 10 answers) is a 360-answer smoke test of the whole pipeline. Its numbers are too small to mean anything.
- **Code** lives in `research/stats_real/`, a new folder. Nothing in Paper 1's research code changes.

## Alternatives considered

- **Public benchmarks (GSM8K, MMLU):** realistic, but answers are long (math reasoning) or need licence checks, and on a laptop long answers cost ten times more. Computed tasks keep answers to a few tokens.
- **Degrading the system prompt to inject a regression:** realistic, but which cases get worse is unknown, so there is no ground truth. Turning answers into fails at a known rate on top of real answers keeps the real correlation and gives exact truth.
- **Free cloud tiers for bigger models:** possible later ([ADR 0040](0040-free-cloud-tiers-with-pacing.md)), but their daily limits are too low for thousands of answers, and cloud models cannot be pinned to exact weights.

## Consequences

- RQ2 gets real-answer results with ground truth from one command, on hardware a student has, at no cost.
- With a cap of 50 answers and 60 cases, the sequential suite's bar is m/q = 1,200, which 50 answers can reach only for large drops. The simulation predicts that fixed k = 50 + BH will find more of the 30% injected drops. Whether that holds on real answers is part of what the run measures.
- Results go into [the experiment's page](../research/stats-real.md) after the full run.
- Six task families from one model family is a narrow sample. Threats to validity are written up with the results.
