# ADR 0067: Use Qwen 3 4B Instruct for the second migration, and keep a proposal's added instruction when its edits do not fit

- **Status:** Accepted
- **Date:** 2026-10-31

## Context

The first run of the RQ3 experiment ([ADR 0066](0066-rq3-repair-experiment.md)) used `ollama/qwen3:4b` with thinking off. Two things went wrong.

**The model only thinks.** Qwen 3 4B regressed on 57 of 70 corpus cases, against 4 for Qwen 3 8B. Its answers start with plain-text reasoning ("We are given...", "Okay, let's tackle this...") and are 1,600 to 1,900 characters long, so the 400-token limit cuts them off before any answer. In Ollama the `qwen3:4b` tag has the same digest as `qwen3:4b-thinking` (Qwen3-4B-Thinking-2507, per the tags page at ollama.com/library/qwen3/tags), a model that always reasons and ignores `reasoning_effort: none`. Since its trace has no opening `<think>` tag, the runner's think stripping ([ADR 0039](0039-pin-local-models-to-their-digest.md)) cannot remove it. The 8B tag is still the hybrid model, which honours thinking off. Changing the prompt cannot repair that, and the overnight run showed it: 1 of 11 calls repaired, and nearly every 4B candidate screened below 0.2.

**Evidence proposals were thrown away.** 5 of 11 evidence runs had no candidates at all. The proposer saw failing answers full of reasoning text and wrote edits whose `find` came from those answers or from one case's inputs, which match 0 times in the prompt. Its answers usually had a useful `add_system` too, and the whole answer was refused ([ADR 0063](0063-candidate-patches-from-a-local-model.md)).

## Decision

1. **The second migration is Qwen 2.5 7B → `ollama/qwen3:4b-instruct`** (Qwen3-4B-Instruct-2507, non-thinking), still with thinking off and the same 400 tokens. The corpus run goes to `research/data/corpus/run-qwen3-4b-instruct`, which `research.repair_eval.run` now reads by default. The thinking run is kept, reported as a warning rather than a result: a model tag can silently move to a different kind of model, and a reference-based test then flags almost everything.
2. **Salvage proposals:** when an answer has an `add_system` and edits that are invalid (an edit replaces text with itself) or do not fit the suite (a `find` not exactly once in every case), the edits are dropped and the candidate keeps the `add_system`. The patch's note records `edits dropped:` and the reason. An answer with edits only is still refused. All strategies share this check, so the comparison stays fair.
3. **The reported run** is `--calls 8 --drop-call app-33/api/index.py:53`: every regressed call of the 8B migration (3 after app-33) and the first 8 of the 4B Instruct migration. The apps are in random order (seed 2030), so the first 8 calls are a fair sample. One night on a 16 GB laptop; more calls can be added later from the cache.

## Alternatives considered

- **Keep the thinking model and raise `max_tokens`:** a fair test of a thinking model, but the app's prompt is not the problem then, and every answer would cost several times more on a laptop.
- **Strip plain-text reasoning:** there is no reliable marker where the reasoning ends when the answer is cut off.
- **Show the proposer only the end of each failing answer:** it would hide what the model did wrong. With an instruct model the answers are short again.
- **Refuse the whole answer, as before:** simpler, but it throws away a usable instruction because of a copying mistake, and it hit the evidence strategy hardest, because only that strategy sees answers.

## Consequences

- The corpus run must be redone for the new model (Qwen 2.5 answers and generated inputs come from the cache).
- `research/data/repair_eval/` from the thinking run should be moved aside before the new run, so the results do not mix.
- Candidates from earlier `repair propose` runs are unchanged: salvage only affects new answers.
