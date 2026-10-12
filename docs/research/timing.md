# Timing: when did projects migrate?

**Code:** `research/enrichment/timing.py` · **Decision:** [ADR 0016](../adr/0016-migration-timing.md) · **Input:** the labels from [filtering](filtering.md), measured in [validation](validation.md)

Kim (2026) reports that 82% of migrations happened *after* the old model was shut down. This step checks that on our data.

## Running it

```
uv run python -m research.enrichment.timing
```

It reads `research/data/labeled.jsonl` and writes:

| File | Contents |
|------|----------|
| `research/data/timing.jsonl` | One row per `migration_away` commit: `sha`, `repo`, `url`, `committed`, `model_id`, `provider`, `notice`, `shutdown`, `shutdown_is_earliest`, `phase`, `days_from_shutdown`, `in_kim_window` |
| `research/data/timing.stats.json` | The phase counts and the headline shares, for the paper |

Options:

- `--label migration` scores Kim-style labels instead of `migration_away`.
- `--retired-by 2026-10-23` changes which models count as shut down. The default is the last commit day in the data.

## Phases

| Phase | Meaning |
|-------|---------|
| before the notice | Committed before the provider announced the deprecation |
| after the notice, before shutdown | Committed between the announcement and the shutdown day |
| after the shutdown | Committed on or after the shutdown day |
| before shutdown, no notice date | Before the shutdown, for a model with no known announcement (all of Google) |

## Reading the headline

- **OpenAI + Anthropic (exact dates)** is the number to compare with Kim's 82%. It counts only models already shut down when the data ends.
- **From notice minus 30 days** drops older commits, as Kim did.
- **First migration per repository** counts each repository once per model.
- **Google** is shown separately, because its shutdown days are only the earliest possible ones.

Keep in mind that about 16% of `migration_away` commits are not real migrations ([validation results](validation.md#results)). So the share describes the flagged commits, not a hand-checked set.

## Results

Run on 12 October 2026 on the 40,876 `migration_away` commits (rules v2).

**Models shut down by the end of the data (2026-10-09):**

| Phase | Anthropic | Google | OpenAI | All |
|-------|-----------|--------|--------|-----|
| before the notice | 1,573 | 0 | 1,069 | 2,642 |
| after the notice, before shutdown | 2,247 | 0 | 910 | 3,157 |
| after the shutdown | 6,537 | 11,422 | 1,418 | 19,377 |
| before shutdown, no notice date | 0 | 9,073 | 0 | 9,073 |

**Models shut down at least 90 days before the end** (`--retired-by 2026-07-11`), which gives every model time for late migrations to show up:

| Phase | Anthropic | Google | OpenAI | All |
|-------|-----------|--------|--------|-----|
| before the notice | 1,493 | 0 | 402 | 1,895 |
| after the notice, before shutdown | 2,218 | 0 | 512 | 2,730 |
| after the shutdown | 6,481 | 11,421 | 1,138 | 19,040 |
| before shutdown, no notice date | 0 | 9,067 | 0 | 9,067 |

**Share made after the shutdown:**

| Counting rule | Shut down by 2026-10-09 | Shut down by 2026-07-11 |
|---------------|-------------------------|-------------------------|
| OpenAI + Anthropic (exact dates) | 57.8% (7,955 of 13,754) | 62.2% (7,619 of 12,244) |
| same, from notice minus 30 days | 66.8% (7,955 of 11,913) | 69.2% (7,619 of 11,006) |
| same, first migration per repository | 57.6% (7,038 of 12,222) | 61.6% (6,742 of 10,947) |
| Google (earliest possible dates) | 55.7% (11,422 of 20,495) | 55.7% (11,421 of 20,488) |

### What this means

- **Most migrations come after the shutdown, but fewer than Kim found.** Depending on the counting rule, 58% to 69% of migrations away from OpenAI and Anthropic models were made after the shutdown. Kim (2026) reports 82%.
- **Late shutdowns explain only a small part of the gap.** Giving every model at least 90 days of follow-up raises the share by about 4 points (57.8% to 62.2%). The rest of the gap remains.
- **It is not one provider.** With 90 days of follow-up, Anthropic is at 64% (6,481 of 10,192) and OpenAI at 55% (1,138 of 2,052).
- **Some projects move early.** 1,895 commits, about 15% of the exact-date set, left a model before its deprecation was announced. Those are ordinary upgrades, not reactions to a retirement. Kim's window drops most of them, which is why it gives the highest share.
- **Possible reasons for the rest of the gap**, none of which can be tested with this data alone: Kim's study may cover other models and another time span; about 16% of our flagged commits are not real migrations; and our rules miss about 42% of real migrations, which may differ in timing from the ones they catch.

For the paper: *between 58% and 69% of migrations happened after the shutdown (Kim: 82%). The direction is the same, the size is smaller.*
