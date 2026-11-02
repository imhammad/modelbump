# Bump

`modelbump bump` moves a repository from one model to another. Phase 7 builds it in steps; this page grows with them.

## Changing the model ID

```bash
modelbump bump claude-3-haiku-20240307
```

```text
Using the replacement the registry suggests: claude-haiku-4-5-20251001.
--- a/app/llm.py
+++ b/app/llm.py
@@ -2,7 +2,7 @@
-MODEL = "claude-3-haiku-20240307"
+MODEL = "claude-haiku-4-5-20251001"
...
Would change 3 places in 2 files: claude-3-haiku-20240307 -> claude-haiku-4-5-20251001.
Left alone, check by hand (2):
  app/llm.py:6:12  claude-3-haiku-20240307  (price or limit table; add the new model's row by hand)
  app/llm.py:7:22  claude-3-haiku-20240307-v1  (cloud platform ID; look up the new model's ID there)
Nothing was written. Run again with --write to change the files.
```

- Without `--to NEW`, the registry's suggested replacement is used. A retired target is refused; a deprecated one gets a warning.
- Nothing changes until `--write`.
- Only the places the [scanner](scanner.md) found are edited, character for character. Aliases of the old model in the registry are changed too.
- Comments, docstrings and sentences are left alone unless `--include-docs` is given. Price tables, Bedrock and Vertex AI IDs, and files that are not UTF-8 are always left alone, and listed.
- `--exclude PATTERN` keeps paths out, as in `modelbump scan`.

Why it works this way: [ADR 0068](../adr/0068-bump-rewrites-ids-the-scanner-found.md).

## Moving the model to an environment variable

```bash
modelbump bump claude-3-haiku-20240307 --env ANTHROPIC_MODEL
```

```diff
+import os
 import anthropic

-MODEL = "claude-3-haiku-20240307"
+MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
```

- In Python files, whole string literals that are call arguments, values given to a name, or dict values read the variable, with the new model as the default. Everything else gets the plain bump.
- `import os` is added when missing, and `.env.example` in the root folder gets `ANTHROPIC_MODEL=claude-haiku-4-5-20251001`.
- Without `--env`, the bump prints a tip with the number of places it could move and a variable name for the provider.

Why: [ADR 0069](../adr/0069-move-hard-coded-ids-to-an-environment-variable.md).

## Evidence and repairs

The bump calls no model. Run the test (and the repair) first, then hand their files to the bump:

```bash
modelbump suite . --output suite.json
modelbump test suite.json --from ollama/qwen2.5:7b --to ollama/qwen3:4b-instruct \
  --patch fix.json --format json --output test.json
modelbump bump claude-3-haiku-20240307 --suite suite.json --report test.json --patch fix.json
```

```text
Would change 1 place in 1 file: claude-3-haiku-20240307 -> claude-haiku-4-5-20251001.
Would repair the prompt of 1 call in the code: support.py:30.
Would add evidence, tested ollama/qwen2.5:7b -> ollama/qwen3:4b-instruct:
  .modelbump/suite.json
  .modelbump/test.json
  .modelbump/repairs.json
```

- `--repairs REPORT --proposals DIR` takes the accepted patches from `modelbump repair run --report REPORT`; `--patch FILE` takes a patch file instead, such as `modelbump-repair.json`.
- A patch goes into the code only where its place is certain: the text to edit, or the call's whole system message, is exactly one plain string literal in the app's Python files. Otherwise it is listed under "Apply by hand" with the reason, and stays in `.modelbump/repairs.json`.
- `.modelbump/` holds `suite.json`, `test.json`, `repair.json` and `repairs.json`, copied as they were run. The scanner skips this folder.

Why: [ADR 0070](../adr/0070-bump-adds-evidence-and-writes-repairs-into-the-code.md).

## The pull request

```bash
modelbump bump claude-3-haiku-20240307 --suite suite.json --report test.json --patch fix.json --open-pr
```

- `--open-pr` checks that `gh` is installed, the working tree is clean and the branch `modelbump/OLD-to-NEW` is new. It then writes the files, commits them on that branch, pushes it, opens the pull request with `gh pr create`, and switches back to the branch you were on.
- The description is the evidence report: why the model changes, what changed, what to check by hand, and the test result per case with the command that runs it again. It holds verdicts and scores, never prompts or answers; those are in `.modelbump/test.json`.
- `--pr-body FILE` writes the description to a file, with no git at all.

Why: [ADR 0071](../adr/0071-pull-request-with-the-evidence-report.md).

## Every due model, on a schedule

```bash
modelbump bump-all --within 90            # list what would be bumped
modelbump bump-all --within 90 --open-pr  # one pull request per model
```

A model is due when the code uses it, it is retired or shuts down within `--within` days, and the registry suggests a replacement that is not retired. A model whose branch `modelbump/OLD-to-NEW` already exists is skipped, so a scheduled run never opens a second pull request for it.

In GitHub Actions:

```yaml
name: ModelBump
on:
  schedule:
    - cron: "0 6 * * 1"   # Mondays, 06:00 UTC
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

The repository must allow GitHub Actions to create pull requests (Settings → Actions → General → Workflow permissions). Pull requests opened with the default token do not start other workflows; pass a fine-grained token as `github-token` to run CI on them.

Why: [ADR 0072](../adr/0072-scheduled-bump-pull-requests.md).

## What the evidence may hold

`.modelbump/test.json` holds every prompt, answer and error message of the test. Before the bump writes it, it replaces these with `[REDACTED:kind]`:

- API keys and tokens in the published formats of OpenAI, Anthropic, Google, GitHub, AWS, Groq, Hugging Face and Slack;
- private key blocks, bearer tokens and JSON web tokens;
- email addresses (not `example.com`, `example.org` or `example.net`).

```text
Added evidence, tested ollama/qwen2.5:7b -> ollama/qwen3:4b-instruct:
  .modelbump/suite.json
  .modelbump/test.json
Redacted from the evidence: 1 Google API key, 2 email addresses.
```

The pull request description says the same. Names, street addresses and phone numbers are not looked for, so read `test.json` before merging. A patch that holds a key is refused, because it would go into the source code.

## Large repositories

On a 24,000-file repository, `modelbump scan` and `bump-all` each take about 3 seconds (19 and 34 before). A line with no registry ID and no provider prefix is skipped, a file with no ID is not parsed, and `bump-all` scans once for all its models.

Why: [ADR 0073](../adr/0073-redact-evidence-and-scan-large-repositories-fast.md).

## Code

| Module | What it does |
|--------|--------------|
| `modelbump.bump.rewrite` | `plan_bump` (scan, keep the old model's findings, build each file's new text), `apply_plan` (write, refusing files that changed), `plan_diff`, `skipped_lines` |
| `modelbump.bump.config` | `movable` (can this literal read an environment variable), `import_position`, `env_file_text`, `suggested_env_name` |
| `modelbump.bump.evidence` | `load_evidence` (read and check the suite, test report, repair report or patch file), `Evidence.files` |
| `modelbump.bump.prompts` | `literals` (plain string literals of a Python file), `plan_repair` (where each part of a patch goes, or why not), `apply_repair`, `render` |
| `modelbump.bump.pr` | `pr_body`, `pr_title`, `branch_name`, `check_repo` (gh, clean tree, new branch), `open_pr` (commit, push, `gh pr create`, switch back) |
| `modelbump.bump.due` | `due_models` (models the code uses that are retired or shut down soon, with their replacement or the reason there is none), `due_line` |
| `modelbump.bump.redact` | `redact`, `redact_json` (replace secrets and email addresses with `[REDACTED:kind]`, keeping the JSON valid), `secrets_in` (for patch checks), `summary` |
