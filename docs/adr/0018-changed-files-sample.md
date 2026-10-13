# ADR 0018: Check what migration commits change on a random sample of 400

- **Status:** Accepted
- **Date:** 2026-10-13

## Context

RQ4 of Paper 1 asks whether projects test a model switch: does a migration commit come with tests or an evaluation, or is it a one-line ID swap? Kim (2026) reports that only a small share of migrations add an evaluation suite. The exact figure and its definition must be checked against Kim's paper before we compare.

Commit messages cannot answer this. The changed files can, but only GitHub's REST API has them, at one request per commit. Fetching all 40,876 commits would take more than 8 hours of requests at GitHub's limit of 5,000 an hour, and most of the answer comes from far fewer.

## Decision

- **Sample.** A simple random sample of **400** `migration_away` commits from `targets.jsonl`, seed **2028**. With 400 commits, a share near 10% has a 95% interval of about ±3 points, which is enough to compare with Kim and between groups.
- **Fetch.** `GET /repos/{repo}/commits/{sha}`, up to 300 changed files per commit, one request a second, with the miner's rate-limit and retry rules. Every response is cached under `research/data/cache/commit_files/`, including commits GitHub no longer serves (404, 409, 422 and so on), which are counted and reported, not replaced.
- **File kinds**, judged from the path, first match wins: `eval` (evals/, benchmarks, golden files, promptfoo), `test` (tests/, `test_*.py`, `*.test.ts`, `*_spec.rb` ...), `prompt` (prompts/, `*.prompt`), `ci`, `docs`, `config`, `code`, `other`.
- **Measures**, each with a 95% Wilson interval: touches or adds a test file; changes a test that names a model; touches or adds an evaluation file; touches a test or evaluation file; touches a prompt file; and **pure ID swap**: every changed line outside docs names a model ID. When GitHub leaves out a diff (binary or very large files), the ID swap is unknown and the commit is left out of that measure only.
- **Hand check.** 100 of the fetched commits (seed 2029) go into a blind sheet that lists each commit's files but not the code's answer. A person answers `has_test` and `has_eval` for each, and `--score` reports agreement and Cohen's kappa against the code.
- **By AI assistance.** The test measures are also split by `ai_assisted` from [ADR 0017](0017-lag-and-migration-targets.md), since half the migrations are AI-assisted.

## Alternatives considered

- **All 40,876 commits:** a day of requests for little more precision. A larger sample can be drawn later with the same code if a reviewer asks.
- **Clone each repository and look at its test suite:** says whether the project has tests, not whether the migration touched them, and costs far more.
- **Classify files with an LLM:** less transparent than path rules plus a measured hand check.

## Consequences

- RQ4 describes migration commits, not whole migrations. A project may add tests in a later commit. The paper says so.
- About 16% of `migration_away` commits are not real migrations ([ADR 0015](0015-fresh-sample-for-rules-v2.md)). The hand check lets those be spotted, and the `note` column records them.
- Path rules miss tests kept in unusual places. The hand check measures how many.

## Revision, 13 October 2026

The hand check of 100 commits (seed 2029) was scored against the rules as they were when the sheet was drawn:

| Question | Agreement | Kappa | Hand "yes" | Code found | Code "yes", hand "no" |
|----------|-----------|-------|------------|------------|-----------------------|
| `has_test` | 98 of 100 (93.0 to 99.4) | 0.93 | 19 | 17 | 0 |
| `has_eval` | 96 of 100 (90.2 to 98.4) | 0.32 | 5 | 1 | 0 |

The code never said "yes" where the hand said "no". The kappa for `has_eval` is low because evaluations are rare: with 5 "yes" answers in 100, each miss costs a lot of kappa. The five disagreeing commits were:

- **A PHPUnit test in `Tests/Unit/...Test.php`, missed.** Test folders were matched only in lower case, and PHP test files were not listed. Fixed: test folder names now match in any case, and `*Test.php` is a test.
- **`study/lib/llm_judge.py`, an LLM-as-judge evaluation, missed.** Fixed: `judge` and `judges` now mark an evaluation file, like `eval`.
- **Two commits in repositories that are themselves benchmarks** (`verify.py` in a Lean proof benchmark, `baselines/registry.py` in a citation benchmark). No path rule can tell that a whole repository is an evaluation, so these stay missed.
- **Configuration and result files under `test-corpus/`** in an embedding search project. The hand said both test and evaluation. One case, so the rules were not changed for it.

These fixes were made after seeing the labels, so this sample no longer tests them blind. The paper reports the scores above, from before the change, as the validation, and the rescore with `--score --current` only as a check that the fixes work. For evaluations, the code's rate is a lower bound, and the paper reports the hand rate on the 100 commits (5 of 100, 2.2 to 11.2) next to it.
