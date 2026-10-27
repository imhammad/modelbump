# Stats engine simulation study

Does the stats engine keep its error promises, and what does it cost compared with a single-run diff and a fixed number of answers? Decision: [ADR 0044](../adr/0044-simulation-study-of-the-stats-engine.md). Code: `research/stats_sim/`. This is the simulation part of RQ2.

## Run it

```bash
uv run python -m research.stats_sim.run
```

It takes about 2 minutes (`--quick` takes seconds) and writes to `research/data/stats_sim/`:

| File | Contents |
|------|----------|
| `item.csv` | One test case: chance of REGRESSED and EQUIVALENT, and answers per model, for each method, old pass rate and drop |
| `peeking.csv` | False REGRESSED when the fixed-k interval is checked after every answer |
| `suite.csv` | 300-case suites: real regressions found, false alarms, FDR, answers per model |
| `stopping.csv` | Variants of the suite stopping rule |
| `results.json` | All of the above, plus the settings |
| `figures/power.png`, `figures/answers.png` | Chance of REGRESSED and answers per model against the drop, old model at 90% |

Every random draw has a fixed seed, so the files are the same on every machine.

## Results

alpha = q = 0.05, margin 10 points, at most 200 answers per model per test case unless stated otherwise.

### One test case, old model at 90%

Chance of REGRESSED (mean answers per model in brackets for the sequential test):

| True drop | Single run | Fixed k=10 | Fixed k=30 | Fixed k=100 | Sequential |
|-----------|------------|------------|------------|-------------|------------|
| 0 (false alarm) | 9.0% | 0.5% | 2.0% | 3.3% | 1.2% (181) |
| 5 points | 13.5% | 1.8% | 8.4% | 22.9% | 24.2% (179) |
| 10 points | 18.0% | 4.5% | 20.3% | 58.3% | 67.0% (142) |
| 15 points | 22.5% | 8.6% | 36.4% | 85.8% | 95.4% (93) |
| 20 points | 27.0% | 14.3% | 53.8% | 96.9% | 99.8% (64) |
| 30 points | 36.0% | 29.1% | 82.4% | 100.0% | 100% (40) |
| 50 points | 54.0% | 65.9% | 99.6% | 100.0% | 100% (22) |

At a 60% pass rate, a single run gives 24% false alarms. The worst false alarm of the fixed-k and sequential tests over the whole grid was 4.0%.

### Peeking

| Both models at | False REGRESSED when checking fixed k after every answer |
|----------------|-----------------------------------------------------------|
| 60% | 24.4% |
| 90% | 16.3% |

### Suites of 300 test cases (20 suites per row)

| Suite | Method | Real regressions found | False alarms per suite (max) | Answers per model |
|-------|--------|------------------------|------------------------------|-------------------|
| Nothing changed | single run | 0 | 36.9 (45) | 300 |
| | fixed k=30 | 0 | 6.8 (13) | 9,000 |
| | sequential | 0 | 4.5 (9) | 45,970 |
| | fixed k=170 + BH | 0 | 0 (0) | 51,000 |
| | sequential + e-BH | 0 | 0 (0) | 52,870 |
| 30 worse by 30 points | fixed k=30 + BH | 9.8 | 0.1 (1) | 9,000 |
| | fixed k=170 + BH | 30 | 0.7 (3) | 51,000 |
| | sequential + e-BH | 30 | 0.1 (1) | 50,645 |
| 30 worse by 15 points | fixed k=170 + BH | 22.4 | 0.35 (2) | 51,000 |
| | sequential | 27.1 | 4.0 (9) | 44,369 |
| | sequential + e-BH | 17.2 | 0.05 (1) | 53,148 |
| 150 worse by 15 points | fixed k=170 + BH | 133.3 | 1.65 (5) | 51,000 |
| | sequential + e-BH | 109.7 | 0.15 (2) | 54,349 |

`suite.csv` has every method for every row.

### What limits power on small drops (30 of 300 worse by 15 points, 5 suites)

| Rule | Found | False alarms | EQUIVALENT | Answers per model |
|------|-------|--------------|------------|-------------------|
| Bar m/q, cap 200 (default) | 17.0 | 0 | 68.6 | 53,269 |
| Bar m/(10q), cap 200 | 17.2 | 0 | 68.6 | 50,926 |
| Bar m/q, cap 500 | 28.6 | 0 | 166.4 | 114,554 |
| Bar m/q, cap 500, stop cases that look fine | 28.6 | 0 | 137.4 | 89,888 |
| Fixed k=300 + BH, for comparison | 27.8 | 0.8 | | 90,000 |

"Stop cases that look fine" stops a case once its REGRESSED wealth falls below 0.1 after at least 20 answers.

## Limits

- Answers are independent and scores are pass/fail. Real models give correlated answers to one prompt, and some oracles give scores. P4-5 and P4-6 test that.
- Unchanged test cases pass 60%, 80%, 90% or 100% of the time. Other mixes change the costs, not the guarantees.
