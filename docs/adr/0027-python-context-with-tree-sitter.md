# ADR 0027: Give Python findings their context with tree-sitter

- **Status:** Accepted
- **Date:** 2026-10-22

## Context

The text finder ([ADR 0023](0023-scanner-finds-ids-as-text-first.md)) finds model IDs anywhere in a file, including comments and docstrings, which describe the code rather than use a model. A finding is easier to act on when it says *what* uses the ID: `client.messages.create(model=)`, a constant `MODEL`, or the key `summary_model` in a config file. The replay experiment and the labelled evaluation set also need to tell real uses from mentions. On our own `research/` code, 41 of 53 findings are in comments or docstrings.

The master plan names tree-sitter for the scanner's parsers, and the TypeScript step will need it too.

## Decision

- **Keep the text finder as the only source of findings,** and add a context to each one. A parser never adds or drops an ID, so recall stays the same; only `--skip-comments` drops findings, and only when asked.
- **Python files (`.py`, `.pyi`) are parsed with tree-sitter** (`tree-sitter` and `tree-sitter-python`). For each finding, the scanner takes the smallest syntax node at its position and walks up to the string or comment that holds it. The context is:
  - `call_argument`: a keyword argument (`create(model=)`) or positional argument (`GenerativeModel(argument 1)`) of a call;
  - `assignment`: assigned to a name (`MODEL`, `self.model`) or the default of a parameter;
  - `string`: any other string, with the dict key when it is a dict value;
  - `docstring`: a string that is a statement on its own;
  - `comment`.
- **Config files** (JSON, YAML, TOML, INI, `.env`) get context `config`, and the key when the line looks like `key: value` or `KEY=value`. Other files keep context `text` until their parser lands.
- **Shown everywhere:** at the end of the text line (`[assigned to MODEL]`, `[in a comment]`), as `context` and `detail` in JSON, and in the SARIF message and `properties`.
- **`--skip-comments`** leaves out findings in comments and docstrings. It is off by default, because a comment can be the only sign of a model a project still depends on (`# TODO: move off gpt-3.5-turbo-0613`).

## Alternatives considered

- **Python's own `ast` module:** no new dependency and exact for valid Python 3, but it fails on a file with a syntax error or Python 2 code (common in old commits, which the replay will scan), it drops comments, and it cannot be reused for TypeScript.
- **Let the parser find the IDs:** would catch IDs built from parts (`f"gpt-{version}"`), but it gives up the single, language-free finder, and parsing errors could hide findings. Building IDs from parts stays future work.
- **Drop comments by default:** less noise, but silent misses are worse than visible noise for a tool whose job is warning.

## Consequences

- Two small, prebuilt dependencies (wheels for macOS, Linux and Windows on Python 3.12 and 3.13).
- Positions are converted from the finder's character columns to tree-sitter's byte offsets, so non-ASCII text before an ID is handled (tested).
- The same tree-sitter code will serve the TypeScript parser.
