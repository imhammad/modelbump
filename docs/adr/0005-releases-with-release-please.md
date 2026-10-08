# ADR 0005: Versioning and releases with release-please

- **Status:** Accepted
- **Date:** 2026-10-07

## Context

We want every release to have a correct semantic version, a changelog, and a git tag, without hand-editing version numbers. Our commits already follow Conventional Commits (ADR 0003), which carry exactly the information needed.

## Decision

Use [release-please](https://github.com/googleapis/release-please-action) (v5):

- On every push to `main`, it opens or updates a **release PR** that bumps the version and updates `CHANGELOG.md` from the commit messages.
- Merging that PR creates the git tag (`vX.Y.Z`) and the GitHub Release.
- `feat:` bumps the minor version, `fix:` the patch version (while we are below 1.0, breaking changes also bump minor). `docs:`, `research:`, `perf:` appear in the changelog; `ci:`, `chore:`, `test:`, `refactor:` are hidden.
- The version lives in `pyproject.toml` (and is mirrored into `uv.lock`); the code reads it at runtime with `importlib.metadata`, so there is one source of truth.
- We merge the release PR only at meaningful milestones, so releases mark real progress.

## Alternatives considered

- **Manual tags and changelog:** error-prone and easy to forget.
- **semantic-release:** releases on every merge with no review step; less control over timing.
- **Commitizen (`cz bump`):** good, but runs locally, so releases depend on someone's laptop.

## Consequences

- Release PRs need a fine-grained personal access token (`RELEASE_PLEASE_TOKEN`), because PRs created with the default `GITHUB_TOKEN` do not trigger CI. See [challenge 001](../engineering-challenges/001-release-pr-ci-never-runs.md). The token expires and must be rotated.
- `uv.lock` must be bumped together with `pyproject.toml`, or CI's `uv sync --locked` fails. Handled with an `extra-files` rule.
