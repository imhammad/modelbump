# Dataset card: LLM model migrations on GitHub

The data files in this folder are not committed to git (see `.gitignore`). Only this card is. The files are rebuilt with the commands below and will be published separately with a DOI.

## What it is

Commits from public GitHub repositories whose message names an LLM model that its provider has retired or plans to retire, with labels that say whether the commit moves the project **away** from that model. It covers OpenAI, Anthropic and Google, and is built with the method of Kim (2026), whose own dataset was not yet published when this one was built.

| | |
|---|---|
| Built | 8 to 12 October 2026 |
| Commits searched | 1 January 2023 to 8 October 2026 (committer date; the exact window is in `candidates.stats.json`) |
| Retired models | 128 in the registry (85 OpenAI, 20 Anthropic, 23 Google), 139 searchable IDs and aliases |
| Candidate commits | 254,765 (one per SHA) |
| Migrations away (`migration_away`) | 40,876 |
| Estimated real migrations | about 34,300 (precision 84%) |

## How it was built

1. **Registry.** Retirement dates were copied by hand from each provider's deprecation page (`src/modelbump/registry/data/`, [ADR 0006](../../docs/adr/0006-retirement-registry-format.md), [ADR 0007](../../docs/adr/0007-rescheduled-retirements.md)).
2. **Mining** (`research.mining.miner`, [mining protocol](../../docs/research/mining.md)). One GitHub commit search per model ID. Time windows are split until each has under 1,000 results. Forks are dropped, and each SHA is kept once with every repository it appears in. GitHub's search is fuzzy, so only messages that contain the exact ID are kept. The five IDs with over 50,000 results were searched only from 30 days before their deprecation notice ([ADR 0011](../../docs/adr/0011-search-huge-ids-from-the-notice.md)). 11,003 searches, 851,580 results seen, 294,578 duplicates, 300,955 without the exact ID, 61 windows truncated at GitHub's limit, 0 failed.
3. **Filtering** (`research.filtering.filter`, rules v2, [ADR 0014](../../docs/adr/0014-filter-rules-v2.md)). Every candidate keeps one field per rule, so any other definition can be rebuilt from the same file.
4. **Validation** (`research.validation`, [ADR 0013](../../docs/adr/0013-validation-sample.md), [ADR 0015](../../docs/adr/0015-fresh-sample-for-rules-v2.md)). Two blind, stratified samples labelled by hand.
5. **Timing** (`research.enrichment.timing`, [ADR 0016](../../docs/adr/0016-migration-timing.md)). Each migration is placed before the notice, between notice and shutdown, or after the shutdown.
6. **Lag and targets** (`research.analysis.lag`, `research.enrichment.targets`, [ADR 0017](../../docs/adr/0017-lag-and-migration-targets.md)). How many days before or after the shutdown each migration came, and which model it moved to.

To rebuild everything (the mining step takes about a day because of GitHub's rate limits):

```
uv run python -m research.mining.miner --end 2026-10-08
uv run python -m research.filtering.filter
uv run python -m research.enrichment.timing
uv run python -m research.analysis.lag --retired-by 2026-07-11
uv run python -m research.enrichment.targets
uv run python -m research.enrichment.files
uv run python -m research.analysis.robustness
uv run python -m research.analysis.paper
uv run python -m research.release.export
```

## Files

| File | Rows | Contents |
|------|------|----------|
| `candidates.jsonl` | 254,765 | `sha`, `repo`, `repos`, `url`, `committed_at`, `message`, `matched_ids`, `providers` |
| `candidates.stats.json` | | Mining counts and the exact search window |
| `labeled.jsonl` | 254,765 | Each candidate plus one field per rule (`migration_word`, `direction`, `after_notice_start`, `bot`, `ai_trailer`, `ai_style`) and the labels |
| `labeled.stats.json` | | The filter funnel and the rules version |
| `validation/` | 300 | First sample, first-pass labels (rules v1) |
| `validation_adjudicated/` | 300 | First sample, adjudicated labels |
| `validation_v2/` | 200 | Second sample, first-pass labels (rules v2) |
| `validation_v2_adjudicated/` | 200 | Second sample, adjudicated labels, plus a second person's blind labels on rows 1 to 100 (`sample_b.csv`) |
| `timing.jsonl` | 40,876 | One row per `migration_away` commit: model left, its dates, and the phase |
| `timing_90d.jsonl` | 40,876 | The same with `--retired-by 2026-07-11` (models shut down at least 90 days before the data ends) |
| `lag.stats.json` | | Days from the shutdown: medians, windows and notice use per provider ([lag](../../docs/research/lag.md)) |
| `targets.jsonl` | 40,876 | One row per `migration_away` commit: the model it moves to and the kind of switch ([targets](../../docs/research/targets.md)) |
| `targets.stats.json` | | The counts behind the target tables |
| `files.jsonl` | 400 | A random sample of migration commits with their changed files, each sorted into a kind ([changed files](../../docs/research/files.md)) |
| `validation_files/` | 100 | Hand check of the file kinds: `has_test` and `has_eval` per commit |
| `robustness.json` | | RQ1 and RQ2 repeated with other labels, with days cut at 1,000 results weighted up, with intervals by repository, by phase in the hand sample, and OpenAI against Anthropic ([robustness](../../docs/research/robustness.md)) |

## Labels

| Label | Count | Meaning |
|-------|-------|---------|
| `migration_away` | 40,876 | The message clearly moves away from a retired model, and the commit is not from a dependency bot. **This is the dataset's main label.** |
| `migration` | 40,483 | Kim's rules: a migration word, not a move into the model, not more than 30 days before the notice, not a bot, no AI-tool trailer |
| `migration_strict` | 15,576 | `migration`, and the message clearly moves away |
| `migration_with_ai` | 36,048 | Kim's rules, but the commit has an AI coding tool trailer (Kim dropped these) |

## Quality

Measured on a fresh, blind sample of 200 commits that the rules had never seen, labelled by one person and re-checked against the labelling guide ([validation results](../../docs/research/validation.md#results)):

| Measure | Value |
|---------|-------|
| Precision of `migration_away` | 84.0% (95% CI 75.6% to 89.9%) |
| Real migrations it misses | about 24,500 (most without a clear "from X to Y" wording) |
| Recall (rough) | about 58% |
| Agreement with a second person, blind, 100 rows | Cohen's kappa 0.94 |

## Headline result: when do projects migrate?

For models from OpenAI and Anthropic that were already shut down when the data ends:

| Counting rule | After the shutdown |
|---------------|-------------------|
| All migrations | 57.8% (7,955 of 13,754) |
| Models shut down at least 90 days before the data ends | 62.2% (7,619 of 12,244) |
| Same, only from 30 days before the notice (Kim's window) | 69.2% (7,619 of 11,006) |
| Same, first migration per repository | 61.6% (6,742 of 10,947) |

Kim (2026) reports 82%. Our data points the same way, since most migrations come after the shutdown, but by a smaller margin. Details are in the [timing protocol](../../docs/research/timing.md#results).

## Known limits

- **Messages only.** The labels come from commit messages, not diffs. A migration whose message does not say what changed is missed, which is the main reason recall is about 58%.
- **English rules.** The wording rules are English. Migrations described only in other languages are mostly missed.
- **About 16% false positives** in `migration_away`. One known pattern is "replaces deprecated X" written next to the *new* model, which the rules read as moving away from it. This is kept as a test case for a future rules version.
- **Search limits.** GitHub's commit search finds only default-branch commits in indexed repositories. 61 time windows hit its 1,000-result cap, so some commits in them were not seen.
- **Busiest IDs searched late.** gpt-4, gpt-3.5-turbo, gemini-2.0-flash, gpt-5.3-codex and gpt-5-codex were searched only from 30 days before their notice, so earlier migrations away from them are not in the data.
- **Google dates.** Google publishes no notice dates and only *earliest possible* shutdown dates, so its timing is less exact.
- **Dates.** The commit date is the committer's date. It can differ from when the change reached users.
- **Labels are human, with an AI second reader on the first sample.** On the first sample, an AI model read every row as a disclosed second rater ([challenge 005](../../docs/engineering-challenges/005-first-pass-labels.md)). The second sample's quality numbers come from human labels only.

## Ethics and licence

All data comes from public commits returned by GitHub's API. Commit messages can contain names and email addresses (for example in `Co-Authored-By` lines). The published version will contain commit SHAs, repository names, URLs, the labels and the derived fields, but **not** full messages, so that people can rehydrate the messages from GitHub themselves. The code is Apache-2.0.

## Cite

The method follows H. L. Kim, *When the Model Retires: An Empirical Study of LLM Migration in Open-Source Applications*, arXiv:2609.31288, 2026.
