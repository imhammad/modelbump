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
