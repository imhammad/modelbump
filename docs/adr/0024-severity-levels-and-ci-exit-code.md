# ADR 0024: Severity levels, cloud forms of model IDs, and a CI exit code

- **Status:** Accepted
- **Date:** 2026-10-22

## Context

After [ADR 0023](0023-scanner-finds-ids-as-text-first.md), `modelbump scan` lists model IDs and their registry status. A user (or a CI job) needs more: how urgent each one is, and a way to make CI fail before a shutdown, not after it. Paper 1 found that most migrations come after the shutdown, with a median of 11 days late, so the point of the tool is a warning that comes early enough to act on.

Two gaps from Step S1 also hid retired models: cloud platforms write provider IDs in their own forms (Amazon Bedrock: `anthropic.claude-3-haiku-20240307-v1:0`; Google Vertex AI: `claude-3-5-sonnet@20240620`), and the registry only knows the provider's form.

The tool paper will replay the scanner on past commits to measure how early it would have warned. That needs the scanner to judge a finding as of a past day.

## Decision

- **Four severity levels**, computed from the registry for a check day:
  - `RETIRED`: the shutdown day has passed.
  - `RETIRING_SOON`: the shutdown is within the warning window, 90 days by default (`--soon-days`).
  - `DEPRECATED`: a shutdown is announced, but further away.
  - `UNKNOWN`: no retirement is announced (the ID is not in the registry).
- **90 days by default,** because providers usually give 2 to 6 months of notice (Anthropic gave claude-3-haiku-20240307 60 days, so it is `RETIRING_SOON` from its notice day).
- **`--fail-within N`** exits with code 1 when any finding is retired or shuts down within N days. Without it, the scan always exits 0, so adding ModelBump to CI never breaks a build until a team chooses a threshold. Code 2 stays Typer's code for bad arguments.
- **`--today YYYY-MM-DD`** checks as if it were that day. A model announced after that day is `UNKNOWN`, because nobody could have known yet. This keeps replays honest. The registry's current plan is used even when an earlier plan was in force on that day; the replay experiment will revisit this.
- **Cloud forms are mapped only when the result is in the registry** (`modelbump.scanner.resolve`): drop a Bedrock `-vN` suffix, or turn a Vertex `@` into `-`. The output shows both forms: `claude-3-haiku-20240307-v1 (= claude-3-haiku-20240307)`.

## Alternatives considered

- **Fail on any retired model by default:** safer in theory, but it would break existing builds on the first run and teach people to remove the check.
- **The master plan's PINNED_SNAPSHOT and ALIAS levels:** they describe how an ID is written (a dated snapshot or a floating alias), not how urgent it is. They will come as a separate field, so a finding can be both `ALIAS` and `RETIRING_SOON`.
- **Map every cloud form, even unknown ones:** would turn unknown IDs into guesses. Mapping only into the registry cannot create a wrong warning.

## Consequences

- CI can now block a merge before a model shuts down.
- The same code serves the product (today) and the replay experiment (`--today`).
- Google's shutdown dates are "earliest possible", so their severity can be too early but never too late.
