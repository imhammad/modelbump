# ADR 0059: Run the corpus end to end, a few calls per app, and label across apps

- **Status:** Accepted
- **Date:** 2026-10-29

## Context

Phase 5 is done when `modelbump test` works end to end on the corpus of real apps ([ADR 0057](0057-benchmark-corpus-from-migration-snapshots.md)) and the judge's agreement with people is measured on about 200 hand labels. The corpus has 356 LLM calls in 40 apps. Running all of them with 50 answers per model and a judge would take days on a 16 GB laptop: a free-text case costs 3 reference answers, 2 × k answers and 2 × k judge calls.

Running the corpus also showed a gap in the suite builder: a call whose prompt is all written text, with no slots (33 in the corpus), got no test case, because cases only came from inputs. A fixed prompt needs no inputs.

## Decision

- **A fixed prompt is its own test case** (`build_suite`, source `fixed prompt in the code`).
- **`research.corpus.run`** runs every app in `apps.jsonl`:
  1. Pick up to **3 calls per app**, at random (seed 2033, per repository), among calls that can get a complete case: no tools, every message readable, some written text. Every app then weighs about the same, and a few big apps cannot fill the corpus.
  2. Give each picked call **one case**: its fixed prompt, the first input from the app's code, or one input written by the generator (`ollama/qwen2.5:7b`, [ADR 0051](0051-generated-test-inputs-from-a-local-model.md)).
  3. Run the case with `modelbump test`'s engine: **Qwen 2.5 7B to Qwen 3 8B** (thinking off), **fixed k = 10 + BH**, free text judged by Gemma 3 12B. These are the same models as the demo and the Phase 4 study.
  4. Write each app's suite and report (`runs/app-NN.suite.json`, `runs/app-NN.report.json`), one row per app (`runs.jsonl`), and the totals (`run.stats.json`).
- **One merged report** (`report-all.json`): every app's cases, ids prefixed `app-NN/`. `modelbump judge sheet` reads it as it is, so the ~200 paper labels are drawn across all apps, half judge PASS and half judge FAIL ([ADR 0055](0055-check-the-judge-against-hand-labels.md)).
- `--apps N` runs only the first N apps, for a trial. Every answer is cached, so the full run reuses the trial, and a stopped run continues where it stopped.

## Alternatives considered

- **k = 50, as in `modelbump test`'s default:** EQUIVALENT becomes reachable, but the run would be five times longer. With k = 10 a case can still be REGRESSED when the new model clearly fails (as in the demo), and the answers are what the labels need. The corpus run reports REGRESSED cases, not equivalence.
- **Every call:** more cases, but days of laptop time, and the apps with 20 to 40 calls would dominate the labels.
- **Sequential + e-BH:** stops early on clear cases, but with k at most 10 it rarely stops before the end.

## Consequences

- About 120 cases at most (fewer where an app has fewer than 3 testable calls), and a few thousand model requests: a run of some hours, best left overnight.
- The corpus verdicts are a sample of what `modelbump test` finds on real apps, not a full test of each app.
- Labels across 40 apps cover many more prompts than the 4-prompt demo, so the agreement numbers will be the ones the paper reports.
