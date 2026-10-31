# Prompt repair on real regressions

How often does `modelbump repair` fix a real regression without breaking anything else, how does it compare with the baselines, and what does it cost? This is Phase 6's evaluation, RQ3 of the tool paper. Decisions: [ADR 0062](../adr/0062-prompt-patches.md) (patches), [ADR 0063](../adr/0063-candidate-patches-from-a-local-model.md) (candidates), [ADR 0064](../adr/0064-repair-loop-screen-then-confirm.md) (the loop), [ADR 0065](../adr/0065-repair-baselines.md) (baselines), [ADR 0066](../adr/0066-rq3-repair-experiment.md) (this experiment), [ADR 0067](../adr/0067-instruct-model-and-salvaged-proposals.md) (the second model, and proposals whose edits do not fit). Code: `research/repair_eval/`.

## Run it

Ollama running with `qwen2.5:7b`, `qwen3:8b`, `qwen3:4b-instruct` and `gemma3:12b` pulled, and the corpus built ([Test suites on real apps](suites.md)).

```bash
# The second migration: the same corpus, Qwen 3 4B Instruct as the new model.
# Not the plain qwen3:4b tag: that one is a thinking-only model (ADR 0067).
uv run python -m research.corpus.run --new ollama/qwen3:4b-instruct --out research/data/corpus/run-qwen3-4b-instruct \
  --drop-case "app-13/docs/docs/API-Reference/python-examples/api-openai-responses/additional-configuration-for-openai-client-libraries.py:16#1" \
  --drop-case "app-13/docs/versioned_docs/version-1.9.0/API-Reference/python-examples/api-openai-responses/additional-configuration-for-openai-client-libraries.py:16#1" \
  --drop-case "app-14/src/agenthatch/skill/reflection.py:202#1" \
  --drop-case "app-28/processing/digest.py:72#1" \
  --drop-case "app-29/openai_demo.py:13#1"

# The experiment: every regressed call of run-v3 and run-qwen3-4b-instruct.
uv run python -m research.repair_eval.run --calls 1 --drop-call app-33/api/index.py:53  # a quick trial
uv run python -m research.repair_eval.run --calls 8 --drop-call app-33/api/index.py:53  # the reported run (a night)
```

| Option | Default | What it does |
|---|---|---|
| `--run` | `run-v3` and `run-qwen3-4b-instruct` | A corpus run folder. Repeatable. |
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

Run on 31 October 2026 on a 16 GB MacBook Air, all models local and free. In both migrations the same three calls regressed (app-33 aside): a numbered-list rule at app-05, the tone of a memory summary at app-07, and a JSON key at app-19. That gives 6 regressed calls, each tried with every strategy.

| Migration | Call | Output | Cases | evidence | naive | iterative |
|---|---|---|---|---|---|---|
| Qwen 3 8B | app-05 `demo.py:93` | text | 1 | **REPAIRED** | skipped | rejected |
| Qwen 3 8B | app-07 `memory.py:817` | text | 3 | rejected (collateral) | skipped | skipped |
| Qwen 3 8B | app-19 `llm.py:387` | JSON | 1 | skipped | skipped | skipped |
| Qwen 3 4B Instruct | app-05 `demo.py:93` | text | 1 | rejected | skipped | **REPAIRED** |
| Qwen 3 4B Instruct | app-07 `memory.py:817` | text | 3 | rejected | rejected | skipped |
| Qwen 3 4B Instruct | app-19 `llm.py:387` | JSON | 1 | skipped | skipped | skipped |

*Skipped:* the best candidate screened more than 0.25 below the old model, so it was not confirmed. *Rejected:* confirmed on 100 fresh answers per model per case and found worse than the old model on at least one case. *Collateral:* the candidate fixed the regressed case but broke another case of the call. The calls with one case could not be widened (no input slots to fill, or no new inputs came back).

| Strategy | Repaired | 95% CI (Wilson) | Rejected | Skipped | Blocked for collateral | Requests per call (proposer / old / new / judge) |
|---|---|---|---|---|---|---|
| evidence | 1 of 6 | 3% to 56% | 3 | 2 | 1 | 5 / 244 / 215 / 390 (854) |
| naive | 0 of 6 | 0% to 39% | 1 | 5 | 0 | 5 / 145 / 122 / 210 (481) |
| iterative | 1 of 6 | 3% to 56% | 1 | 4 | 0 | 6 / 307 / 243 / 400 (957) |
| no repair | 0 of 6 | 0% to 39% | | | | 0 |

Requests include answers served from the cache, so each one would be a paid request on a cloud API. Across both migrations, 2 of the 6 calls were repaired by at least one strategy.

### What the run shows

1. **Repair is possible but not common.** Prompt changes repaired 2 of 6 real regressions, both on the same call. The intervals are wide: this is a case study of six calls, not a precise rate.
2. **The safety check matters.** Both accepted patches passed the non-inferiority check on every case of their call. Twice a candidate looked fine and was stopped. On the 4B app-05 call, the evidence candidate scored 1.00 on its 10 screening answers and then failed on 100 fresh ones. On the 8B app-07 call, the evidence candidate fixed the regressed case and broke another of the call's cases.
3. **One test case overstates repair.** With one case per call, the loop repaired app-07 earlier (old 77 of 100, patched new 100 of 100, [ADR 0065](../adr/0065-repair-baselines.md)). With 3 cases, no strategy did. A fix judged on a single input can be a fix for that input only.
4. **Seeing the failures helps, asking for a rewrite does not.** The naive rewrite repaired nothing, and 5 of its 6 runs were too far behind to confirm. On the 4B app-05 call its best candidate screened at 0.00. The evidence and iterative strategies each repaired one call. The iterative strategy cost the most (about 960 requests per call), because it screens every candidate it writes.
5. **Some regressions are not prompt problems.** At app-19 the new models drop a required JSON key, and no candidate from any strategy screened above 0.43 against the old model's 1.00.
6. **Skipping saves most of the cost.** 11 of the 18 strategy runs stopped after screening. Each skip saves 100 answers per model per case, plus judging for free text.

### Limits

Six calls from three call sites, two migrations in one model family, one proposer (Gemma 3 12B) and one judge (the same model, which agrees with hand labels on 83% of answers, [Test suites on real apps](suites.md)). Regressions were found at k = 10, so only large ones show up. app-33 was left out by hand, below.

## The case left out

`app-33/api/index.py:53` asks the model to read the numbers off a body-composition scan image, but the test case holds only the text, not the image. Qwen 2.5 7B made up plausible numbers and passed the JSON checks. Qwen 3 answered `null` for every number and failed them. The old model's reference answer was invented, so this regression is false, and no prompt change should "fix" it. It is left out with `--drop-call`. Reference-based tests share this limit: they reward an old model that guesses confidently.

## The first try with the `qwen3:4b` tag

The first second-migration run used the plain `qwen3:4b` tag. In Ollama that tag is the same model as `qwen3:4b-thinking` (Qwen3-4B-Thinking-2507), which reasons before every answer whatever `--new-think` says, and writes that reasoning as plain text ("Okay, let's tackle this..."). With the corpus limit of 400 tokens, most answers ended before the reasoning did: 57 of 70 cases REGRESSED. The repair run then repaired 1 of 11 calls (app-05 of the 8B migration, by the evidence strategy). Almost every candidate on the 4B calls screened below 0.2, and 5 of 11 evidence runs had no candidates, because the proposer copied its edits from the failing answers. A cut-off reasoning trace cannot be repaired by changing the prompt, so that run is kept only as a warning: one model tag can silently switch to a different kind of model ([ADR 0067](../adr/0067-instruct-model-and-salvaged-proposals.md)).

## Earlier runs (one case per call, Qwen 3 8B only)

| Strategy | Repaired | Calls |
|---|---|---|
| evidence | 2 of 4 | app-05, app-07 |
| naive | 0 of 4 | none |
| iterative | 1 of 4 | app-07 |

These had one case per call, so the guarantee covered one input. They are kept as a first look; the numbers to report come from the run above.
