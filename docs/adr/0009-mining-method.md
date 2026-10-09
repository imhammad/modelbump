# ADR 0009: Mine with one search per model ID and split windows at the cap

- **Status:** Accepted
- **Date:** 2026-10-08

## Context

Phase 1 builds our own dataset of commits that migrate away from retired LLM models, because the dataset of the study we build on (Kim, arXiv:2609.31288) is not released yet. According to its Method section, that study used GitHub's commit-search API with 22 query strings that combine retired model IDs with migration words, searched quarterly and monthly windows, excluded forks and de-duplicated by SHA. Its Threats section says GitHub returns at most 1,000 results per search and that its windows kept only the first 200 to 300, so its counts are lower bounds.

## Decision

- **One search per model ID** (and per alias) in the registry, matching the exact ID in commit messages. Migration words are applied afterwards, on our side, not inside the search.
- **Adaptive windows:** search the whole date range first. If GitHub reports more than 1,000 results, split the window in half and search each half, until every window fits or is a single day. Single days that still overflow are recorded as truncated.
- Every raw response is cached on disk with its query and fetch time. Forks are dropped and commits are de-duplicated by SHA.
- IDs that are ordinary words or very short (`ada`, `babbage`, `curie`, `davinci`, `o1`) are not searched on their own; their dated versions are.

## Alternatives considered

- **Copy the study's 22 queries exactly:** the paper does not list the strings, so we could not reproduce them anyway.
- **Put migration words inside the search:** fewer results to download, but the word list would be frozen into the data. Filtering afterwards lets us change and test the rules without searching again.
- **GH Archive / BigQuery:** complete event history, but costs money and needs a separate pipeline. It could later be used to check how much the search API misses.

## Consequences

- Our candidate set should be more complete than a capped one, and we can report exactly which windows were truncated.
- Searching 139 IDs and aliases takes more requests, at 30 searches per minute. The cache makes reruns free and lets a run resume after it stops.
- Because the search API's results can change over time, the cache is the record of what we saw, and the dataset card will give the fetch dates.
