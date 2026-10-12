# ADR 0016: Place each migration on its model's retirement timeline

- **Status:** Accepted
- **Date:** 2026-10-12

## Context

Kim (2026) reports that 82% of migrations happened *after* the old model was shut down. That number is the paper's motivation, so Phase 1 checks it on our own data. We now have 40,876 commits labelled `migration_away`, with 84% precision on a fresh sample ([ADR 0015](0015-fresh-sample-for-rules-v2.md)), and a registry with notice and shutdown dates ([ADR 0006](0006-retirement-registry-format.md)).

The plan also lists diff statistics and repository metadata as enrichment. Both need one GitHub API call per commit or repository, which means tens of thousands of calls.

## Decision

- `research.enrichment.timing` writes one row per migration commit to `research/data/timing.jsonl`: the retired model it leaves, that model's notice and shutdown dates, and the commit's **phase**:
  - before the notice,
  - after the notice but before the shutdown,
  - after the shutdown,
  - or before the shutdown when no notice date is known.
- **Which model.** Only IDs the message moves away from count. If several qualify, the one shut down first is used, since it forced the change soonest. If the rules find none, every matched ID counts.
- **Which dates.** The shutdown is the current plan's date. The notice is the earliest one, counting rescheduled plans, as the miner already does.
- **Which models count for the headline.** Only models shut down by the end of the data (the last commit day). A model that is still running cannot have migrations made after its shutdown, so including it would push the share down.
- **The headline** uses OpenAI and Anthropic only, because their pages give exact dates. Google gives only an *earliest possible* shutdown day and no notice day ([ADR 0007](0007-rescheduled-retirements.md)), so its share is reported separately.
- Two variants are reported next to it:
  - **Kim's window:** only commits from 30 days before the notice. Kim excluded earlier commits, and the miner searched the five busiest IDs only from that day ([ADR 0011](0011-search-huge-ids-from-the-notice.md)).
  - **First migration per repository:** each repository's earliest move away from each model, so one busy repository does not count many times.
- **Diff statistics and repository metadata are left for later.** They will be fetched for a sample when a research question needs them, not for all 40,876 commits.

## Alternatives considered

- **Count every model a commit leaves:** commits leaving several models would count several times.
- **Use the shutdown date of the first plan for rescheduled models:** this would call some migrations "after shutdown" even though the model was still running.
- **Include Google with its earliest dates in the headline:** Google is almost half the data. But "after the earliest possible shutdown" is a weaker statement than "after the shutdown".

## Consequences

- The number we compare with Kim's 82% is a share of the commits our rules flag. About 16% of those are not real migrations, and the paper says so.
- The busiest IDs (gpt-4, gpt-3.5-turbo) shut down on 2026-10-23, after our data ends. Their migrations appear in the phase tables but not in the headline. A rerun after the shutdown would add them.
- Commit dates are the committer's dates, which can differ from when the change reached users.
