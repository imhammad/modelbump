# ADR 0031: Mark IDs that only describe a model, and let users skip test files

- **Status:** Accepted
- **Date:** 2026-10-23

## Context

The first precision measurement ([ADR 0029](0029-scanner-evaluation-set.md), [ADR 0030](0030-scoring-the-scanner-evaluation.md)) gave 51.1% over all findings and 53.2% with `--skip-comments`. Recall on known sites was 94.6%. The 145 findings labelled "not a dependency" showed four patterns:

1. Whole-line comments in files the scanner does not parse: `//` in Go and Swift, `#` in YAML and in `.env.example` (`# ANTHROPIC_MODELS=...`). These were `text` or `config`, not `comment`.
2. IDs inside sentences: help text, log messages, training data (`"Model to use (default: gemini-2.0-flash-exp)"`).
3. Price and token-limit tables: `"gpt-4o": (2.50, 10.00)`, `'claude-3-5-sonnet': 200000`.
4. Test files: 76 of the 145, mostly mocks and asserts. But 38 of the 105 real dependencies were in test folders too, mostly saved Langflow flows under `tests/data/` that offer model menus.

Ten of the 12 missed sites were in file types the scanner did not read: HTML pages, Elixir config (`.ex`, `.exs`) and `env.example`.

## Decision

- **Three line rules,** applied after the parser, only to findings that are not already a comment or docstring:
  - a line that starts with the file's comment marker is a `comment`, for files without a parser (marker per suffix; JSON and notebooks have none);
  - a string key followed by a number, a tuple of numbers or an object whose first value is a number is a `table`;
  - an ID inside a one-line string that contains a space is `prose`, unless the ID sits in escaped quotes (`\"gpt-4o\"`), which means the string holds code, as notebooks and saved flows do.
- **`--skip-comments` leaves out `comment`, `docstring`, `prose` and `table`:** everything that describes a model instead of using it. The flag keeps its name, so existing workflows keep working.
- **`--skip-tests`** (and the action input `skip-tests`) leaves out test files and test folders. It is off by default, because test folders also hold real model settings.
- **New file types:** `.html`, `.htm`, `.ex`, `.exs`, and `env.example`-style names. Emacs files and files over 1 MB stay out.

## Alternatives considered

- **Skip tests by default:** the largest gain on our labels, but it drops about a third of the real dependencies, and a migration that misses a test fixture breaks CI.
- **Rules for model catalogs** (`create_model_metadata(name="o3", not_supported=True)`) **and string checks** (`model.includes("gpt-4o")`): they look exactly like real use, and the sample has real dependencies of both shapes.
- **A parser per language** (Go, PHP, ...): more exact, but the comment-line rule covers what the labels showed at a fraction of the cost.

## Consequences

- On the labelled sheet the three rules catch 22 false findings and no real one. Measured on the same labels with `--skip-comments`, precision rises from 53.2% to about 60%. The exact number comes from re-scoring the snapshots with this version, not from the sheet lines alone.
- The rules read one line, so a sentence split over several lines, or an ID in a multi-line prompt, keeps its old context.
- The research evaluation (`research.scanner_eval.build`) groups contexts it knows; the new contexts are scored by a separate re-scoring step, so the labels stay valid.
