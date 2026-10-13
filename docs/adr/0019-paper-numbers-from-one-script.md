# ADR 0019: Build every number, table and figure in the paper with one script

- **Status:** Accepted
- **Date:** 2026-10-13

## Context

Paper 1 cites about 250 numbers from ten data files made by six earlier steps. Typing them into the paper by hand invites copying mistakes, and they go stale whenever a step is run again (as Steps 19b and 20c showed). Reviewers at empirical venues also expect every number to be traceable to code and data.

## Decision

- **One command,** `uv run python -m research.analysis.paper`, reads the outputs of the earlier steps in `research/data/` and writes to `paper/generated/`:
  - `numbers.tex`: one LaTeX command per number, for example `\MigrationsAway` for 40,876, `\Precision` with `\PrecisionLow` and `\PrecisionHigh` for its 95% interval. Percentages are written without the `%` sign, so the paper writes `\Precision\%`.
  - `numbers.json`: the same numbers, unrounded.
  - `tables/*.tex`: the body of each table, as a booktabs `tabular`. The paper adds the caption and label.
  - `figures/*.pdf`: the figures, with embedded TrueType fonts and no creation date, so the same data gives the same file.
- **Nothing is recomputed differently.** The script uses the earlier steps' own functions (validation scoring, the file-kind check) and their stats files, so a number in the paper is the number the step printed.
- **Kim's numbers** are constants in the script, each with the section of Kim's paper it comes from: 82% after the shutdown (abstract), 16% of migrations touch a test file (Section 4.4, 3,931 migrations), 4.5% of messages mention an evaluation suite (Section 4.5).
- **Recorded numbers.** The one number the current code cannot rebuild, the target check before the rules were tuned (70 of 97), is kept in `RECORDED` with its source ([ADR 0017](0017-lag-and-migration-targets.md)).
- **Committed output.** `paper/generated/` holds only aggregate numbers, no commit data, so it is committed. The paper's own build (Step 23) can then run in CI without the data.
- **Figures** use the first three slots of a validated colour-blind-safe categorical palette, in a fixed order per provider (OpenAI blue, Anthropic orange, Google green), so a provider keeps its colour in every figure.

## Alternatives considered

- **Copy numbers by hand into the paper:** the usual way, and the usual source of errors.
- **A Jupyter notebook:** harder to test and review, and its output depends on the order cells are run.
- **Generate the whole paper from a template:** too rigid for the writing.

## Consequences

- After any step is run again, one command updates every number, table and figure.
- The script fails with a list of the missing files, and the command that makes each, when an input is missing.
- matplotlib becomes a research dependency.
