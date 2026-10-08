# ADR 0006: Retirement registry as YAML files checked by a pydantic schema

- **Status:** Accepted
- **Date:** 2026-10-08

## Context

The scanner (Phase 2) must know which model IDs are being retired and when, and the research (RQ1) needs the same dates to measure how early a warning could have come. Providers publish this on their own deprecation pages, in different layouts, and those pages change over time. We need one format that people can read and review in a PR, that a program can check, and that ships inside the installed package so `modelbump` works offline.

## Decision

- One YAML file per provider in `src/modelbump/registry/data/` (for example `anthropic.yaml`). Each file records the `source_url` it was copied from and the `retrieved` date.
- Each entry has `id`, optional `aliases`, `announced`, `shutdown`, `replacement` and `notes`.
- A pydantic v2 schema validates every file when it is loaded. Unknown fields are errors (`extra="forbid"`), the shutdown date may not be before the announcement date, and the same ID may not appear twice across all files.
- The data lives inside the package (not in a top-level `registry/` folder as the first plan said), so it is included in the wheel and read with `importlib.resources`.

## Alternatives considered

- **JSON:** no comments, which we need to explain odd data.
- **A database (SQLite):** binary, so changes cannot be reviewed in a PR diff.
- **Scraping the pages at run time:** slow, needs network, and breaks whenever a page layout changes.
- **dataclasses with hand-written checks:** pydantic gives clear error messages and type conversion for free.

## Consequences

- A typo in a data file fails CI instead of producing wrong warnings.
- The registry only knows what a page said on the `retrieved` date. Pages are rewritten, so for history we also need archived copies (Internet Archive), which is the next step.
- `replacement` is what the page recommends **today**. For example, the page now lists `claude-opus-4-8` as the replacement for `claude-2.0`, a model that did not exist when `claude-2.0` was retired. Research code must not treat `replacement` as the historical recommendation.
- Adding a provider means adding a YAML file and a value to the `Provider` enum.
