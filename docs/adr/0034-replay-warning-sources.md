# ADR 0034: Say why each flagged project was warned, and re-check labels the sheet cut off

- **Status:** Accepted
- **Date:** 2026-10-23

## Context

The first replay ([ADR 0033](0033-replaying-the-scanner.md)) flagged 96 of 100 projects, but gave a first-warning day for only 32 of them. The other 64 fell into two groups that the output did not separate:

- 45 used Google models. The registry has no notice day for them, only the earliest shutdown day ([ADR 0007](0007-rescheduled-retirements.md)). For such a model the scanner says `DEPRECATED` on any day before the shutdown, which does not tell anyone when to act.
- 19 used Anthropic or OpenAI models but migrated before the provider's notice. They moved early on their own, so there was nothing to warn about yet.

The first version also searched for the notice day only three years back, so a notice older than that would have been reported as exactly three years.

The re-score also kept one "real" finding marked as `prose`. It was a mislabel, not a scanner error: the ID (`o1`) sat in a Python comment, `# Hide system_message for o1 models`, inside code stored in a Langflow flow file, 5,967 characters into the line. The sheet shows only the first 300 characters of a line, so the labeller could not see the ID. Five labelled rows had their ID beyond that cut.

## Decision

- **Warning source, per project:** `notice` (the provider's notice day), `retiring soon (no notice date)` (90 days before the shutdown, when the scanner says `RETIRING_SOON`), `migrated before the notice`, or `migrated before the warning window`.
- **The first-warning day is read from the registry**, not searched for, so there is no look-back limit.
- **Re-check rows the sheet cut off.** The labeller re-labels the rows whose ID was not visible, from the text around the ID, and writes `re-checked` in `note`. The first-pass labels stay in `sheet_labelled.csv`, and `rescore --sheet sheet_labelled.csv` reports them, so both versions can be given, as in Paper 1.
- **Reported:** the count for each source, and the median days from the first warning to the migration for each warned source and for both together.

## Consequences

- Google projects now count from the 90-day window, so their warning lead is a lower bound: the provider's own emails may have come earlier.
- Five labels changed after the labeller saw scanner output for them. The paper reports both versions and says why.
- The 19 early movers are not a weakness of the tool. The paper reports them as projects that did not need it.
