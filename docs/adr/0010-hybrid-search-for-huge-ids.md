# ADR 0010: Search hugely popular model IDs together with migration words

- **Status:** Superseded by [ADR 0011](0011-search-huge-ids-from-the-notice.md)
- **Date:** 2026-10-11
- **Amends:** [ADR 0009](0009-mining-method.md)

## Context

ADR 0009 searches every commit that mentions a model ID and applies migration words afterwards. The first full run showed that this does not scale to the most popular IDs. After a night of mining, the run reached `gpt-4` (ID 59 of 139) and had split its date range in half 10 times, down to windows about one day wide, because nearly every day since 2023 has more than 1,000 commits mentioning it. GitHub's fuzzy search makes it worse: a search for `gpt-4` also returns commits that only mention `gpt-4o` or `gpt-4-turbo`, which our exact-ID filter throws away only after they have been downloaded. At one search every 10 seconds, plus GitHub's secondary-limit refusals, IDs like `gpt-4`, `gpt-4o` and `gpt-3.5-turbo` would take days each.

## Decision

- Before searching an ID, read GitHub's `total_count` for the whole date range (the first search the miner makes anyway).
- If it is **50,000 or fewer** (`--focus-above`), search all of the ID's commits as in ADR 0009.
- If it is **more**, search the ID together with each migration word from Kim (2026, Section 3), one search per word: migrate, replace, switch, upgrade, update, remove, drop, swap, retire, deprecate, sunset, "shut down". Windows are still split at the 1,000 cap, and results still go through the exact-ID filter, the fork filter and SHA de-duplication.
- Record each ID's `total_count` (`model_totals`) and which IDs used migration words (`focused_ids`) in `candidates.stats.json`, so the paper can report both.
- `--counts` prints every ID's total without mining, so the threshold can be checked against real numbers before a long run.

## Alternatives considered

- **Keep searching everything:** the most complete data, but several days of laptop time for a handful of IDs, most of whose commits are not migrations anyway.
- **Migration words for every ID:** simpler and closer to Kim, but it would throw away the full search already finished for the smaller IDs, and it misses migrations described without those words.
- **Keep only the first few pages per window, as Kim did:** fast, but the sample would depend on how GitHub orders results, which we cannot control.

## Consequences

- The full run finishes in hours instead of days.
- For the focused IDs, migrations whose message uses none of the words (for example "use gpt-4o") are missed. Their counts are lower bounds, as Kim's are, and the paper must say so.
- We do not know whether GitHub's search matches word forms (does "migrate" find "migrated"?). Step 11 checks this on the cached results.
- An ID whose full search was already finished before this change, but which is over the threshold, is now searched the focused way. Its full results stay in the cache, which lets us measure how much the migration words miss for that ID.
