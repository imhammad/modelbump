# ADR 0008: Research code lives in `research/`, separate from the product

- **Status:** Accepted
- **Date:** 2026-10-08

## Context

The paper needs code that the product does not: dataset miners, experiment scripts and analysis notebooks. This code has different users (us, and reviewers who want to reproduce the paper), different dependencies, and a different life span.

## Decision

- Research code lives in a top-level `research/` folder, not in `src/modelbump/`.
- `research/` may import from `modelbump` (for example, the miner reads the registry). The product never imports from `research/`.
- Research-only libraries go in a `research` dependency group in `pyproject.toml`, so they are never installed for users of the package. `[tool.uv] default-groups` makes `uv sync` install them for us and for CI.
- Research code meets the same bar as product code: ruff, mypy `--strict` and tests in CI. Its tests live in `tests/research/`.
- Mined data goes in `research/data/`, which git ignores. Datasets are published separately, with a dataset card.

## Alternatives considered

- **A separate repository:** cleaner, but the miner depends on the registry, and two repos would drift apart.
- **Notebooks only:** fast to write, but hard to test and review, and they hide the code that produced each number.

## Consequences

- The wheel stays small and has no research dependencies.
- Reviewers can rerun every research step from this one repo.
