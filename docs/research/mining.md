# Mining protocol: candidate migration commits

**Code:** `research/mining/` · **Decisions:** [ADR 0008](../adr/0008-research-code-separate-from-product.md), [ADR 0009](../adr/0009-mining-method.md)

## Goal

Collect public commits whose message mentions a retired LLM model ID from our [retirement registry](../architecture/registry.md). This is the **candidate** set. Deciding which candidates are real migrations is the next step.

## Method

1. Take every model ID and alias in the registry, except IDs that are ordinary words or very short (`ada`, `babbage`, `curie`, `davinci`, `o1`).
2. For each ID, search GitHub's commit-search API for `"<id>" committer-date:<start>..<end>`, sorted by committer date.
3. If a search reports more than 1,000 results (GitHub's cap), split the date window in half and search each half. Repeat until every window fits. Record any single day that still overflows.
4. Keep a result only if its message contains the exact ID as a whole word (GitHub's search is fuzzy; see [challenge 003](../engineering-challenges/003-fuzzy-commit-search.md)). Drop commits from forks. Merge results with the same SHA into one candidate. The same commit is often found in many repositories (non-fork copies, mirrors, templates) and by more than one ID; the candidate lists every repository and every ID.
5. Save every raw response, with its query and fetch time, in `research/data/cache/`.

## Outputs

| File | Contents |
|------|----------|
| `research/data/candidates.jsonl` | One commit per line: `sha`, `repo` (first found), `repos` (all), `url`, `committed_at`, `message`, `matched_ids`, `providers` |
| `research/data/candidates.stats.json` | Date range, number of IDs, searches, results seen, forks skipped, results without the ID, duplicates, truncated windows |
| `research/data/cache/*.json` | Every raw GitHub response |

`research/data/` is not committed to git. The dataset will be published with a dataset card at the end of Phase 1.

## Running it

```
export GITHUB_TOKEN=$(gh auth token)
uv run python -m research.mining.miner --only claude-3-haiku-20240307
uv run python -m research.mining.miner --end 2026-10-08
```

The second command searches every ID. A fixed `--end` date keeps the search the same if you rerun it, which matters for reproducibility. If it stops, run the same command again: cached searches are not repeated.

## Differences from Kim (2026)

| | Kim (2026), per its Method and Threats sections | This protocol |
|---|---|---|
| Queries | 22 strings: retired IDs combined with migration words | One per model ID; migration words applied afterwards |
| Windows | Quarterly, then monthly | Adaptive: split until each window is under the 1,000 cap |
| Cap | First 200 to 300 results per window kept; counts are lower bounds | Truncation avoided where possible, and recorded where not |
| Forks, duplicates | Excluded; de-duplicated by SHA | Same |
