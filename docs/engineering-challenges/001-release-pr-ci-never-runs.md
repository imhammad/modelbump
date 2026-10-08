# 001: Release PRs would never pass CI

- **Date:** 2026-10-07
- **Area:** CI / releases

## Symptom

Found while designing the release pipeline, before it shipped: release-please's own pull requests would sit forever with "Expected — Waiting for status to be reported" on all five required checks, so the protected `main` branch could never accept them.

## Investigation

1. Our `main` ruleset requires the five CI checks to pass before any merge.
2. release-please opens its release PR using whatever token it is given; by default that is the workflow's `GITHUB_TOKEN`.
3. GitHub deliberately does not start new workflow runs for events created with `GITHUB_TOKEN` (to prevent infinite loops of workflows triggering workflows). The release-please README states this directly and recommends a personal access token.
4. So the release PR would exist, but no CI run would ever start for it.

A second problem appeared while testing the version bump locally: changing only the `version` in `pyproject.toml` makes `uv sync --locked` fail with *"The lockfile at `uv.lock` needs to be updated"*, because `uv.lock` records the project's own version too.

## Root cause

1. Token semantics: `GITHUB_TOKEN`-created events don't trigger workflows.
2. Two files store the version (`pyproject.toml` and `uv.lock`), but release-please's Python strategy only knows about the first.

## Options considered

| Option | Trade-off |
|--------|-----------|
| Use `GITHUB_TOKEN` and merge release PRs with a bypass | Weakens branch protection; easy to forget why |
| Fine-grained personal access token scoped to this repo | Simple; must be rotated before it expires |
| A dedicated GitHub App token | Most robust for teams; more setup than a one-person repo needs |
| Regenerate `uv.lock` in a separate workflow step | Extra moving parts and another commit |
| release-please `extra-files` TOML rule for `uv.lock` | One config line; verified locally to produce a lockfile that passes `uv sync --locked` |

## Fix

- A fine-grained PAT (`RELEASE_PLEASE_TOKEN`), limited to this repository with only Contents, Pull requests and Issues read/write.
- An `extra-files` rule updating `$.package[?(@.name.value=='modelbump')].version` in `uv.lock`.

## Lesson

Branch protection and automation interact: any bot that opens PRs needs a token whose events trigger CI. And when a version number lives in more than one file, every copy must be bumped together, or one strict check will catch the mismatch.
