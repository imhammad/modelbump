# Robustness: do the timing results hold?

**Code:** `research/analysis/robustness.py` · **Decision:** [ADR 0021](../adr/0021-robustness-checks.md) · **Output:** `research/data/robustness.json`

RQ1 (share of migrations after the shutdown) and RQ2 (days from the shutdown) rest on choices a reviewer can question. This step repeats the headline once per question, with one thing changed.

## Running it

Run it after `research.enrichment.targets`, from the repo root:

```
uv run python -m research.analysis.robustness
```

It reads `labeled.jsonl`, `candidates.stats.json`, `targets.jsonl`, `validation_v2_adjudicated/` and the miner's cache (`research/data/cache/`, or `--cache`), from which it takes the number of results GitHub reported on each day it cut at 1,000. It makes no request to GitHub. The headline is OpenAI and Anthropic migrations away from models shut down by 2026-07-11 (`--retired-by`), as in [timing](timing.md). `--reps` sets the number of bootstrap resamples (2,000).

## The checks

| Doubt | Check |
|-------|-------|
| The search missed commits for some models | Each migration found on a day GitHub cut at 1,000 results counts total/1,000 times; and how many headline migrations leave an ID searched only from its notice ([ADR 0011](../adr/0011-search-huge-ids-from-the-notice.md)) |
| Commits from one repository are alike | 95% intervals from resampling whole repositories; first migration per repository |
| The label differs from Kim's | The same share with `migration` (Kim's rules), `migration_strict`, and without AI-assisted commits |
| The label's mistakes depend on timing | Precision before and after the shutdown; share after the shutdown among all real migrations in the hand sample, missed ones included |
| OpenAI and Anthropic differ only by eye | Mann-Whitney U test and Cliff's delta on days from the shutdown |

## Reading the output

- If the share after the shutdown stays near the headline in every row, the result does not depend on that choice.
- The weighted row assumes the 1,000 results GitHub showed on a cut day are like the ones it did not show. The output also says whether the cut days fall before or after each model's shutdown.
- If the repository intervals are much wider than the per-commit ones, the paper should quote the repository intervals.
- If the precision after the shutdown is close to the precision before it, the label's mistakes do not push the share either way. The weighted share among real migrations says the same thing directly.
- Cliff's delta near 0 (below 0.147 in absolute value) means the two providers' timing is practically the same, even when the p-value is small.

`research.analysis.paper` turns the file into `tables/robustness.tex` and commands such as `\AfterKimLabel`, `\AfterReweighted`, `\AfterLateRepoLow`, `\PrecisionAfter`, `\SampleTrueAfter` and `\CliffAll`.
