# Lag: how long before or after the shutdown?

**Code:** `research/analysis/lag.py` · **Decision:** [ADR 0017](../adr/0017-lag-and-migration-targets.md) · **Input:** `research/data/timing.jsonl` from [timing](timing.md)

[Timing](timing.md) says *whether* each migration came after the shutdown. This page says *how long* before or after, which is the paper's RQ2.

## Running it

```
uv run python -m research.analysis.lag --retired-by 2026-07-11
```

It reads `research/data/timing.jsonl` and writes `research/data/lag.stats.json`. Only models shut down by the `--retired-by` day count. Without it, the default is the last commit day, as in timing.

Options:

- `--min-commits 50` lists every model with at least 50 migrations in the last table (default 100).
- `--timing` and `--out` change the input and output files.

## What it prints

All numbers are days from the shutdown: negative means before it, positive after it. Google's are from its *earliest possible* shutdown day.

| Table | Meaning |
|-------|---------|
| All migrations | Median days from the shutdown, its 95% confidence interval, and the quartiles |
| First migration per repository and model | The same, counting each repository once per model |
| Only migrations made after the shutdown | How long the late ones waited |
| When migrations happen | The share in each window, from "more than 180 days before" to "more than 365 days after" |
| Notice period | Days from notice to shutdown (one value per model), and how far into that period the migrations made during it came. 0% is the notice day and 100% is the shutdown |
| Models with the most migrations | Per model: commits, notice period, median days, and the share after the shutdown |

## Reading it

- **The confidence interval** of the median uses order statistics, so it assumes nothing about the shape of the data (Conover, *Practical Nonparametric Statistics*).
- **Late windows are lower bounds.** With `--retired-by 2026-07-11`, every model has at least 90 days of data after its shutdown. So the windows up to "31 to 90 days after" are complete, and the later ones may still grow.
- About 16% of the commits are not real migrations ([validation](validation.md#results)). The numbers describe the flagged commits.
