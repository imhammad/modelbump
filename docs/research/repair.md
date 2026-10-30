# Prompt repair on real regressions

How often does `modelbump repair` fix a real regression without breaking anything else, how does it compare with the baselines, and what does it cost? This is Phase 6's evaluation, RQ3 of the tool paper. Decisions: [ADR 0062](../adr/0062-prompt-patches.md) (patches), [ADR 0063](../adr/0063-candidate-patches-from-a-local-model.md) (candidates), [ADR 0064](../adr/0064-repair-loop-screen-then-confirm.md) (the loop), [ADR 0065](../adr/0065-repair-baselines.md) (baselines), [ADR 0066](../adr/0066-rq3-repair-experiment.md) (this experiment). Code: `research/repair_eval/`.

## Run it

Ollama running with `qwen2.5:7b`, `qwen3:8b`, `qwen3:4b` and `gemma3:12b` pulled, and the corpus built ([Test suites on real apps](suites.md)).

```bash
# The second migration: the same corpus, Qwen 3 4B as the new model.
uv run python -m research.corpus.run --new ollama/qwen3:4b --out research/data/corpus/run-qwen3-4b \
  --drop-case "app-13/docs/docs/API-Reference/python-examples/api-openai-responses/additional-configuration-for-openai-client-libraries.py:16#1" \
  --drop-case "app-13/docs/versioned_docs/version-1.9.0/API-Reference/python-examples/api-openai-responses/additional-configuration-for-openai-client-libraries.py:16#1" \
  --drop-case "app-14/src/agenthatch/skill/reflection.py:202#1" \
  --drop-case "app-28/processing/digest.py:72#1" \
  --drop-case "app-29/openai_demo.py:13#1"

# The experiment: every regressed call of run-v3 and run-qwen3-4b.
uv run python -m research.repair_eval.run --calls 1   # a quick trial: one call per migration
uv run python -m research.repair_eval.run             # every regressed call (hours)
```

| Option | Default | What it does |
|---|---|---|
| `--run` | `run-v3` and `run-qwen3-4b` | A corpus run folder. Repeatable. |
| `--out` | `research/data/repair_eval` | Where results go. Not committed. |
| `--calls` | all | Only the first N regressed calls of each run. |
| `--extra` | 2 | Generated cases added to each regressed call. |
| `--strategy` | all three | `evidence`, `naive` or `iterative`. Repeatable. |
| `--drop-call` | none | Leave out `app-NN/path:line`, for a case found broken by hand. Repeatable. |

## What it does

For each corpus run (one migration) and each call with a REGRESSED case:

1. **Widen** the call to 3 cases: its corpus case and 2 new inputs from the generator. Calls with no slots keep their one case.
2. **Test** the widened call on both models (fixed k = 10). A call that no longer has a REGRESSED case is noted and skipped.
3. For each **strategy**, write candidates with Gemma 3 12B and run the repair loop: screen on 10 answers per case, skip the best candidate if it screens more than 0.25 below the old model, otherwise confirm it on 100 fresh answers per model per case. A call counts as repaired only if every case is no worse than the old model.

Every request is counted by role (proposer, old, new, judge), with and without the cache.

## Outputs

| File | What it holds |
|---|---|
| `results.jsonl` | One row per call and strategy: cases, best screen, old and unpatched means, status, blocked for collateral, requests, fresh requests, tokens. |
| `summary.json` | Per strategy: fix rate with a Wilson 95% interval, outcomes, calls blocked for collateral, mean requests per call. Also the calls that were dropped or stopped regressing. |
| `<migration>/<app>/<call>/suite-report.json` | The widened call's test, with every answer. |
| `<migration>/<app>/<call>/<strategy>/` | The candidates (`proposals.json` and one file each) and the loop's `repair-report.json`. |

## Results

To be filled in Step P6-6, from the full run.

## Earlier runs (one case per call, Qwen 3 8B only)

| Strategy | Repaired | Calls |
|---|---|---|
| evidence | 2 of 4 | app-05, app-07 |
| naive | 0 of 4 | none |
| iterative | 1 of 4 | app-07 |

These had one case per call, so the guarantee covered one input. They are kept as a first look; the numbers to report come from the run above.
