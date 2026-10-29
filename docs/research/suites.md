# Test suites on real apps

Does `modelbump test` work on real apps, and how far can its free-text judge be trusted? This is Phase 5's evaluation and part of RQ3. Decisions: [ADR 0057](../adr/0057-benchmark-corpus-from-migration-snapshots.md) (the corpus), [ADR 0058](../adr/0058-judge-probes.md) (judge probes), [ADR 0059](../adr/0059-run-the-corpus-end-to-end.md) (the run), [ADR 0060](../adr/0060-judge-instructions-from-corpus-labels.md) and [ADR 0061](../adr/0061-no-made-up-specifics.md) (the judge's instructions). Code: `research/corpus/`.

## Run it

```bash
export GITHUB_TOKEN=$(gh auth token)
uv run python -m research.corpus.build     # the corpus: 40 apps, no model calls
uv run python -m research.corpus.run       # every app, Ollama with qwen2.5:7b, qwen3:8b, gemma3:12b
```

The build reuses the scanner evaluation's snapshots and downloads the rest. The run takes about 7 minutes per app on a 16 GB laptop the first time. Every answer is cached, so a rerun with another judge only asks the judge. The cases with a wrong reference were left out with `--drop-case` (the five ids are in ADR 0060). Everything is written to `research/data/corpus/`, which is not committed.

## The corpus

40 Python apps drawn at random from Paper 1's migration commits, each as it was just before it moved off a retiring model. One app per repository, and each has at least one LLM call with written prompt text.

| | |
|---|---|
| Snapshots screened | 223 (119 had no Python, 36 no LLM call, 22 no prompt text) |
| Python files | 5,566 |
| LLM calls | 356 (187 with prompt text, 33 fixed prompts, 243 with slots) |
| Oracle kinds | 224 text, 98 JSON, 34 tools, 0 label |
| Calls with test inputs in the app's own code | 11 |

## The run

Up to 3 calls per app, one case per call, Qwen 2.5 7B against Qwen 3 8B (thinking off), fixed k = 10 + BH.

| | |
|---|---|
| Apps with a case | 35 |
| Cases | 70 (42 JSON, 28 text; 59 with generated inputs), after 5 with a wrong reference were dropped |
| Verdicts (judge v3) | 4 REGRESSED, 2 IMPROVED, 64 INCONCLUSIVE |
| Requests | 2,247 for the first run; 446 for each re-judge |

With 10 answers per model no case can be shown EQUIVALENT ([ADR 0053](../adr/0053-suite-file-and-modelbump-test.md)). The run is there to show the pipeline works on real code and to give the judge real answers to be checked on.

## The judge

Each free-text answer is graded PASS or FAIL by Gemma 3 12B against an old-model reference answer. It was checked two ways: blind hand labels on corpus answers, and **probes**, which are reference answers broken on purpose in four known ways (plus correct paraphrases as a control).

Three versions of its instructions were tried. Each fresh sheet was used once as a test, and then as a development check for the next version:

| Version | What changed | Probes caught | Corpus labels |
|---|---|---|---|
| v1 ([ADR 0056](../adr/0056-bigger-judge-and-no-invented-facts.md)) | Fail any fact not in the prompt or the reference | 22 of 24 | Too strict: FAILs right 57%, kappa 0.47 |
| v2 ([ADR 0060](../adr/0060-judge-instructions-from-corpus-labels.md)) | The reference is one answer; open-ended prompts may add content | 9 of 24 | 79% agreement, kappa 0.47 |
| **v3** ([ADR 0061](../adr/0061-no-made-up-specifics.md)) | v2, plus: no made-up specifics about the app (links, contacts, policies, steps) | **22 of 24** | **83% agreement, kappa 0.56** |

**v3 on its fresh test sheet** (100 answers):

| | Agreed | 95% CI |
|---|---|---|
| Judge said PASS | 87% (55 of 63) | 76-94% |
| Judge said FAIL | 68% (25 of 37) | 50-81% |

Corrected to the labels, both models pass 76% (64-85%) of free-text answers.

## What we learned

- **A reference-guided judge needs a right reference.** 5 of 75 cases had a wrong one (wrong dates, a wrong sports venue, an empty input, a reference that broke its own prompt's rule), and on those no verdict means anything.
- **One rule does not fit every prompt.** Failing every fact not in the prompt catches invented support details but fails good answers to prompts that ask for something new. Allowing new content fixes those but lets support answers invent links and steps. Naming the app-specific details that must never be made up handles both, on these apps.
- **Hand labels and probes catch different failures.** v2 looked better on the corpus labels than v1, and only the probes showed what it had lost.
- **Test inputs mostly have to be generated.** The apps' own code gave inputs for 11 of 356 calls.

## Limits

- Python only, OpenAI-style, Anthropic and Gemini calls; tool calls are not scored.
- One labeller, the author. The labels are blind to model and verdict, but not checked by a second person.
- Small local models on both sides. Results for hosted models may differ.
- The judge's instructions were tuned on this corpus. The probes and the final fresh sheet limit, but do not remove, that bias.
