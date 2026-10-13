# Changed files: do migrations come with tests?

**Code:** `research/enrichment/files.py`, `research/validation/files_check.py` · **Decision:** [ADR 0018](../adr/0018-changed-files-sample.md) · **Input:** `research/data/targets.jsonl` from [targets](targets.md)

This step answers the paper's RQ4. It takes a random sample of 400 migration commits and asks GitHub which files each one changed. Do they touch tests or evaluations, or only swap a model ID?

## Running it

```
export GITHUB_TOKEN=$(gh auth token)
uv run python -m research.enrichment.files
```

It makes about 400 requests, one a second, so it takes about 7 minutes. Every response is cached under `research/data/cache/commit_files/`, so running it again costs nothing. If it stops, run the same command again.

It writes:

| File | Contents |
|------|----------|
| `research/data/files.jsonl` | One row per sampled commit: its files (path, status, kind, lines added and removed) and the flags below |
| `research/data/files.stats.json` | Every number printed, for the paper |

Options: `--sample` (default 400), `--seed` (default 2028), `--interval` (seconds between requests, default 1).

## File kinds

| Kind | Examples |
|------|----------|
| `eval` | `evals/`, `benchmarks/`, `golden.jsonl`, `promptfooconfig.yaml`, `llm_eval.py` |
| `test` | `tests/`, `test_x.py`, `x_test.go`, `x.test.ts`, `x.spec.js`, `x_spec.rb`, `conftest.py` |
| `prompt` | `prompts/`, `x.prompt`, `system_prompt.txt` |
| `ci` | `.github/workflows/`, `.gitlab-ci.yml` |
| `docs` | `*.md`, `docs/`, `README`, `CHANGELOG` |
| `config` | `.env*`, `*.yaml`, `*.json`, `*.toml`, `Dockerfile`, `requirements.txt` |
| `code` | source files (`.py`, `.ts`, `.go`, ...) |
| `other` | anything else (images, binaries) |

The first matching kind wins, so `tests/evals/x.py` is an `eval`.

## What it prints

- How many commits were fetched, and how many GitHub no longer serves, by HTTP status.
- How many commits touch each kind of file.
- RQ4, with 95% Wilson intervals:
  - **touches / adds a test file**;
  - **changes a test that names a model**, meaning the test itself mentions a model ID;
  - **touches / adds an evaluation file**;
  - **touches a test or evaluation file**;
  - **touches a prompt file**;
  - **pure ID swap**: every changed line outside docs names a model ID. Commits with a missing diff are left out of this one.
- The test measures split by AI assistance.

## Checking it by hand

```
uv run python -m research.validation.files_check
```

This draws 100 of the fetched commits (seed 2029) into `research/data/validation_files/sample.csv`. Each row has the commit URL and its changed files, written as `A` (added), `M` (modified), `D` (deleted) or `R` (renamed) followed by the path. The code's answers go to `sample_key.csv`. Don't open that file until you have finished.

For each row, fill in:

| Column | Answer |
|--------|--------|
| `has_test` | `yes` if the commit adds or changes an automated test (unit, integration or end-to-end), otherwise `no` |
| `has_eval` | `yes` if the commit adds or changes an evaluation of model output: a set of test prompts with expected answers, a benchmark, golden outputs, or an eval config such as promptfoo. Otherwise `no` |
| `note` | Anything odd, for example "not a migration" or "tests are in a file called check.py" |

Judge from the file names first. Open the URL only when a name is unclear, for example `check.py`. Then score it:

```
uv run python -m research.validation.files_check --score
```

It prints, for each question, the agreement with a 95% interval, Cohen's kappa, and how many of your "yes" answers the code found.
