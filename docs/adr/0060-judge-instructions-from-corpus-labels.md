# ADR 0060: Rewrite the judge's instructions from the corpus labels, drop cases with a wrong reference, and test on fresh labels

- **Status:** Accepted
- **Date:** 2026-10-29

## Context

On 200 blind labels from the corpus run ([ADR 0059](0059-run-the-corpus-end-to-end.md)), Gemma 3 12B with ADR 0056's instructions was right on 90% of its PASSes but only 57% of its FAILs. The labeller sorted the 43 wrong FAILs (41 rows):

| What the answer did | Rows |
|---|---|
| Added reasonable content to an open-ended prompt (descriptions, summaries, pitches, question lists, replies) | ~26 |
| Was correct where the reference was wrong (dates, a `v` prefix the reference missed) | 6 |
| Made another valid choice (a `CharField` where the reference used `EmailField`, other wording) | 5 |
| Added content the prompt asked for (a git command the PR template requires) | 2 |
| Other | 3 |

So the rule added in ADR 0056 ("FAIL if the answer states any fact that isn't in the source text or the reference") fits answers that must stick to a source, such as support replies, but punishes answers to prompts that ask the model to create something. About a third of the wrong FAILs have a second cause that the rule does not explain: **the judge treats the reference as the truth.**

The judge also passed 10 answers the labeller failed, mostly misread facts in summaries and analyses: "no tasks are pending" when one is, the wrong peer output, a README said to list 10 commands when it does not.

Four prompts had a **wrong reference** (the labeller's notes say "reference also wrong"): the second Wednesdays of 2026 (wrong dates), the 2020 World Series venue (every game was at Globe Life Field), an UNFOMO news digest whose articles were never filled in (an empty `articles_json`, so every answer invents the news), and a skill reflection whose own example fails a `v` prefix that the reference passes. Six of the judge's wrong FAILs and six of its wrong PASSes are on these four.

## Decision

1. **New judge instructions.** Three changes:
   - *The reference is one acceptable answer, not the only one:* pass a candidate that makes another valid choice, or that is more correct than the reference.
   - *Open-ended prompts:* if the prompt asks for something new (a description, a plan, a pitch, questions, code), adding content is the job, so an answer is not failed for details the prompt does not contain.
   - *Source-based prompts:* if the prompt gives source text to work from (a document, a thread, a summary, data), fail an answer that states facts not in that source, or that **misstates what it says** (who did what, what is done or still pending, numbers and names).
2. **Drop the cases with a wrong reference** (`research.corpus.run --drop-case`). Judging against a reference assumes the reference is right; when it is not, neither verdict means anything. The four prompts are five cases, because the calendar example is in two copies of one app's docs:
   - `app-13/docs/docs/API-Reference/python-examples/api-openai-responses/additional-configuration-for-openai-client-libraries.py:16#1` (calendar)
   - `app-13/docs/versioned_docs/version-1.9.0/API-Reference/python-examples/api-openai-responses/additional-configuration-for-openai-client-libraries.py:16#1` (calendar, older docs copy)
   - `app-14/src/agenthatch/skill/reflection.py:202#1` (skill reflection)
   - `app-28/processing/digest.py:72#1` (UNFOMO digest)
   - `app-29/openai_demo.py:13#1` (World Series)
3. **Re-judge the same answers** into a new folder (`--out research/data/corpus/run-v2`). The model answers come from the cache, so only the judge is asked again.
4. **The 200 corpus labels are now a development set.** They shaped this change, so they are used only as a check (`modelbump judge agreement --report`, no correction). The number to report comes from a **fresh blind sheet** drawn from the new run that leaves out every answer already labelled (`--exclude-key`).
5. The demo probes ([ADR 0058](0058-judge-probes.md)) are judged again with the new instructions, to check that the fix does not lose the mistakes the old rule caught.

## Alternatives considered

- **Removing the invented-facts rule:** fixes the creative prompts, but the demo pilot showed that without it the judge passes invented support facts (ADR 0056).
- **Asking a model to classify each prompt as creative or source-based first:** an extra call per case, and its own error rate. The judge already reads the prompt, so it is told the difference instead.
- **Several references:** helps with valid alternatives, but not with a reference that is wrong, and it makes the judge's prompt much longer.
- **Keeping the four cases:** honest about the data, but each of their verdicts would measure the reference, not the judge or the models.

## Consequences

- Every free-text answer is judged again (a new cache key), once.
- Two sets of corpus labels: the first 200 (development) and the fresh sheet (test). The paper reports the test numbers, and the development numbers as the reason for the change.
- A judge guided by one reference cannot catch a wrong reference. Dropping cases by hand does not scale, so the paper reports it as a limit: 5 of the 75 corpus cases (4 prompts) had a wrong reference.

## Results (29 October 2026)

The re-judged run (`run-v2`, 70 cases, 446 judge requests, every model answer from the cache) gave **3 REGRESSED** (app-07 text, app-19 and app-33 JSON), 1 IMPROVED and 66 INCONCLUSIVE. Of the 5 text regressions in ADR 0059, only app-07's is left. The judge now passes 516 of 560 free-text answers (92%).

| Check | Agreed |
|---|---|
| Development labels (the first 200, check only): judge PASS | 82% (123 of 150) |
| Development labels: judge FAIL | 67% (8 of 12) |
| **Fresh sheet (100 answers, test): judge PASS** | **79% (54 of 68), 95% CI 68-88%** |
| **Fresh sheet: judge FAIL** | **69% (22 of 32), 50-83%** |

On the fresh sheet, agreement weighted to the report is 79% (kappa 0.47). Corrected, Qwen 2.5 passes 75% (63-85%) and Qwen 3 76% (64-85%), so on these apps the two models are about the same.

The **probes** ([ADR 0058](0058-judge-probes.md)) show the price. Re-judged with these instructions and checked against the same hand labels, the judge caught **9 of 24** broken answers, down from 22: changed source 0 of 7 (was 7), hedged invention 2 of 8 (was 8), flipped meaning still 6 of 6, missing fact still 1 of 3. Paraphrases still pass 8 of 8. The demo's support prompt gives no source text, so the judge now treats a support reply as "something new" and lets invented links and details through. One instruction set traded one kind of mistake for the other, so [ADR 0061](0061-no-made-up-specifics.md) adds one narrow rule back.
