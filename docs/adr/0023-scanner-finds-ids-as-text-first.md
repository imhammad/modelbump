# ADR 0023: The scanner finds model IDs as text first, and parses code later

- **Status:** Accepted
- **Date:** 2026-10-19

## Context

Phase 2 builds the scanner: it reads a repository and lists the LLM model IDs the code depends on, so ModelBump can warn before a provider shuts one down. Model IDs live in many places: SDK calls in Python and TypeScript, constants, YAML, TOML and JSON config, and `.env` files. Kim (2026) found model IDs hard-coded in 94% of migrating apps.

The master plan's first scanner step is a tree-sitter parser for Python. A parser knows *where* an ID is used (which SDK, which argument), but it only sees the languages it has a grammar for, and it misses every config file.

Paper 1 is still being written, and its numbers come from `research/` and from the registry (`research/` imports `modelbump.registry`).

## Decision

- **Stage 1 is a language-free text finder** (`modelbump.scanner.ids`). It splits each line into runs of letters, digits, `.`, `-` and `_`, and keeps a run that is either an exact registry ID or shaped like a model ID from a provider we track: lowercase `gpt-`, `chatgpt-`, `claude-`, `gemini-` or `text-embedding-` with at least one digit, or `o1`/`o3`/`o4` names.
  - The digit rule keeps out package and tool names (`gpt-tokenizer`, `claude-code`).
  - Matching is case-sensitive, so prose such as "GPT-4" is not a finding.
  - Registry IDs that are plain words (`ada`, `davinci`, `curie`, `babbage`) count only as a whole quoted string.
  - Wrapped forms give the inner ID: `anthropic.claude-...` (Bedrock), `openai/gpt-4o` (LiteLLM), `models/gemini-...` (Google).
- **Which files:** code and config by file suffix, plus `.env` and `.env.*`. Docs (`.md`, `.rst`, `.txt`) and lock files are left out, because a mention in a README or a package name in a lock file is not a dependency. Tool and build folders (`.git`, `node_modules`, `.venv`, ...) are skipped, symbolic links are not followed, and files over 1 MB or with a NUL byte are skipped and counted.
- **The scanner reports, it does not judge yet.** Each finding has a path, line, column, the ID and whether the registry lists it. Severity (RETIRED, RETIRING_SOON, ...) and the normalisation of provider forms such as `-v1:0` and `@20240620` come in later steps.
- **Parsers come next, on top.** Tree-sitter parsers for Python and TypeScript will add context (SDK, call, argument) to the text findings, and catch IDs built from parts.
- **The paper's code stays frozen.** Until Paper 1 is submitted, Phase 2 only adds new modules. It does not change `research/` or `modelbump.registry` (code or data), so the paper's numbers cannot move.

## Alternatives considered

- **Tree-sitter first:** gives call context from day one, but misses config files and every language without a grammar, so recall would be lower exactly where Kim found the IDs.
- **Exact registry IDs only:** very precise, but blind to models that are not retired yet. Those are the ones a user most needs to know about before the notice comes.
- **A regex per provider over whole files:** simpler, but harder to keep from matching inside longer names, and it cannot give exact columns as easily.
- **Asking an LLM to find the IDs:** costs money on every run, is not deterministic, and is hard to test in CI.

## Consequences

- One finder works for every language and config format, and gives exact line and column numbers (needed later for SARIF).
- Some findings will not be dependencies, for example an ID in a code comment or in test data. The labelled evaluation set (Phase 2) measures precision and recall, and the parsers can later lower the noise.
- IDs written without a digit (`claude-sonnet-latest`) or assembled from parts (`f"gpt-{version}"`) are missed until the parsers land.
- Registry updates wait until the paper is submitted.
