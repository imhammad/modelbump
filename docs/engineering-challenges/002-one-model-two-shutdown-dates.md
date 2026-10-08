# 002: One model, two shutdown dates

- **Date:** 2026-10-08
- **Area:** Registry data

## Context

Step 07 built the registry with a rule: the same model ID may not appear twice. That rule catches copy-paste mistakes. The next job was to add OpenAI's retirements.

## Symptom

While collecting OpenAI's data, the same IDs kept turning up in two different sections of the page with two different shutdown dates. For example, `gpt-4-1106-preview` is listed for shutdown on 2026-03-26 and again for 2026-10-23. With the Step 07 rule, the data could not even be loaded.

## Investigation

I checked each duplicate against the page. There were two kinds:

1. **Real reschedules.** OpenAI announced a date, then later announced a new one (`gpt-4-0314`, `gpt-4-1106-preview`, `code-davinci-002`).
2. **Not a shutdown at all.** The 2024-08-29 entry for `babbage-002` and `davinci-002` only stopped *new fine-tuning*; the models kept working. So it does not belong in a retirement registry.

## Root cause

The schema matched one provider's page (Anthropic's), where every model is listed once. It did not match how retirements really happen: plans change.

## Options

- Keep only the newest date (loses information the research needs).
- Allow several entries per ID (lookups become ambiguous).
- One entry with the current plan plus a list of earlier plans.

## Fix

The third option, recorded in [ADR 0007](../adr/0007-rescheduled-retirements.md): a `superseded` list, plus a `shutdown_is_earliest` flag for Google's "earliest possible" dates. Fine-tuning-only entries are left out.

## Lesson

Read real data before fixing a schema. A validation rule that looks obviously right ("no duplicates") can encode a wrong assumption about the world, and the data is what tells you what exactly the real case is.
