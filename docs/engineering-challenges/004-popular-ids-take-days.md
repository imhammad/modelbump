# 004: Popular model IDs would take days to mine

- **Date:** 2026-10-11
- **Area:** Research mining

## Context

The miner (Step 09, ADR 0009) searches GitHub for every commit that mentions a retired model ID, splitting the date range whenever a search has more than GitHub's 1,000-result cap.

## Symptom

The full run worked through the night and was only at ID 59 of 139 the next afternoon. It was stuck on `gpt-4`, with a long line of "secondary rate limit" waits, and the cache had grown from about 7,700 to 9,300 files mostly for that one ID. It also crashed once with `httpx.ConnectError: nodename nor servname provided`.

## Investigation

- The traceback showed `search_window` calling itself 10 times: the date range had been halved 10 times, to windows about one day long. So almost every single day had more than 1,000 commits mentioning `gpt-4`.
- GitHub's search is fuzzy ([challenge 003](003-fuzzy-commit-search.md)), so those results also include `gpt-4o`, `gpt-4-turbo` and `gpt-4.1` commits that the exact-ID filter drops only after downloading them.
- Internet speed was not the limit. Each search is small; the time goes to the deliberate 10-second gap between searches and to GitHub's refusals.
- The `ConnectError` meant the Mac could not look up `api.github.com` for a moment (the Wi-Fi dropped). The miner had no retry for network errors, so the whole run stopped.

## Root cause

Searching every commit that mentions an ID costs roughly one request per 100 results. That is fine for most IDs, but a few IDs are mentioned in so many commits that a complete search would take days at a pace GitHub accepts.

## Options considered

- Keep searching everything and wait several days.
- Search every ID together with migration words, as Kim (2026) did.
- A hybrid: full search for most IDs, migration words only for the huge ones.

## Fix

The hybrid ([ADR 0010](../adr/0010-hybrid-search-for-huge-ids.md)): IDs with more than 50,000 results are searched once per migration word. `--counts` shows each ID's total before a long run. Network errors are now retried with growing waits (1, 2, 4 ... minutes), and if the network stays down the miner stops cleanly with a message instead of a traceback. The miner also prints each date window it downloads, so a long search no longer looks frozen.

## Lesson

I assumed the slow part was my internet. It was the amount of data. Before a long mining run, measure how big each search is first, and design for the biggest ones, not the typical ones.

## Follow-up: migration words did not narrow enough

The first run with ADR 0010 showed that searching an ID together with a migration word is fuzzy too. For `gemini-2.0-flash`, "replace" alone returned about 600 results every ten days, so the 12 words together would have cost almost as much as the full search. [ADR 0011](../adr/0011-search-huge-ids-from-the-notice.md) replaces the words with a date rule taken from Kim (2026): huge IDs are searched only from 30 days before the deprecation notice, because older commits are excluded from the dataset anyway. The lesson is the same, measured again: check how much a fix actually cuts, on real data, before trusting it.
