# ADR 0025: JSON and SARIF reports, with UNKNOWN IDs left out of SARIF

- **Status:** Accepted
- **Date:** 2026-10-22

## Context

`modelbump scan` prints one line per finding ([ADR 0024](0024-severity-levels-and-ci-exit-code.md)). That suits a person at a terminal, but two other readers need the same findings:

- **Scripts**, including our replay experiment for the tool paper, which will scan thousands of old commits and needs every field without parsing text.
- **GitHub code scanning**, which shows findings as alerts in a repository's Security tab and on pull request lines. It reads SARIF 2.1.0, the OASIS standard for static analysis results.

## Decision

- **`--format text|json|sarif`**, with text as the default, and **`--output FILE`** to write the report to a file. With `--output`, the screen still shows where the report went and the summary line.
- **One report object, three renderers** (`modelbump.scanner.report`). Each finding is assessed once, then rendered, so the formats cannot disagree.
- **JSON** holds the check day, the window, the threshold, whether the scan failed, counts per severity, and every finding with all of its fields (`days_left`, `shutdown`, `replacement`, ...). Dates are ISO strings; a missing value is `null`.
- **SARIF** has one rule per severity: `modelbump/retired` (level `error`), `modelbump/retiring-soon` (`warning`) and `modelbump/deprecated` (`note`). Each result points at the exact line and columns of the ID, with a path relative to the scan root (`%SRCROOT%`).
- **UNKNOWN findings are left out of SARIF.** An ID with no announced retirement is not a problem, and GitHub would show each one as an alert, so real warnings would drown. They stay in the text and JSON reports.
- **The exit code is the same in every format.** When the screen holds JSON or SARIF, the failure message goes to stderr, so the screen output stays a valid document.
- **No fingerprints of our own.** GitHub's upload action (`github/codeql-action/upload-sarif`) computes `partialFingerprints` to track an alert across commits.

## Alternatives considered

- **Report UNKNOWN as SARIF `note`s:** complete, but a typical app has many such IDs, and every one would become an alert to dismiss.
- **One SARIF rule per model ID:** finer filtering in GitHub, but the rule list would grow with the registry, and the urgency is what users act on.
- **A JSON schema file and validation in the tests:** stronger, but it adds a dependency. The SARIF output was checked once against the official 2.1.0 schema from SchemaStore, and the tests check its structure.

## Consequences

- The GitHub Action (a later step) only has to run `modelbump scan --format sarif --output modelbump.sarif` and upload the file.
- The replay experiment can read `--format json` directly.
- Scan the repository root before uploading SARIF; otherwise the paths will not match the repository's files.
