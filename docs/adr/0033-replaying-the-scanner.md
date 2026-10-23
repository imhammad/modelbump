# ADR 0033: Replay the scanner on the snapshots before each migration

- **Status:** Accepted
- **Date:** 2026-10-23

## Context

The tool paper has to show that ModelBump would have helped real projects, not only that it finds model IDs. Paper 1 found that projects migrate a median of 11 days *after* the shutdown. The question for the tool is: had a project run `modelbump scan`, would it have been warned, and how early?

The scanner's evaluation set ([ADR 0029](0029-scanner-evaluation-set.md)) already holds 100 migration commits, each with the snapshot of the repository just before the migration. `modelbump scan --today DAY` replays any past day honestly: a model whose deprecation was announced after that day is `UNKNOWN` ([ADR 0024](0024-severity-levels-and-ci-exit-code.md)).

## Decision

- **Flagged:** a project is flagged if the current scanner reports the model the commit moved away from (any alias, Bedrock or Vertex form) anywhere in its snapshot, including files fetched for missed sites ([ADR 0032](0032-rescoring-after-a-scanner-change.md)). This is counted for all four settings: all findings, `--skip-comments`, `--skip-tests`, and both.
- **First warning:** the first day `assess` says more than `UNKNOWN`, which is the provider's notice day. Models without a notice date in the registry (some Google models) are flagged but get no first-warning day.
- **CI failure:** with `--fail-within 30`, the scan fails from 30 days before the shutdown. For flagged projects that migrated only after the shutdown, we report how many days earlier CI would have failed.
- **Reported:** the share flagged with a Wilson interval, and medians with distribution-free 95% intervals (`median_ci` from Paper 1's lag analysis, unchanged).
- **New code only:** `research/scanner_eval/replay.py` reads the commit day from `research/data/timing.jsonl` and changes nothing.

## Alternatives considered

- **Replay on all 40,876 migrations:** a much larger sample, but it needs a snapshot of every repository, which means tens of thousands of downloads.
- **Snapshots on the notice day instead of before the migration:** closer to what a user would have seen on that day, but it needs a second download per commit and finding the commit in force on that day.

## Consequences

- The snapshot is the code just before the migration, not on the notice day. A project that added the model after the notice would have been warned later than we report, so the warning lead is an upper bound. The paper must say so.
- The registry is today's. On the notice day, a real user would only have been warned if the registry already had the notice. The lead time assumes it was added on that day.
