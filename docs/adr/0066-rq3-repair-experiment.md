# ADR 0066: Measure the repair on two migrations, with each regressed call widened to three cases, and count every request

- **Status:** Accepted
- **Date:** 2026-10-30

## Context

RQ3 asks how well suite synthesis plus prompt repair restores behaviour after a migration, compared with the baselines of [ADR 0065](0065-repair-baselines.md). The first runs give four regressed calls from one migration (Qwen 2.5 7B → Qwen 3 8B):

| Strategy | Repaired |
|---|---|
| evidence | 2 of 4 (app-05, app-07) |
| naive | 0 of 4 (often worse than no change) |
| iterative | 1 of 4 (app-07) |

Four calls cannot separate the strategies: a 95% interval on 2 of 4 runs from 15% to 85%. Three more problems:

1. **One case per call.** The corpus run tested one case per call, so the loop's guarantee covered one input, and a candidate could only add a system line (an edit to a slot's text would not match every case, [ADR 0062](0062-prompt-patches.md)). A repair that fixes one input and breaks the others could not be seen.
2. **Cost.** Every screened-best candidate was confirmed on 100 fresh answers per model per case, even when its screen was far below the old model and could not pass. Those confirmations took most of the hours of the runs.
3. **app-33.** Every candidate scored exactly what the unpatched new model scored (0.62). That points at the case, not the model.

## Decision

The experiment lives in `research/repair_eval/` and reads finished corpus runs ([ADR 0059](0059-run-the-corpus-end-to-end.md)).

1. **A second migration: Qwen 2.5 7B → Qwen 3 4B** (thinking off). `research.corpus.run` gets `--new` and `--new-think`. The old model, the picked calls, the generated inputs and the old answers stay the same and come from the cache, so only the new model's answers and their judging are new. The run uses the same five `--drop-case` ids as `run-v3` ([ADR 0060](0060-judge-instructions-from-corpus-labels.md)). Qwen 3 4B is a smaller model in the same family, so it is likely to regress more often, and it runs free on a 16 GB laptop.
2. **Widen every regressed call to 3 cases:** its corpus case plus 2 new inputs from the generator ([ADR 0051](0051-generated-test-inputs-from-a-local-model.md)), with a sample number the corpus never used (`WIDEN_SAMPLE` 100) so they are new inputs. Calls with no slots keep their one case. The widened call is tested again (fixed k = 10, as the corpus run). A call with no REGRESSED case left is reported, not repaired.
3. **Every strategy runs through the same loop** ([ADR 0064](0064-repair-loop-screen-then-confirm.md)) with the defaults: screen 10, confirm 100, top 1, alpha 0.05, margin 0.10. Candidates are made fresh per strategy for the widened call.
4. **Skip a confirmation that cannot pass** (`repair run --max-gap`, default 0.25): when the best candidate's screen mean is more than 0.25 below the old model's, it is not confirmed and the call is reported as `SKIPPED`. Skipping only ever rejects, so the guarantee is unchanged: it bounds the chance of a wrong accept, and a skip never accepts. A candidate that far behind on 10 answers per case would need the new model to gain about 25 points on fresh answers to pass. `--max-gap 1` turns the skip off.
5. **Count every request**, per call and strategy, by role (proposer, old, new, judge), both all requests and those not served from the cache. Cached answers were paid for once, by an earlier step or strategy, so the paper reports both.
6. **Metrics per strategy:** fix rate (calls repaired / regressed calls) with a Wilson 95% interval; outcomes (`REPAIRED`, `REJECTED`, `SKIPPED`, `NO CANDIDATES`); calls **blocked for collateral** (a confirmed candidate fixed every regressed case but broke another case of the call, which only widening can show); mean requests per call. "No repair" is 0 by definition.
7. **app-33 is checked by hand** before the full run. If its case is broken (the new answers fail for a reason no prompt change can fix, such as an input the case does not send), it is left out with `--drop-call` and the reason goes in the results.

## Alternatives considered

- **More calls per app from the first migration:** the corpus run already tested up to 3 calls per app; the rest have no test case yet. A new model gives new regressions for the price of new-model answers only.
- **A model from another family as the second migration** (Llama, Gemma): a bigger change, but Gemma 3 12B is the judge and proposer, and a family change mixes in tokenizer and chat-template effects. The 4B model keeps the comparison within one model family, so a regression comes from the model and not from a new chat format.
- **More generated cases per call (5 or 10):** a stronger guarantee per call, but each case costs 200 confirmation answers per model per candidate. Three is the smallest number that can show a collateral break and lets a patch edit the template.
- **Confirming every candidate:** the cleanest cost comparison, but most of the cost would go to candidates that cannot pass.

## Consequences

- RQ3 reports a fix rate with an interval over two migrations, safety (collateral breaks caught) and cost per strategy.
- The guarantee now covers three inputs per call where the call has slots.
- The repair report and its JSON gain `max gap` and the skipped candidates; existing patch files and reports still read.
- The full run takes hours on a laptop. Every answer is cached, so a rerun or a trial with `--calls 1` costs little.
