# Filtering protocol: which candidates are migrations

**Code:** `research/filtering/` · **Decision:** [ADR 0012](../adr/0012-migration-filter-as-flags.md) · **Input:** the candidates from [mining](mining.md)

## Goal

Decide which candidate commits are migrations *away* from a retired model, using the rules of Kim (2026, Section 3), and record why every other candidate was excluded.

## Rules

| Field | Meaning |
|-------|---------|
| `migration_word` | The message uses migrate, replace, switch, upgrade, update, remove, drop, swap, retire, deprecate, sunset or shut down, in any common form ("migrated", "replacing", "shutdown") |
| `direction` | `away` ("from X", "X to Y", "X -> Y", "replace X with", "remove X", "X is deprecated"; since rules v2 also "X was retired", "X is no longer served", "X returns 404", "remove A and X", "Y replaces X"), `into` ("to X", "use X", "revert to X", "-> X"), or `unclear` |
| `after_notice_start` | The commit is on or after 30 days before the earliest deprecation notice. `null` when the provider gives no notice date (Google) |
| `bot` | Dependency-bot wording (Dependabot, Renovate, "Bump x from 1 to 2") |
| `ai_trailer` | An AI coding tool's trailer, such as `Co-Authored-By: Claude` or "Generated with Claude Code" |
| `ai_style` | The first line reads like a chat assistant ("I'll help you ...") |

## Labels

| Label | Rule |
|-------|------|
| `migration` | `migration_word`, direction not `into`, `after_notice_start` not false, not `bot`, not `ai_trailer` |
| `migration_strict` | `migration`, and direction `away` |
| `migration_with_ai` | Same as `migration`, but with an AI-tool trailer |
| `migration_away` | Direction `away` and not `bot`, whatever the date, migration word or AI trailer (rules v2, [ADR 0014](../adr/0014-filter-rules-v2.md)) |

## Running it

```
uv run python -m research.filtering.filter
```

It reads `research/data/candidates.jsonl` and writes `research/data/labeled.jsonl` (every candidate with the fields above) and `research/data/labeled.stats.json`, and prints how many candidates survive each rule.

## Rules versions

`labeled.stats.json` records `rules_version`. Version 1 is Step 11 (ADR 0012). Version 2 adds the "away" shapes above and `migration_away` (ADR 0014).

## Validation

The rules are tested on real messages from the run, but their precision on the whole set is unknown until a random sample is labelled by hand. See [validation](validation.md).
