# Stats engine on real models

Does the stats engine work on real, random model answers, not only simulated ones? Decision: [ADR 0046](../adr/0046-real-model-experiment.md). Code: `research/stats_real/`. This is the real-model part of RQ2.

## Run it

Ollama must be running, with `qwen2.5:7b` and `qwen3:8b` pulled (`modelbump models` lists them).

```bash
uv run python -m research.stats_real.run --quick   # 360 answers: a smoke test
uv run python -m research.stats_real.run           # 9,000 answers: the real run
```

Progress is printed every 200 answers. Every answer is cached, so a run that is stopped (Ctrl+C, laptop asleep) resumes where it left off when started again, and a finished run can be re-analysed for free. It writes to `research/data/stats_real/`:

| File | Contents |
|------|----------|
| `answers.jsonl` | Every answer: task, model, sample, text, score |
| `tasks.csv` | Each test case: family, right answer, pass rate of each model, sequential verdict for the real upgrade |
| `results.json` | Pass rates per family, and the null, injected and natural comparisons for every method |

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

The numbers are added here after the full run on Hammad's MacBook Air (M5, 16 GB).
