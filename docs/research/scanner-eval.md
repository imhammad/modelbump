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

## Scoring

Decision: [ADR 0030](../adr/0030-scoring-the-scanner-evaluation.md).

```
uv run python -m research.scanner_eval.score
```

It checks that every row of `sheet.csv` is in `sheet_key.csv` and that every answer is `yes`, `no` or `unclear` (blank rows are counted and skipped, so it can run halfway). It prints, and writes to `scanner_eval.json`:

- precision for each group, with a 95% Wilson interval; `unclear` rows are counted but left out of the share;
- precision over all findings, weighted by the size of each group;
- precision with `--skip-comments`, which is the same without the documentation group;
- the share of `yes` for each context, unweighted;
- recall on known sites, copied from `build.stats.json`.

If a second person labels a copy of the blank sheet, add `--second path/to/their_sheet.csv` to get Cohen's kappa.

## Re-scoring after a scanner change

Decision: [ADR 0032](../adr/0032-rescoring-after-a-scanner-change.md). Do not run the build again after the scanner changes: it would draw a new sheet. Instead:

```
uv run python -m research.scanner_eval.rescore
```

It scans the saved snapshots with the current scanner, checks that it finds the IDs at the same places, and gives each labelled row its new context. It prints precision and recall for four settings (all findings, `--skip-comments`, `--skip-tests`, both) and the labelled rows whose context changed. For sites missed because their file type was not scanned, it downloads those files from `raw.githubusercontent.com` into `extra/` (`--no-fetch` skips this). It writes `rescore.json` and `rescore.findings.jsonl`, and changes none of the build's files.

The rules of [ADR 0031](../adr/0031-describing-contexts-and-test-files.md) were written after reading these labels, so their gain on this sheet is in-sample.

The sheet shows the first 300 characters of a line, so on very long lines (flow files, one-line JSON) the ID can be out of view. Those rows were re-checked from the text around the ID ([ADR 0034](../adr/0034-replay-warning-sources.md)). The first-pass labels are kept in `sheet_labelled.csv`; `--sheet sheet_labelled.csv` scores them.

## Replay: would the scanner have warned in time?

Decision: [ADR 0033](../adr/0033-replaying-the-scanner.md).

```
uv run python -m research.scanner_eval.replay
```

For each of the 100 commits, it scans the snapshot from just before the migration. If the scanner reports the model the commit moved away from, the project counts as flagged. The first warning comes on the provider's notice day, or, for models without a notice date (Google), 90 days before the shutdown, when the scanner says `RETIRING_SOON` ([ADR 0034](../adr/0034-replay-warning-sources.md)). Projects that migrated before any warning are counted on their own. It prints, for each setting, how many projects were flagged, and the median days between the first warning and the migration. For flagged projects that migrated only after the shutdown, it also prints how many days earlier `--fail-within 30` would have failed CI. It writes `replay.jsonl` (one row per commit) and `replay.json`.

The snapshot is the code at the migration, not on the notice day, so the warning lead is an upper bound.
