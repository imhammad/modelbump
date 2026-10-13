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
