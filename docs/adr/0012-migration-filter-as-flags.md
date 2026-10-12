# ADR 0012: Label migration commits with one flag per rule, and keep AI-assisted commits separate

- **Status:** Accepted
- **Date:** 2026-10-12

## Context

The full mining run (ADRs 0009 and 0011) produced 254,765 candidate commits that mention a retired model ID. A first look at them showed:

- 41.3% use one of Kim's migration words exactly, and 55.8% use one in any form ("migrated", "replacing").
- 41.2% carry an AI-tool trailer such as `Co-Authored-By: Claude`. Kim (2026, Section 3) excludes AI-tool commits.
- Many messages move *into* a retired model ("revert to gemini-2.0-flash", "update Gemini model to gemini-2.0-flash"). Kim excludes migrations into a model.
- 47.5% only mention Google models, and Google publishes no deprecation notice dates, so Kim's rule "not more than 30 days before the notice" cannot be checked for them.
- 0.4% use dependency-bot wording.

## Decision

- Keep every candidate. Record each rule as its own field in `labeled.jsonl`: `migration_word`, `direction` (away / into / unclear), `after_notice_start` (true / false / unknown), `bot`, `ai_trailer`, `ai_style`.
- **`migration`** (Kim's rules): a migration word in any common form, direction not "into", not before notice minus 30 days (unknown counts as passing), not a bot, no AI-tool trailer.
- **`migration_strict`**: `migration`, and the direction is clearly "away" ("from X", "X to Y", "X -> Y", "replace X with", "remove X", "X is deprecated").
- **`migration_with_ai`**: the same rules, but with an AI-tool trailer. These are counted separately, not thrown away.
- Direction is decided per model ID, and a commit is "away" if it moves away from any of its IDs.
- The rules are regular expressions in `research/filtering/rules.py`, each tested against real messages from the run.

## Alternatives considered

- **Delete commits that fail a rule:** simpler files, but every change to a rule would mean rerunning and could not be audited.
- **Drop AI-tool commits like Kim:** keeps the comparison fair, and the `migration` label does this. Deleting them, though, would hide that AI tools write a large share of 2026's migrations, which is a finding in its own right.
- **A machine-learning classifier:** possibly more accurate, but it needs labelled training data, which we do not have yet. The manual validation sample (next step) gives us that data, so this could be revisited.

## Consequences

- The paper can report the funnel rule by rule, and any number can be recomputed with a rule switched off.
- Rule-based direction detection will make mistakes. Its precision has to be measured on a manually labelled random sample, as Kim did with 300 commits, before any number is reported.
- Commits written in other languages (some are in Japanese or Spanish) mostly fail the English migration-word rule. This is a known limitation.
- Bots are detected from the message only. The commit author is in the raw cache and could be added later.
