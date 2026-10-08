# ADR 0007: Keep rescheduled retirements as superseded plans

- **Status:** Accepted
- **Date:** 2026-10-08

## Context

ADR 0006 assumed each model ID has one retirement. OpenAI's deprecations page shows that is false. Some models appear in two sections with different dates, because OpenAI changed the plan:

- `gpt-4-0314`: announced 2023-06-13 with shutdown "at earliest 2024-06-13", then announced again on 2025-09-26 with shutdown 2026-03-26.
- `gpt-4-1106-preview`: shutdown 2026-03-26 (announced 2025-09-26), then 2026-10-23 (announced 2026-04-22).
- `code-davinci-002`: shutdown 2023-03-23 (announced 2023-03-20), then 2024-01-04 (announced 2023-07-06).

Google's page has a different problem: it gives no announcement dates, and says its shutdown dates are "the earliest possible dates on which a model might be retired".

## Decision

- Each model has **one entry**. Its main fields describe the **current** plan, which is the newest section on the page.
- Older plans go in a `superseded` list (announced, shutdown, `shutdown_is_earliest`), oldest first. The schema rejects a superseded plan that is not older than the current one.
- `shutdown_is_earliest: true` marks dates the provider only promises as a lower bound. Every Google entry has it.

## Alternatives considered

- **Keep only the newest plan:** simple, but loses the fact that a date moved. That fact matters for the research: "migrated after shutdown" depends on which date a developer saw at the time.
- **One entry per announcement:** looking up an ID would return several answers, and the scanner would have to pick one each time.

## Consequences

- Lookups stay simple: one ID gives one current plan.
- The research code can count how often providers postpone retirements, and test results against both the old and new dates.
- Status is always computed from the current plan, so a model whose old date has passed but whose new date has not is still reported as deprecated, not retired.
