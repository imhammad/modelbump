# ADR 0069: `bump --env NAME` moves hard-coded model IDs in Python to an environment variable, with the new model as the default

- **Status:** Accepted
- **Date:** 2026-11-01

## Context

Most apps write the model ID straight into the code: `client.messages.create(model="claude-3-haiku-20240307")`. The master plan counts this hard-coding as the root of the migration problem (94% of the apps in the source study). It means every model change is a code change, a review and a deploy, often in several files. [ADR 0068](0068-bump-rewrites-ids-the-scanner-found.md) made that code change automatic. This step makes the *next* change unnecessary: after one bump, the model can be switched with one setting.

There are several places a model could be moved to: an environment variable, a settings module the bump creates, or the app's own config framework (pydantic-settings, Django settings, Hydra). The bump must not break the app, and the diff must be small enough to review.

## Decision

1. **`modelbump bump OLD --to NEW --env NAME`** replaces each hard-coded literal with `os.environ.get("NAME", "NEW")`, and adds `import os` when the module does not import it yet.
   - The new model is the default, so the app behaves exactly as with a plain bump when `NAME` is not set.
   - `NAME` must be an upper-case name (`A-Z`, `0-9`, `_`), so nothing but a name is ever written.
2. **Only literals where the swap is plain Python are moved.** The finding must be a whole string literal (the ID with nothing else in the quotes), in a Python file that parses, and one of the following:
   - a call argument;
   - the value given to a name or a parameter default;
   - a dict value with a string key.

   These are left as literals, and only the ID inside them changes:
   - places that already read the environment (`os.getenv("X", "gpt-4o")`);
   - f-strings and bytes;
   - strings with more than the ID in them (`"openai/gpt-4o"`);
   - list items;
   - implicit concatenations (`"gpt-4o" "-mini"`);
   - TypeScript, JavaScript and other files.

   As a last check, a file whose new text does not parse keeps all its literals.
3. **`import os`** goes before the first top-level import, or after the module docstring and `from __future__` imports. It never goes above a shebang. `import os.path` counts as importing `os`; `import os as system` does not.
4. **`.env.example`** in the root folder gets `NAME=NEW` (it is created if missing), unless it already sets `NAME`. People copy that file to `.env`, so the setting is documented where they look for it. A single-file bump does not create one.
5. **Without `--env`, the bump says what it could do.** When some places could be moved, a tip names them and suggests a variable from the old model's provider: `ANTHROPIC_MODEL`, `OPENAI_MODEL`, `GEMINI_MODEL`, or `LLM_MODEL` when the model is not in the registry. Moving stays opt-in because it changes code shape, not only a value.

## Alternatives considered

- **A generated settings module (`llm_models.py` with constants):** one place in the code, but it adds a new file and an import into every file that uses it, and changing the model is still a code change.
- **The app's own config framework:** the best fit when one exists, but there are many of them and detecting them reliably is a project on its own. An environment variable works with all of them, and most frameworks read the environment anyway.
- **TypeScript with `process.env.NAME ?? "NEW"`:** right for Node, wrong for browser bundles, where `process` does not exist and Vite uses `import.meta.env`. A wrong guess breaks the build, so TypeScript and JavaScript get the plain bump for now.
- **One shared constant per file instead of repeating the default:** less repetition, but a bigger and harder to review diff. The repeated default is updated by the next bump anyway.
- **Moving by default:** a bump should first do the smallest change that works.

## Consequences

- After `bump --env`, switching models is one setting, and the next `modelbump bump` still finds and updates the defaults.
- A moved line can be longer than the project's line limit; the project's formatter handles it, and the PR in a later step says so.
- When different calls in one app use the same model, they now share one variable and move together. To keep them apart, bump one folder at a time with different names.
