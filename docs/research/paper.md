# Paper numbers, tables and figures

**Code:** `research/analysis/paper.py` · **Decision:** [ADR 0019](../adr/0019-paper-numbers-from-one-script.md) · **Output:** `paper/generated/`

Every number, table and figure in Paper 1 comes from one command, so none is typed by hand.

## Running it

Run it after every earlier step, from the repo root:

```
uv run python -m research.analysis.paper
```

It reads these files from `research/data/` and stops with a list of any that are missing, and the command that makes each:

| Input | Made by |
|-------|---------|
| `candidates.stats.json` | `research.mining.miner` |
| `labeled.stats.json` | `research.filtering.filter` |
| `timing.stats.json`, `timing.jsonl` | `research.enrichment.timing` |
| `timing_90d.stats.json` | `research.enrichment.timing --retired-by 2026-07-11 --out research/data/timing_90d.jsonl` |
| `lag.stats.json` | `research.analysis.lag --retired-by 2026-07-11` |
| `targets.stats.json` | `research.enrichment.targets` |
| `files.stats.json`, `files.jsonl` | `research.enrichment.files` |
| `robustness.json` | `research.analysis.robustness` |
| `validation_v2_adjudicated/` | the second hand-labelled sample, with `sample_b.csv` and `targets_check.csv` |
| `validation_files/` | the hand check of file kinds |

## What it writes

| File | Contents |
|------|----------|
| `numbers.tex` | One LaTeX command per number, such as `\MigrationsAway`. Shares have `Low` and `High` versions for the 95% interval, and no `%` sign |
| `numbers.json` | The same numbers, unrounded |
| `tables/dataset.tex` | How the dataset was built: searches, candidates and each filter step |
| `tables/validation.tex` | Precision of the migration label, agreement with a second rater, the target check and the file-kind check |
| `tables/timing.tex` | RQ1: share of migrations after the shutdown, next to Kim's 82% |
| `tables/lag.tex` | RQ2: median days from the shutdown per provider |
| `tables/targets.tex`, `tables/top-switches.tex` | RQ3: what projects migrate to |
| `tables/changed-files.tex` | RQ4: tests, evaluations and pure ID swaps |
| `tables/robustness.tex` | RQ1 and RQ2 repeated with other labels, with days cut at 1,000 results weighted up, and with intervals by repository |
| `figures/lag-windows.pdf` | Share of migrations in each window around the shutdown |
| `figures/lag-ecdf.pdf` | Cumulative share of migrations by days from the shutdown, per provider |
| `figures/targets.pdf` | How targets relate to the recommended replacement, per provider |
| `figures/changed-files.pdf` | RQ4 shares with 95% intervals, and Kim's 16% |

In the paper, a number is written as its command:

```latex
\MigrationsAway{} commits move away from a retired model; \AfterLate\%
(95\% CI \AfterLateLow--\AfterLateHigh) of them came after the shutdown.
```

The output holds aggregate numbers only, so it is committed with the code.
