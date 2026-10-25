# ADR 0035: Publish each release to PyPI from the release workflow, with trusted publishing

- **Status:** Accepted
- **Date:** 2026-10-23

## Context

v0.1.0 is the first release meant for users: the scanner and the GitHub Action are done and evaluated ([scanner evaluation](../research/scanner-eval.md)). Until now a release only made a tag and a GitHub release ([ADR 0005](0005-releases-with-release-please.md)). People who want the command-line tool should be able to run `pip install modelbump` or `uvx modelbump`, and the version on PyPI must be the one that was tagged.

## Decision

- **Publishing is part of `release-please.yml`.** Two jobs run only when release-please reports `release_created`, that is, when the release PR is merged:
    - **build** checks out the new tag, checks that the `pyproject.toml` version equals the tag without its `v`, runs `uv build`, installs the wheel in a clean environment and scans the demo app (`tests/fixtures/action-demo/`), which must fail with `--fail-within 30` because it uses retired models. This proves the wheel carries the registry data, not just the code.
    - **publish** uploads that same `dist/` with `pypa/gh-action-pypi-publish`.
- **Trusted publishing, not an API token.** PyPI is told to trust this repository's `release-please.yml` running in the GitHub environment `pypi`. The job gets a short-lived token through OpenID Connect (`id-token: write`, only on that job), so no PyPI secret is stored anywhere. The project is created on PyPI by a "pending publisher" on the first upload.
- **The package description says what exists now** (find model IDs and warn before retirement), not the whole plan, and the README links use full URLs so they work on PyPI.
- **The Action keeps installing from its own tag** ([ADR 0026](0026-github-action.md)), not from PyPI, so the two cannot drift apart.
- **The GitHub Marketplace listing** is a one-time manual step on the v0.1.0 release; later releases keep it.

## Alternatives considered

- **A separate workflow triggered by `release: published`:** releases made with the release-please token do trigger it, but the version check and the tag would then live in two files. One workflow keeps the whole release in one place.
- **A PyPI API token in a repository secret:** works, but it is a long-lived secret that can leak and has to be rotated. PyPI recommends trusted publishing.
- **Publishing by hand with `uv publish`:** easy to forget, and the uploaded files would not be built from the tag by CI.
- **TestPyPI first:** useful for a first try, but the smoke test already installs the built wheel, and a second publisher doubles the setup. It can be added if an upload ever goes wrong.

## Consequences

- Merging the release PR is the only step to release: tag, GitHub release, changelog and PyPI upload all follow from it.
- A wrong version, a broken wheel or missing registry data stops the release before anything reaches PyPI. A PyPI version can never be uploaded twice, so a failed publish is fixed with a new patch release.
- If the workflow file or the environment is renamed, the trusted publisher on PyPI must be updated too.
