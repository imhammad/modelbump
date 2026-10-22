# Architecture Decision Records

An ADR records one significant decision: the context, what we decided, the alternatives, and the consequences. ADRs are never edited after acceptance; a new ADR supersedes an old one instead.

Format: [Michael Nygard's ADR template](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions).

| # | Decision | Status |
|---|----------|--------|
| [0001](0001-python-uv-src-layout.md) | Python 3.12+, uv, src layout | Accepted |
| [0002](0002-apache-2-license.md) | Apache License 2.0 | Accepted |
| [0003](0003-git-workflow.md) | Branches, PRs, squash merges, Conventional Commits | Accepted |
| [0004](0004-docs-with-material-for-mkdocs.md) | Docs with Material for MkDocs, with a path to Zensical | Accepted |
| [0005](0005-releases-with-release-please.md) | Versioning and releases with release-please | Accepted |
| [0006](0006-retirement-registry-format.md) | Retirement registry as YAML + pydantic schema | Accepted |
| [0007](0007-rescheduled-retirements.md) | Keep rescheduled retirements as superseded plans | Accepted |
| [0008](0008-research-code-separate-from-product.md) | Research code lives in `research/`, separate from the product | Accepted |
| [0009](0009-mining-method.md) | Mine with one search per model ID and split windows at the cap | Accepted, amended by 0010 |
| [0010](0010-hybrid-search-for-huge-ids.md) | Search hugely popular model IDs together with migration words | Superseded by 0011 |
| [0011](0011-search-huge-ids-from-the-notice.md) | Search hugely popular model IDs only from shortly before the deprecation notice | Accepted |
| [0012](0012-migration-filter-as-flags.md) | Label migration commits with one flag per rule, and keep AI-assisted commits separate | Accepted |
| [0013](0013-validation-sample.md) | Check the migration filter on a blind, stratified sample of 300 commits | Accepted |
| [0014](0014-filter-rules-v2.md) | Filter rules v2, a `migration_away` label, and a fresh sample to measure them | Accepted |
| [0015](0015-fresh-sample-for-rules-v2.md) | Measure rules v2 on a fresh, blind sample of 200 commits | Accepted |
| [0016](0016-migration-timing.md) | Place each migration on its model's retirement timeline | Accepted |
| [0017](0017-lag-and-migration-targets.md) | Measure how late projects migrate, and what they migrate to | Accepted |
| [0018](0018-changed-files-sample.md) | Check what migration commits change on a random sample of 400 | Accepted |
| [0019](0019-paper-numbers-from-one-script.md) | Build every number, table and figure in the paper with one script | Accepted |
| [0020](0020-dataset-release-package.md) | Publish the dataset on Zenodo as one versioned zip, without commit messages | Accepted |
| [0021](0021-robustness-checks.md) | Test the timing results against the objections a reviewer would raise | Accepted |
| [0022](0022-paper-in-latex.md) | Write Paper 1 in LaTeX in this repository, with the Springer Nature template | Accepted |
| [0023](0023-scanner-finds-ids-as-text-first.md) | The scanner finds model IDs as text first, and parses code later | Accepted |
| [0024](0024-severity-levels-and-ci-exit-code.md) | Severity levels, cloud forms of model IDs, and a CI exit code | Accepted |
| [0025](0025-json-and-sarif-reports.md) | JSON and SARIF reports, with UNKNOWN IDs left out of SARIF | Accepted |
| [0026](0026-github-action.md) | A composite GitHub Action in this repository | Accepted |
| [0027](0027-python-context-with-tree-sitter.md) | Give Python findings their context with tree-sitter | Accepted |
| [0028](0028-typescript-and-javascript-context.md) | TypeScript and JavaScript context, and option objects as call arguments | Accepted |
| [0029](0029-scanner-evaluation-set.md) | Evaluate the scanner on snapshots taken just before real migrations | Accepted |
