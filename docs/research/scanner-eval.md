# Scanner evaluation

How well does `modelbump scan` find the model IDs a project depends on? Decision: [ADR 0029](../adr/0029-scanner-evaluation-set.md). Code: `research/scanner_eval/`.

## Building the set

```
export GITHUB_TOKEN=$(gh auth token)
uv run python -m research.scanner_eval.build
```

It reads `research/data/files.jsonl` and its diff cache (RQ4 of Paper 1), downloads 100 parent snapshots into `research/data/scanner_eval/snapshots/`, and writes:

| File | Contents |
|------|----------|
| `commits.jsonl` | The 100 commits, their parent, files kept and counts |
| `findings.jsonl` | Every scanner finding in every snapshot, with its context |
| `sites.jsonl` | Every known site (a removed line naming the old model), found or not, with the reason for a miss |
| `sheet.csv` | The blind labelling sheet |
| `sheet_key.csv` | Group and context of each sheet row (do not open before labelling) |
| `build.stats.json` | Counts, recall with a 95% Wilson interval, misses by reason |

## Labelling guide

For each row of `sheet.csv`, read `line_text` with the lines `before` and `after` (open the `url` if that is not enough), and fill in `dependency`:

| Label | When |
|-------|------|
| `yes` | The model ID can be **used at run time** to call or configure that model: an API call, a default, a constant, a config value, an environment file, a list of models users can pick from, a fallback, or a test that calls the API with it. |
| `no` | The ID is only **described**: a comment, a docstring, help or log text, an error message, a README-like string, a price or token-limit table, test data that never reaches an API, or a word that only looks like an ID. |

Rules for unclear rows:

- A commented-out line of code (`# model = "gpt-4"`) is `no`: it does not run.
- A mapping from model to price, context size or display name is `no`, unless the same mapping also decides which model is called.
- A list or menu of models a user can select is `yes`.
- If you cannot decide even after opening the link, write `unclear` and explain in `note`.

Label in order, without opening `sheet_key.csv`. In Numbers, export the sheet back to CSV with the same name (File, Export To, CSV).
