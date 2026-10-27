# Stats engine on real models

Does the stats engine work on real, random model answers, not only simulated ones? Decisions: [ADR 0046](../adr/0046-real-model-experiment.md) (the design) and [ADR 0047](../adr/0047-real-model-results.md) (what the results mean). Code: `research/stats_real/`. This is the real-model part of RQ2.

## Run it

Ollama must be running, with `qwen2.5:7b` and `qwen3:8b` pulled (`modelbump models` lists them).

```bash
uv run python -m research.stats_real.run --quick   # 360 answers: a smoke test, about 2 minutes
uv run python -m research.stats_real.run           # 9,000 answers: the real run, about 40 minutes
```

Progress is printed every 200 answers. Every answer is cached, so a run that is stopped (Ctrl+C, laptop asleep) resumes where it left off when started again, and a finished run can be re-analysed for free. It writes to `research/data/stats_real/`:

| File | Contents |
|------|----------|
| `answers.jsonl` | Every answer: task, model, sample, text, score, prompt and reply tokens |
| `tasks.csv` | Each test case: family, right answer, pass rate of each model, sequential verdict for the real upgrade |
| `results.json` | Pass rates per family, tokens per answer, and the null, injected and natural comparisons for every method |
| `figures/methods.png` | False alarms with nothing changed, and the share of injected drops found, per method |
| `figures/upgrade.png` | Each test case's pass rate under Qwen 2.5 and Qwen 3, marked by its verdict |

## Test cases

Six families, 10 cases each by default. Python computes every right answer:

| Family | Example prompt | Right answer |
|--------|----------------|--------------|
| multiply | What is 43 times 344? | 14792 |
| count | How many times does the letter 'n' appear in the word 'tunnel'? | 2 |
| reverse | Write the word 'needle' backwards | eldeen |
| weekday | What day of the week was 21 November 2011? | monday |
| sort | Sort these words alphabetically: window, candle, pencil, island, needle | candle, island, needle, pencil, window |
| letters | Take the last letter of each word in 'success parrot cherry kitten' | styn |

The oracle ignores case, quotes, full stops and thousands separators, and it takes the last number or word, so "43 × 344 = 14792" counts as right.

## Comparisons

| Comparison | Old | New | Truth |
|------------|-----|-----|-------|
| Null | Qwen 2.5, answers 1–50 | Qwen 2.5, answers 51–100 | Nothing changed (20 reshuffles) |
| Injected | same | same, but every third case's answers become fails with chance 0.3 (or 0.6) | Exactly those cases got worse |
| Natural | Qwen 2.5 | Qwen 3, thinking off | Unknown |

## Results

Full run on Hammad's MacBook Air (M5, 16 GB) with Ollama, 27 October 2026: 9,000 answers in about 38 minutes (24 for Qwen 2.5's 6,000, 13 for Qwen 3's 3,000), at no cost. q = 0.05, margin 10 points, at most 50 answers per model per test case. A second run reads every answer from the cache and prints the same numbers.

### Pass rates

| Family | Qwen 2.5 | Qwen 3 |
|--------|----------|--------|
| multiply | 36% | 73% |
| count | 38% | 61% |
| reverse | 11% | 32% |
| weekday | 11% | 26% |
| sort | 79% | 97% |
| letters | 0% | 0% |

Qwen 3 is at least as good as Qwen 2.5 in every family.

### Nothing changed (Qwen 2.5 against itself, 20 reshuffles)

| Method | False REGRESSED per 60-case run (max) | Answers per model |
|--------|---------------------------------------|-------------------|
| Single run | 2.60 (5) | 60 |
| Fixed k=10 | 0.15 (1) | 600 |
| Fixed k=50 + BH | 0.05 (1) | 3,000 |
| Sequential + e-BH | 0 (0) | 3,000 |
| Sequential + e-BH, stop cases that look fine | 0 (0) | 2,999 |

### Injected regressions (every third case made worse, 20 reshuffles)

A case counts as a real drop only if it passed often enough to lose at least 10 points: 4 of the 20 injected cases at 30%, and 5 at 60%. Qwen 2.5 rarely passes the others.

| Answers made fails | Method | Real drops found | False alarms per run | Answers per model |
|--------------------|--------|------------------|----------------------|-------------------|
| 30% | Single run | 1.4 of 4 | 2.10 | 60 |
| | Fixed k=10 | 1.4 of 4 | 0.05 | 600 |
| | Fixed k=50 + BH | 3.1 of 4 | 0.05 | 3,000 |
| | Sequential + e-BH | 0.1 of 4 | 0 | 3,000 |
| | Sequential + e-BH, stop cases that look fine | 0.1 of 4 | 0 | 2,999 |
| 60% | Single run | 2.4 of 5 | 2.10 | 60 |
| | Fixed k=10 | 3.4 of 5 | 0.05 | 600 |
| | Fixed k=50 + BH | 4.0 of 5 | 0.05 | 3,000 |
| | Sequential + e-BH | 3.5 of 5 | 0 | 2,961 |
| | Sequential + e-BH, stop cases that look fine | 3.5 of 5 | 0 | 2,961 |

### The real upgrade (Qwen 2.5 → Qwen 3)

| Method | REGRESSED cases | Answers per model |
|--------|-----------------|-------------------|
| Single run | 1 | 60 |
| Fixed k=10 | 2 | 600 |
| Fixed k=50 + BH | 3 | 3,000 |
| Sequential + e-BH | 3 | 2,685 |
| Sequential + e-BH, stop cases that look fine | 3 | 2,530 |

Sequential + e-BH verdicts: 3 REGRESSED, 16 IMPROVED, 0 EQUIVALENT, 41 INCONCLUSIVE. The run prints the names of the REGRESSED cases, and `tasks.csv` gives every case's pass rates and verdict. Each case sends the same short prompt every time, so tokens grow with answers; the run prints tokens per answer and the tokens each method used.

### What it shows

- **A single-run diff is noise.** With nothing changed it flags 2.6 of 60 cases per run, and on injected suites its false alarms (2.1) outnumber what it finds.
- **The suite-controlled methods keep their promise on real answers.** Sequential + e-BH raised no false alarm in 60 runs; fixed k=50 + BH raised 1 in 20 runs per setting.
- **At 50 answers per case, fixed k + BH finds more.** Sequential + e-BH needs its evidence to reach m/q = 1,200 for one case, which 50 answers reach only for large drops: it found 3.5 of 5 when 60% of answers were made fails, but almost none at 30%. This matches the simulation ([ADR 0044](../adr/0044-simulation-study-of-the-stats-engine.md)), where a higher cap fixed it.
- **A better model on average still breaks cases.** Every family improved or stayed the same, yet 3 test cases got worse. A report must name cases, not only averages.
- **Stopping saves a little at this cap:** 10% of the answers on the real upgrade, 16% when cases that look fine also stop, with the same verdicts.

## Limits

- One model family, 60 made-up cases in six families, temperature 0.7, at most 48 tokens, Qwen 3's thinking off.
- Both models fail every letters case, so those 10 cases cannot show a change.
- Few injected cases are detectable (4 and 5), so the power numbers are rough.
- With 50 answers no case was proven EQUIVALENT; that needs a bigger cap (see the simulation).
