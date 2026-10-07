# ADR 0004: Docs with Material for MkDocs, with a path to Zensical

- **Status:** Accepted
- **Date:** 2026-10-07

## Context

We need a documentation site that is written in Markdown next to the code, versioned in git, deployed automatically, and good-looking enough for a public portfolio.

As of October 2026, **Material for MkDocs** (9.7.x) is in maintenance mode: it receives critical bug and security fixes, while new feature work has moved to **Zensical**, a successor from the same team. Zensical reads existing `mkdocs.yml` configurations, but it is still in alpha (0.0.x, "Development Status: 3 - Alpha" on PyPI).

## Decision

Use **Material for MkDocs** now, deployed to GitHub Pages by GitHub Actions. Re-evaluate Zensical when it reaches a stable release; because it reads `mkdocs.yml`, migrating should be low-cost.

## Alternatives considered

- **Zensical now:** the future direction, but alpha software is a risk for a site we rely on every day.
- **Sphinx:** powerful for API docs, but reStructuredText-first and heavier to configure.
- **GitHub wiki:** not versioned with the code and not reviewable in PRs.

## Consequences

- Stable tooling today, with a known migration path.
- **MkDocs is pinned to `<2`.** The Material team warns that MkDocs 2.0 removes the plugin system and rewrites theming, so Material will not work on it ([their analysis](https://squidfunk.github.io/mkdocs-material/blog/2026/02/18/mkdocs-2.0/)). Without the pin, a routine dependency update could silently break the docs build.
- We must watch Zensical's releases; tracked as a future decision.
