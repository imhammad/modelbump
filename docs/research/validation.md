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
