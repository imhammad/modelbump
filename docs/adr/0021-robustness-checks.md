# ADR 0021: Test the timing results against the objections a reviewer would raise

- **Status:** Accepted
- **Date:** 2026-10-14

## Context

A mock review of Paper 1 expected a major revision, mostly over RQ1 (how many migrations come after the shutdown) and RQ2 (how many days from the shutdown). It raised five doubts that the data can answer without new mining:

1. The search may have missed commits for some models: five huge IDs were searched only from 30 days before their notice ([ADR 0011](0011-search-huge-ids-from-the-notice.md)), and on 61 days GitHub returned only the first 1,000 of more results.
2. Commits from the same repository are not independent, so intervals computed per commit may be too narrow.
3. Our label `migration_away` differs from Kim's rules, so the gap with Kim's 82% may come from the definition.
4. The label is 84% precise and finds about 58% of migrations. If its mistakes are more common before or after the shutdown, the share is biased.
5. RQ2 compares OpenAI and Anthropic by eye, without a test.

## Decision

One command, `uv run python -m research.analysis.robustness`, repeats the RQ1 headline (OpenAI and Anthropic, models shut down by 2026-07-11) once per doubt and writes `research/data/robustness.json`:

1. **Incomplete searches.** Drop every model whose search was narrowed, too big to narrow, or cut at 1,000 results on some day. The models are read from `candidates.stats.json`, so none is typed by hand. Google is shown with and without them too.
2. **Repository bootstrap.** Resample whole repositories with replacement, 2,000 times with seed 2029, and take the 2.5th and 97.5th percentiles of the share and the median days. The first migration per repository and model is shown next to it.
3. **Other labels.** The same share with Kim's rules (`migration`), the strict rules (`migration_strict`), and `migration_away` without AI-assisted commits.
4. **Hand labels by phase.** On the adjudicated second sample ([ADR 0015](0015-fresh-sample-for-rules-v2.md)): precision of `migration_away` for commits made before and after their model's shutdown, and the share after the shutdown among all real migrations in the sample, weighting each stratum by its size so that missed migrations count. Its interval comes from resampling within strata, 2,000 times with seed 2029.
5. **OpenAI against Anthropic.** A two-sided Mann-Whitney U test (normal approximation with the tie correction) and Cliff's delta on the days from the shutdown, for all migrations, those after the shutdown, and the first per repository. Cliff's delta is named negligible, small, medium or large with the limits of Romano et al. (2006): 0.147, 0.33 and 0.474.

`research.analysis.paper` reads `robustness.json`, writes `tables/robustness.tex` and the commands for the paper, and stops if the file does not match `timing_90d.stats.json`.

## Alternatives considered

- **Mixed-effects logistic model with a random effect per repository:** answers doubt 2 too, but needs statsmodels and is harder to explain than resampling.
- **Search the incomplete days again with narrower queries:** GitHub's search cannot be split below one day, so the missing results cannot be fetched.
- **Label a new sample stratified by phase:** more precise for doubt 4, but weeks of labelling, and the existing sample is enough to show a large bias.
- **scipy for the Mann-Whitney test:** the normal approximation is exact enough with thousands of rows, and avoids a new dependency.

## Consequences

- Each doubt has one row or number in the paper, so the threats section can cite the result instead of arguing.
- The hand-sample check is coarse: the 100 `migration_away` commits split into two groups of roughly 50, with intervals of about ±13 points, so it can rule out only a large bias.
- With thousands of rows, almost any difference has a small p-value, so the paper reports Cliff's delta as the size of the difference.

## Revision, 14 October 2026

The first run of check 1 dropped every model with a cut day. That removed 34 models and 7,410 of the 12,244 headline migrations, among them the most used models, and the share after the shutdown rose from 62.2% to 76.1%. The rise mixes two things, the missed commits and the change in which models are counted, so it cannot be read as the size of the search gap.

Check 1 now keeps every model and weights the missed commits back in. For each window GitHub cut, the miner's cache holds the total it reported. A migration found on such a day counts total/1,000 times, on the assumption that the 1,000 results shown are like the rest. The intervals come from resampling repositories, as in check 2. The output also gives how many cut days fall before and after each model's shutdown, and how many headline migrations leave one of the five IDs searched only from their notice: none of their models was shut down by 11 July 2026 except `gemini-2.0-flash`, which is Google's.
