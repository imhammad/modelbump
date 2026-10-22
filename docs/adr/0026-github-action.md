# ADR 0026: A composite GitHub Action in this repository

- **Status:** Accepted
- **Date:** 2026-10-22

## Context

The scanner is most useful where code changes: in CI, on every pull request and on a schedule. GitHub Actions is where most open-source LLM apps run CI, and GitHub code scanning shows SARIF findings ([ADR 0025](0025-json-and-sarif-reports.md)) in the Security tab and on pull request lines.

ModelBump is not on PyPI yet (that comes with v0.1.0), and an action that installs a different version from the one it was tagged with would be confusing to debug.

## Decision

- **A composite action, `action.yml` at the repository root,** so users write `uses: imhammad/modelbump@<tag>` and the GitHub Marketplace can list it.
- **It installs ModelBump from its own copy of this repository** (`uv tool run --from "$GITHUB_ACTION_PATH"`), so the action at a tag always runs the scanner at that same tag. `astral-sh/setup-uv` provides uv and Python 3.12.
- **Three steps:** write the SARIF report, upload it to code scanning (`github/codeql-action/upload-sarif@v4`, category `modelbump`, can be turned off with `upload-sarif: false`), then run the text scan with the threshold. The failing check comes last, so the findings are uploaded even when the job fails. The text report also goes to the job summary.
- **Inputs:** `path`, `fail-within` (empty means never fail, as in the CLI), `soon-days`, `exclude` (one pattern per line, passed as repeated `--exclude`) and `upload-sarif`. Output: `sarif-file`.
- **Inputs reach the script as environment variables,** never pasted into the shell command, so a crafted input cannot run commands (GitHub's script-injection guidance).
- **The scanner gets `--exclude`.** Repositories hold test data, fixtures and vendored code that mention models; users need a way to leave them out.
- **SARIF paths are relative to the working directory,** not to the scanned folder, so `path: services/api` still gives paths GitHub can match to files.
- **A workflow tests the action** (`.github/workflows/action-test.yml`) with `uses: ./` on a demo app in `tests/fixtures/action-demo/`: one job checks the SARIF report, and one checks that a retired model fails the step.

## Alternatives considered

- **A Docker action:** fully pinned, but slower to start, Linux-only, and one more image to build and publish.
- **A JavaScript action:** the usual choice for speed, but it would need a second implementation or a bundled Python, for a scanner written in Python.
- **Installing from PyPI:** the normal route once v0.1.0 is published, but the version could drift from the action's tag. The action can switch to PyPI later without changing its inputs.

## Consequences

- Any repository can add ModelBump to CI in a few lines, once a tag exists. Until v0.1.0, `@main` works for trying it.
- Uploading to code scanning needs `permissions: security-events: write`. On private repositories it also needs GitHub Advanced Security, and pull requests from forks cannot upload; `upload-sarif: false` covers those cases.
- The first run builds ModelBump from source, which takes a few seconds; uv's cache makes later runs faster.
