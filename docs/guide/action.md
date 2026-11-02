# GitHub Action

The ModelBump Action does two jobs:

- **warn:** fail CI before a model shuts down;
- **bump:** open one pull request per due model on a schedule, like Dependabot.

Pin it to the major version, `imhammad/modelbump@v1`. That tag moves to each 1.x release, so you get fixes and new registry dates without breaking changes. Pin a full tag such as `@v1.0.0` to freeze it.

## Warn in CI

```yaml
name: ModelBump scan
on:
  pull_request:
  schedule:
    - cron: "0 6 * * 1"   # Mondays, to catch new retirement notices

permissions:
  contents: read
  security-events: write  # upload findings to code scanning

jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: imhammad/modelbump@v1
        with:
          fail-within: "30"
          skip-comments: "true"
```

The job fails when a model is retired or shuts down within 30 days. The findings appear in the Security tab, on pull request lines, and in the job summary.

## Open bump pull requests on a schedule

```yaml
name: ModelBump bump
on:
  schedule:
    - cron: "0 6 * * 1"
  workflow_dispatch:

permissions:
  contents: write        # push the bump branch
  pull-requests: write   # open the pull request

jobs:
  bump:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: imhammad/modelbump@v1
        with:
          open-prs: "true"
          upload-sarif: "false"
```

Each due model gets the branch `modelbump/OLD-to-NEW` and one pull request. While that branch exists, later runs skip the model, so there are never duplicates. A model is due when the code uses it, it shuts down within `within` days, and the registry suggests a replacement that is not retired.

Two settings matter:

- The repository must allow Actions to open pull requests: Settings, Actions, General, Workflow permissions, "Allow GitHub Actions to create and approve pull requests".
- Pull requests opened with the default token do not start other workflows, so CI does not run on them. Pass a fine-grained token with contents and pull-requests write as `github-token` if you want CI to run.

Scheduled pull requests carry no test results, because running models in CI is not free. Run `modelbump test` yourself, then [bump with the evidence](tutorial.md#5-bump-the-model).

## Inputs

| Input | Default | Meaning |
|-------|---------|---------|
| `path` | `.` | Folder to scan, relative to the repository root |
| `fail-within` | empty | Fail the job if a model is retired or shuts down within this many days; empty never fails |
| `soon-days` | `90` | Warning window for `RETIRING_SOON` |
| `exclude` | empty | Paths to skip, one pattern per line |
| `skip-comments` | `false` | Leave out IDs that only describe a model (comments, docstrings, sentences, price tables) |
| `skip-tests` | `false` | Leave out test files and test folders |
| `upload-sarif` | `true` | Upload findings to code scanning (needs `security-events: write`; private repositories also need GitHub Advanced Security) |
| `open-prs` | `false` | `true` opens one bump pull request per due model; `dry-run` only lists them |
| `within` | `90` | With `open-prs`: bump models that shut down within this many days |
| `github-token` | `github.token` | Token used to open the pull requests |

## Outputs

| Output | Meaning |
|--------|---------|
| `sarif-file` | Path of the SARIF report |
| `bump-report` | With `open-prs`: path of the text report of the bumps |
