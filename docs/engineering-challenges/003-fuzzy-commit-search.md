# 003: GitHub's commit search is fuzzy

- **Date:** 2026-10-09
- **Area:** Research mining

## Context

The miner (Step 09) searches GitHub for each retired model ID in quotes, for example `"claude-3-haiku-20240307"`, and treats every result as a candidate migration commit.

## Symptom

The first real run did not finish: the miner kept waiting on GitHub refusals. To see what GitHub was really answering, I sent the same search by hand with `gh api -i`. It worked (200 OK, search quota untouched), but it reported **5,695** results, and the first one was a spam commit with no mention of Claude at all. Its SHA started with `20240307`, the date part of the model ID.

## Investigation

- `gh api rate_limit` showed 30 of 30 searches left, so it was not the normal search quota.
- The miner's requests differed from `gh`'s: no named `User-Agent` (GitHub's docs say every request must include a valid one), and the miner hid GitHub's actual message, so the reason for the refusal was invisible.
- The quoted search matched parts of the ID, not only the exact ID.

## Root cause

GitHub's commit search is built for people browsing, not for exact matching. Quotes do not guarantee that the whole ID appears in the message.

## Fix

- After searching, keep a result only if the message contains the exact ID as a whole word (`mentions()` in `research/mining/miner.py`). The number dropped is reported as `not_in_message`, so the paper can say how noisy the raw search was.
- Send a named `User-Agent`, and print GitHub's own message whenever it refuses a request.

## Follow-up: the same commit in many repositories

The fixed run searched one ID and reported 1,833 duplicates, which should be impossible for a single search with non-overlapping date windows. A check of the cache showed no commit in two windows, but many windows with far fewer unique SHAs than results (for example 892 results, 60 unique). So GitHub's paging was fine: the same commit appears in many different repositories that are not marked as forks (copies, mirrors, templates, spam networks). We keep one candidate per SHA, as Kim (2026) does, and now record every repository it was found in (`repos`), so the paper can report how many copies there were.

## Lesson

## Lesson

I learned not to trust a search engine's idea of a "match" when I'm building research data. GitHub said it found 5,695 commits for one model, but about 1,000 of them didn't mention the model at all, and a third of the rest were the same commit copied into other repositories. If I had used the raw numbers, my dataset would have been wrong before I even started.

So now I check every result against my own rule (the exact model ID must be in the message), and I count what I drop instead of hiding it. I also learned to look at the raw response when a tool says "rate limit". The real problem was a missing User-Agent header, not the limit.
