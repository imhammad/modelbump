# ADR 0003: Branches, PRs, squash merges and Conventional Commits

- **Status:** Accepted
- **Date:** 2026-10-07

## Context

We want a clean, readable history, automated changelogs later, and protection against broken code reaching `main`, even with a single developer.

## Decision

- `main` is protected by a ruleset: changes only via pull request, all 5 CI checks must pass, linear history, no force pushes or deletion.
- Work happens on short-lived branches named `type/short-description` (e.g. `feat/scanner-python`).
- PRs are **squash-merged**, so each PR becomes one commit on `main`; merged branches are deleted automatically.
- Commit and PR titles follow [Conventional Commits](https://www.conventionalcommits.org) (`feat:`, `fix:`, `docs:`, `ci:`, `chore:`, `test:`, `refactor:`, `research:`).
- pre-commit runs the same checks locally before every commit.

## Alternatives considered

- **Committing directly to `main`:** fast, but no review step and no CI gate.
- **Merge commits:** keep every intermediate commit, making history noisy.
- **Rebase merging:** linear, but keeps every work-in-progress commit.

## Consequences

- `main` is always green and every commit on it corresponds to one reviewed change.
- Squash merges mean local branches must be deleted with `git branch -D` after merging.
