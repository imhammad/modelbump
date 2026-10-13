# Targets: what do projects migrate to?

**Code:** `research/enrichment/targets.py`, `research/validation/targets_check.py` · **Decision:** [ADR 0017](../adr/0017-lag-and-migration-targets.md) · **Input:** the labels from [filtering](filtering.md)

For each migration away from a retired model, this step finds the model the project moved to and describes the switch. It is the paper's RQ3.

## Running it

```
uv run python -m research.enrichment.targets
uv run python -m research.enrichment.targets --per-repo --out research/data/targets_per_repo.jsonl
```

It reads `research/data/labeled.jsonl` and writes:

| File | Contents |
|------|----------|
| `research/data/targets.jsonl` | One row per `migration_away` commit (see below) |
| `research/data/targets.stats.json` | Every count printed, for the paper |

`--per-repo` keeps only each repository's first migration away from each model, so a busy repository counts once.

| Field | Meaning |
|-------|---------|
| `model_id`, `provider` | The retired model the commit leaves, chosen as in [timing](timing.md) |
| `target` | The model it moves to, or `null` if the message names none |
| `target_method` | The pattern that found it: `arrow`, `from_to`, `replace_with`, `instead_of`, `switch_to`, `now_uses`, `any_arrow` or `only_other` |
| `target_provider`, `same_provider` | Who makes the target, and whether it is the same provider |
| `recommended`, `follows` | The registry's recommended replacement, and `exact`, `same_line`, `other`, `none_listed` or `no_target` |
| `target_retired_list` | The target is itself in the retirement registry today |
| `target_announced_before` | The target's own retirement was already announced on the commit day |
| `target_shut_down_before` | The target was already shut down on the commit day |
| `ai_assisted` | The commit has an AI-tool trailer, or a Replit Agent, Lovable or Claude Code marker |
| `tier_change` | `up`, `same` or `down` between small, standard and large tiers |
| `generation_change` | `up`, `same` or `down` within the same series, or `unknown` |

## How a target is found

The patterns are tried in this order, and the first one that names a usable model wins:

| Method | Example |
|--------|---------|
| `arrow` | `gpt-4 -> gpt-4o`, `gpt-4 to gpt-4o` |
| `from_to` | `from gpt-4 (deprecated) to the new gpt-4o` |
| `replace_with` | `replace gpt-4 with gpt-4o` |
| `instead_of` | `use gpt-4o instead of gpt-4`, `gpt-4o replaces gpt-4` |
| `switch_to` | `switch default model to gpt-4o` |
| `now_uses` | `replaced with gpt-4o`, `defaults are now gpt-4o`, `now uses gpt-4o` |
| `any_arrow` | `model: gpt-4-0613 (old) -> gpt-4o` |
| `only_other` | the message names exactly one other model |

An alias of the model being left is never the target. Neither is another retired model that the message clearly leaves, nor a model listed right next to the one left ("remove X, Y"). A wildcard like `gemini-2.5-*` is not a model. If no pattern matches and the message names no other model, or several, the commit has no target.

## Checking it against the hand labels

```
uv run python -m research.validation.targets_check
uv run python -m research.validation.targets_check --dir research/data/validation_adjudicated
```

For every row labelled `yes` with `to_model` filled in, it runs the extraction on the full commit message and compares the result with the hand label. A date or snapshot ending does not count as a difference (`gpt-4o` and `gpt-4o-2024-08-06` agree). It prints the agreement on the model and on the provider, with 95% Wilson intervals, and writes `targets_check.csv` into the sample folder. Sort that file by `verdict` to read the disagreements.

- A hand label with no model ID in it ("current haiku alias") is left out and counted.
- A hand label that gives only a version the code's target extends ("gemini-2.5" for `gemini-2.5-flash`) counts as the same model, except for GPT names.
- When a commit leaves several models and the hand label picked another one than the code, the check uses the hand label's model, since it measures the target for a given model left.

The rules were first written without looking at either sample. They were then tuned on the first sample's disagreements only ([ADR 0017](../adr/0017-lag-and-migration-targets.md#revision-13-october-2026-rules-tuned-on-the-first-sample-only)), so the second sample (the default) is still a held-out test. The paper reports its score before and after the change.

## Reading it

- **The recommended replacement is today's.** Provider pages list what they recommend now, not what they recommended when the commit was made ([ADR 0006](../adr/0006-retirement-registry-format.md)). So `same_line` (for example any newer Sonnet for a retired Sonnet) is the fairer measure, and `exact` is a lower bound.
- **Tier and generation come from names only:** `mini`, `nano`, `haiku`, `lite` are small; `opus`, `pro`, `ultra`, `large` are large; the number in the name is the generation. They are rough labels, not price or capability comparisons.
- About 16% of the commits are not real migrations ([validation](validation.md#results)).
