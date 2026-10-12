# ADR 0014: Filter rules v2, a `migration_away` label, and a fresh sample to measure them

- **Status:** Accepted
- **Date:** 2026-10-12

## Context

The 300-commit validation sample (ADR 0013) was labelled by hand, re-checked, and scored (adjudicated labels):

| Stratum (rules v1) | In full set | Labelled `yes` |
|---|---:|---:|
| strict | 10,940 | 86 of 100 (78% to 92%) |
| broad_only | 28,241 | 25 of 100 (18% to 34%) |
| with_ai | 35,318 | 17 of 50 (22% to 48%) |
| rejected | 180,266 | 4 of 50 (3% to 19%) |

Reading the rows by what the rules decided showed three things:

- **The "away" direction is the strong signal.** Of the 107 sampled rows the v1 rules called "away", 96 were labelled `yes`. That includes all 7 "away" rows with an AI-tool trailer, and all 3 "away" rows that were rejected only for being more than 30 days before the notice.
- **v1 misses common ways of saying a model is gone.** Most `yes` rows in the broad stratum say so without "from X" or "X to Y": "X was retired", "X is no longer served", "X returns 404", "remove A and X", "Y replaces X".
- **The migration word adds little once the direction is clear.** Every sampled "away" row also had a migration word.

## Decision

- **Rules v2** add four "away" shapes to `research/filtering/rules.py`: a statement that the model is gone within 40 characters on the same line (`deprecated`, `retired`, `discontinued`, `sunset`, `removed`, `shut down`, `no longer`, `not available`, `unavailable`, `404`); a removal verb within 60 characters on the same line (`remove`, `drop`, `purge`, `deactivate`); "X model to Y"; and "replaces/supersedes X". More adjectives are allowed before an ID ("unavailable model id X").
- **A new label, `migration_away`**: the direction is "away" and the message is not from a dependency bot, whatever the date, the wording or an AI-tool trailer. Kim's labels (`migration`, `migration_strict`, `migration_with_ai`) keep their definitions and now use the v2 direction.
- `labeled.stats.json` records `rules_version: 2`.
- `research.validation.dev_check` reruns the rules on the labelled sample. Its numbers are **in-sample** and used only to develop the rules.
- The quality of rules v2 will be measured on a **fresh random sample** drawn from the v2 labels and labelled blind (next step), not on the 300 rows the rules were tuned on.

## Alternatives considered

- **Re-score v2 on the same 300 rows:** cheap, but the rules were written from these rows, so the numbers would be too good. They are reported only as development numbers.
- **Keep only Kim's rules:** keeps the comparison simple, but the sample shows that the AI-trailer and 30-day exclusions remove real migrations. `migration_away` keeps them, and the exclusions stay available as flags.
- **A machine-learning classifier:** 300 labels are too few to train and test one honestly. This may be revisited once more labelled data exists.

## Consequences

- On the labelled sample (in-sample), "away" goes from 96 of 107 rows labelled `yes` to 113 of 131, and from catching 96 to 113 of the 132 `yes` rows. The new "gone" shapes also flag some notes and news ("X was retired" in a changelog), which is the main known source of false positives.
- The funnel numbers in the paper change, so Step 11's numbers must be reported as rules v1 and the new ones as rules v2.
- The first-pass labels, the AI second rater's reading and the adjudicated labels are all kept, so the re-check can be reported in full (see [validation](../research/validation.md)).
