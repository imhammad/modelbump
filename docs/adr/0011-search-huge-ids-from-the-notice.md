# ADR 0011: Search hugely popular model IDs only from shortly before the deprecation notice

- **Status:** Accepted
- **Date:** 2026-10-11
- **Supersedes:** [ADR 0010](0010-hybrid-search-for-huge-ids.md)

## Context

ADR 0010 searched IDs with more than 50,000 results once per migration word. The first run with it showed that the words barely narrow the search. For `gemini-2.0-flash`, the word "replace" alone returned about 600 results every ten days. GitHub's commit search is fuzzy ([challenge 003](../engineering-challenges/003-fuzzy-commit-search.md)): it matches "replace", "gemini" and "flash" anywhere in a message, not as one phrase. Across 12 words, with overlaps, the focused search could cost about as much as the full one, and it would still miss migrations described without those words.

Kim (2026, Section 3) excludes every commit made more than 30 days before the provider announced the deprecation, because such a commit cannot be a reaction to the notice. Our dataset will apply the same exclusion.

## Decision

- An ID with **50,000 or fewer** results (`--focus-above`) is searched in full, as in ADR 0009.
- An ID with **more** results is searched in full, but only from **30 days before its earliest deprecation notice**. That date includes notices of rescheduled plans (`superseded` in the registry). It applies to all of the ID's aliases.
- If the registry has no notice date for a huge ID (Google gives none), the ID is searched in full, and `too_big_without_notice` in the stats records it.
- Migration words are not used inside the search. They stay a filter applied afterwards.
- The stats record each ID's total (`model_totals`) and the start date used for each narrowed ID (`focused_starts`).

## Alternatives considered

- **Migration words per search (ADR 0010):** tried, and it narrowed far less than expected because of fuzzy matching.
- **Search everything:** several days of laptop time for a handful of IDs.
- **Narrow every ID, not only the huge ones:** consistent, but it would throw away full searches already in the cache. Older commits for smaller IDs also stay useful for other questions, such as when a model was adopted.

## Consequences

- No candidate that our final dataset would keep is lost: the commits we skip are the ones Kim's exclusion removes anyway.
- The run needs far fewer searches for `gpt-4`, `gpt-3.5-turbo`, `gpt-5-codex` and `gpt-5.3-codex`.
- `gemini-2.0-flash` has no notice date, so it is searched in full. Its full results were already in the cache from before ADR 0010, so this costs no new searches.
- For narrowed IDs, the candidate set cannot be used to study adoption before the notice. Only the smaller IDs can.
