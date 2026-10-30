# ADR 0065: Compare the repair with two baselines, a naive rewrite and a score-guided optimiser, built in-house

- **Status:** Accepted
- **Date:** 2026-10-30

## Context

RQ3 asks how well suite synthesis plus prompt repair restores behaviour after a migration. A fix rate means little alone. The master plan names three baselines: **no repair**, a **naive** "rewrite this prompt for model Y", and **DSPy-style optimisation**.

The first run of the loop ([ADR 0064](0064-repair-loop-screen-then-confirm.md)) on the four corpus regressions (Qwen 2.5 7B → Qwen 3 8B) repaired 2 of 4 calls:

| Call | Kind | Old | Unpatched new | Best candidate (screen) | Confirmed (100 fresh answers) |
|---|---|---|---|---|---|
| app-05 `demo.py:93` | text | 0.90 | 0.10 | 1.00 | old 91, new 100: **repaired** |
| app-07 `memory.py:817` | text | 0.70 | 0.10 | 1.00 | old 77, new 100: **repaired** |
| app-19 `llm.py:387` | JSON | 1.00 | 0.29 | 0.20 | old 99, new 27: rejected |
| app-33 `index.py:53` | JSON | 1.00 | 0.62 | 0.62 | old 100, new 62: rejected |

At app-19 every candidate scored lower than no change. At app-33 every candidate scored exactly what the unpatched model scored, which suggests that the JSON check measures something that no added instruction changes. The RQ3 experiment checks those answers by hand. Four calls show that the loop works end to end, not how good the repair is. The baselines say what part of a fix comes from showing the proposer the failing answers.

## Decision

All strategies write the same thing (one-patch candidate files, checked against the suite, [ADR 0063](0063-candidate-patches-from-a-local-model.md)). They use the same proposer model and go through the same loop, so its guarantee holds for each of them. They differ only in what the proposer sees. `modelbump repair propose --strategy`:

- **`evidence`** (default, ModelBump's own): the prompt, the old model's reference answer, failing new answers and the checks they failed.
- **`naive`**: the prompt and the two model names only, asked to make the prompt "work well with" the new model. This is the common manual fix.
- **`iterative`**: a score-guided optimiser in the style of OPRO (Yang et al., *Large Language Models as Optimizers*, arXiv:2309.03409) and DSPy's COPRO (Khattab et al., *DSPy*, arXiv:2310.03714). It never shows an answer. Round 0 proposes from the prompt and the two models' mean scores. Each candidate is then screened (`--screen-runs`, default 10, the same samples the loop screens, so the loop reads them from the cache). Each later round shows every change tried so far with its score, worst first, and asks for a better one. The defaults are `--rounds 3` and `--per-round 2`: 6 candidates, against 5 for the other strategies. `proposals.json` records each candidate's round and screen score (`trace`).
- **No repair** needs no code. It is the unpatched new model, which the loop already screens.

The iterative strategy reads the test's settings (models, reference, temperature, max tokens, judge) from the JSON report, so that its screen answers match the test and the loop. The report now also records `old_think` and `new_think`. For older reports, `--from-think` and `--to-think` give them (the corpus run used `--to-think none`).

**Built in-house, not with DSPy.** DSPy routes model calls through LiteLLM, which [ADR 0036](0036-runner-speaks-openai-compatible-http.md) keeps out of this project. Its optimisers also expect a training set of examples and a metric function in its own program format. The idea being compared, score-guided instruction search, takes about a hundred lines on top of the runner and the loop, with the same cache, budget and free local models.

## Alternatives considered

- **Running DSPy itself:** the faithful baseline, but it would add LiteLLM and a second way of calling models, and its prompts would not be byte-for-byte comparable with ours. The paper names this as a difference from the original.
- **A naive baseline with no proposer** (one fixed instruction, such as "Follow the instructions exactly."): cheaper, but it says little about what a developer would do, which is to ask a model.
- **Giving the iterative strategy the failing answers too:** that is OPRO plus our evidence. It would mix the two effects the comparison separates.
- **Equal requests across strategies:** the iterative strategy spends screening answers that the loop would spend anyway, and its proposer requests are 6 against 5. The experiment reports requests and tokens per strategy, rather than forcing them equal.

## Consequences

- RQ3 can compare evidence, naive, iterative and no repair on the same regressions with the same loop.
- The iterative strategy costs `rounds × per_round` proposer requests plus `screen_runs` new answers per case for each candidate (judged too for free text). Most of those are reused by the loop.
- `modelbump repair propose --strategy iterative` asks the old and new models as well as the proposer, so it needs all three in Ollama.
