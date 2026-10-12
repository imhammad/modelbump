# Validation: labelling the sample by hand

**Code:** `research/validation/` · **Decision:** [ADR 0013](../adr/0013-validation-sample.md) · **Input:** the labels from [filtering](filtering.md)

## Drawing the sample

```
uv run python -m research.validation.sample
```

It writes three files to `research/data/validation/`:

| File | Contents |
|------|----------|
| `sample.csv` | 300 commits to label: `n`, `url`, `model_ids`, `date`, `message`, and the empty columns `is_migration`, `from_model`, `to_model`, `note` |
| `sample_key.csv` | What the filter decided for each `n`. **Do not open it until you have finished labelling.** |
| `strata.json` | The seed, and how many candidates each stratum has in the full set |

It refuses to overwrite an existing `sample.csv`, so your labels are never lost by running it twice.

## What counts as a migration

The question for every row is: **does this commit move the project away from the retired model named in `model_ids`?**

| Label | When |
|-------|------|
| `yes` | The commit stops using the retired model: it replaces it with another model (in code, configuration, defaults, or documentation that tells users which model to use), or removes it from what the project uses or offers |
| `no` | The commit moves *into* the retired model, starts or keeps using it, only mentions it (pricing tables, tests, logs, a list of models where it stays), or is a dependency bump |
| `unsure` | Still unclear after opening the commit on GitHub |

For a `yes`, fill in `from_model` (the retired model it moves away from) and `to_model` (the model it moves to, or `none` if it is only removed). Use `note` for anything odd, for example "adds a fallback but keeps the old model as default".

Open the `url` whenever the message is not enough to decide; the diff usually settles it. If a commit mentions several retired models, it is a `yes` if it moves away from any of them.

This definition is our own. Kim (2026) does not publish its coding guide, so our precision is not directly comparable to Kim's 62%.

## Tips

- Read every message to the end. In long commits the model switch is often one bullet near the bottom ([challenge 005](../engineering-challenges/005-first-pass-labels.md)).

## Scoring

When the labels are in, run:

```
uv run python -m research.validation.score
```

For each stratum it prints how many commits were labelled `yes`, as a share with a 95% Wilson interval. `unsure` rows are counted but left out of the share. From those numbers it estimates:

- the **precision** of the `migration` label over the full set, as the strict and broad-only shares weighted by their sizes, with a 95% margin;
- how many real migrations sit among the **rejected** candidates, as the rejected share times the rejected population;
- a rough **recall**, as real migrations kept divided by kept plus missed.

The rejected stratum is large and the sample from it is small, so the recall estimate is rough.

If someone else labels a copy of `sample.csv` independently, pass it with `--second` to get Cohen's kappa over the rows both of you labelled:

```
uv run python -m research.validation.score --second research/data/validation/sample_b.csv
```

The results are also written to `research/data/validation/scores.json`.

## Re-check and second rater

The first pass was re-checked once ([challenge 005](../engineering-challenges/005-first-pass-labels.md)):

1. An AI model (Claude) read all 300 messages as a second rater, with this guide. Its answers are in `research/data/validation/sample_claude.csv`.
2. The person who labelled re-read every row where the two disagreed, plus 15 random rows the AI had not flagged (seed 2026), and decided each one. A changed row has `changed in re-check` in `note`.
3. The decisions are in `research/data/validation_adjudicated/` (a copy of the sample folder). The first pass is never edited.

```
uv run python -m research.validation.score --second research/data/validation/sample_claude.csv
uv run python -m research.validation.score --dir research/data/validation_adjudicated --compare research/data/validation/sample.csv
```

The first prints the agreement between the first pass and the AI. The second scores the adjudicated labels and shows the first pass next to them.

## Development check

```
uv run python -m research.validation.dev_check
```

It reruns the current filter rules on the adjudicated sample and prints, for each label, how many rows it flags, how many of those are `yes`, and the row numbers where rule and labels disagree. The rules were tuned on these rows, so these numbers are for developing the rules only. Quality is measured on a fresh sample ([ADR 0014](../adr/0014-filter-rules-v2.md)).

## Second sample (design v2)

Rules v2 are measured on a fresh sample ([ADR 0015](../adr/0015-fresh-sample-for-rules-v2.md)), after `research.filtering.filter` has been rerun with them:

```
uv run python -m research.validation.sample --design v2
```

It draws 200 commits (seed 2027) into `research/data/validation_v2/`: 100 labelled `migration_away`, 50 kept by Kim's rules but not "away", and 50 of the rest. Every commit of the first sample is left out. Label `sample.csv` exactly as before, without opening `sample_key.csv`, then:

```
uv run python -m research.validation.score --dir research/data/validation_v2
```

It reports the precision of `migration_away` and how many migrations it misses. A second person's copy can be passed with `--second` for Cohen's kappa.

## Moving into the model is a `no`

The question is always about the model in `model_ids`. A commit that switches *to* that model is a `no`, even if it leaves another model behind. For example, "switch from gemini-1.5-flash to gemini-2.0-flash" with `model_ids` = `gemini-2.0-flash` is a `no`. It only counts as a `yes` when the model it leaves is a retired model too, as the rule for several retired models says. See [challenge 006](../engineering-challenges/006-into-counted-as-yes.md).

## Results

Measured on 12 October 2026. "First pass" is one person's blind labels. "Adjudicated" is the same person's labels after re-checking the disagreements ([challenge 005](../engineering-challenges/005-first-pass-labels.md), [challenge 006](../engineering-challenges/006-into-counted-as-yes.md)). Both are kept and reported.

| Sample | Labels | Label scored | Precision | Recall (rough) | Agreement (Cohen's kappa) |
|--------|--------|--------------|-----------|----------------|---------------------------|
| First, 300 commits, rules v1 | First pass | `migration` | 31.7% (± 6) | about 53% | 0.78 with an AI second rater |
| First, 300 commits, rules v1 | Adjudicated | `migration` | 42.0% (± 6.4) | about 53% | 0.76 first pass vs adjudicated |
| Second, 200 commits, rules v2 | First pass | `migration_away` | 90.0% (± 5.9) | about 33% | none (the second copy was not independent) |
| Second, 200 commits, rules v2 | Adjudicated | `migration_away` | **84.0% (± 7.2)** | **about 58%** | **0.94 with a second person, blind, rows 1 to 100** |

Rules v2 on the adjudicated second sample, by group:

| Group | In full set | Labelled | Share yes (95% CI) |
|-------|-------------|----------|--------------------|
| away | 40,876 | 100 | 84.0% (75.6% to 89.9%) |
| other_kept | 46,947 | 50 | 16.0% (8.3% to 28.5%) |
| rejected | 166,942 | 49 | 10.2% (4.4% to 21.8%) |

So about 34,336 of the 40,876 `migration_away` commits are real migrations, and the rules miss about 24,546 more. The last row of the first table is the result for rules v2. The in-sample check on the first sample (86.3%, `research.validation.dev_check`) was close to it, so the rules were not overfitted. Kim (2026) reported 62% of matched commits as genuine, but with a different coding guide, so the numbers are not directly comparable.
