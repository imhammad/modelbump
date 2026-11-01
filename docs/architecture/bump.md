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

## Code

| Module | What it does |
|--------|--------------|
| `modelbump.bump.rewrite` | `plan_bump` (scan, keep the old model's findings, build each file's new text), `apply_plan` (write, refusing files that changed), `plan_diff`, `skipped_lines` |
| `modelbump.bump.config` | `movable` (can this literal read an environment variable), `import_position`, `env_file_text`, `suggested_env_name` |
