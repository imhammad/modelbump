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
| [0030](0030-scoring-the-scanner-evaluation.md) | Score the scanner's precision by group, weighted by group size | Accepted |
| [0031](0031-describing-contexts-and-test-files.md) | Mark IDs that only describe a model, and let users skip test files | Accepted |
| [0032](0032-rescoring-after-a-scanner-change.md) | Re-score the same labels after a scanner change | Accepted |
| [0033](0033-replaying-the-scanner.md) | Replay the scanner on the snapshots before each migration | Accepted |
| [0034](0034-replay-warning-sources.md) | Say why each flagged project was warned, and re-check labels the sheet cut off | Accepted |
| [0035](0035-publishing-releases-to-pypi.md) | Publish each release to PyPI from the release workflow, with trusted publishing | Accepted |
| [0036](0036-runner-speaks-openai-compatible-http.md) | The runner calls OpenAI-compatible endpoints with httpx, not LiteLLM, and uses only free models | Accepted |
| [0037](0037-response-cache-in-sqlite.md) | Cache model answers in one SQLite file, keyed by a hash of the whole request | Accepted |
| [0038](0038-budget-in-tokens-and-requests.md) | Limit spending in tokens and requests, not dollars, and count cached answers as savings | Accepted |
| [0039](0039-pin-local-models-to-their-digest.md) | Pin local models to their Ollama digest, and let callers turn thinking off | Accepted |
| [0040](0040-free-cloud-tiers-with-pacing.md) | Add three free cloud tiers, paced under their per-minute limits, and warn before prompts leave the machine | Accepted |
| [0041](0041-item-verdict-from-pass-counts.md) | Decide each test case from pass counts with a continuity-corrected Newcombe interval and an equivalence margin | Accepted |
| [0042](0042-sequential-stopping-by-betting.md) | Stop asking as soon as the verdict is clear, with test-by-betting wealths that are safe to check after every answer | Accepted |
| [0043](0043-suite-control-with-e-bh.md) | Control the false discovery rate across a suite with e-BH on the betting wealths | Accepted |
| [0044](0044-simulation-study-of-the-stats-engine.md) | Check the stats engine with a seeded simulation study and property tests, against a single-run diff and fixed-k baselines | Accepted |
| [0045](0045-scores-and-stopping-cases-that-look-fine.md) | Accept scores between 0 and 1, and optionally stop test cases that look fine | Accepted |
| [0046](0046-real-model-experiment.md) | Test the stats engine on real local models with computed answers, a null pair and injected regressions | Accepted |
| [0047](0047-real-model-results.md) | Pick fixed k + BH or sequential + e-BH by budget, and report regressions per test case | Accepted |
| [0048](0048-find-llm-calls-and-prompt-templates.md) | Find each LLM call and its prompt template with Python's own parser, inside one file | Accepted |
| [0049](0049-follow-prompts-across-files-classes-and-functions.md) | Follow prompts into other files, class attributes and the app's own prompt functions | Accepted |
| [0050](0050-test-inputs-from-the-apps-own-callers.md) | Take the first test inputs from the values the app's own tests and code pass in | Accepted |
| [0051](0051-generated-test-inputs-from-a-local-model.md) | Have a local model write the missing test inputs, and mark every one as generated | Accepted |
| [0052](0052-oracles-by-output-type.md) | Check answers against the old model's answers, with an oracle picked by output type | Accepted |
| [0053](0053-suite-file-and-modelbump-test.md) | Write the suite to a file, then run it on both models with `modelbump test` | Accepted |
| [0054](0054-llm-judge-for-free-text.md) | Judge free-text answers with a third local model, against an old reference answer | Accepted |
| [0055](0055-check-the-judge-against-hand-labels.md) | Check the judge against blind hand labels drawn by verdict, and correct pass rates for it | Accepted |
| [0056](0056-bigger-judge-and-no-invented-facts.md) | Use Gemma 3 12B as the judge, fail invented facts, and test the change on fresh labels | Accepted |
