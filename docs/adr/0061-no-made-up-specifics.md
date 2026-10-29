# ADR 0061: Fail made-up specifics about the app, and stop tuning the judge

- **Status:** Accepted
- **Date:** 2026-10-29

## Context

Two versions of the judge's instructions each got half the job right:

| | Corpus labels | Probes caught |
|---|---|---|
| v1, ADR 0056 ("fail any fact not in the prompt or reference") | too strict: FAILs right 57% (dev) | 22 of 24 |
| v2, ADR 0060 (reference is one answer; open-ended prompts may add content) | 79% agreement on fresh labels | 9 of 24 |

v2 lost the probes where a support reply sends the user to a page that does not exist, or invents a reset method in vague words. Those are the mistakes users of an LLM app fear most, and they are about **the app's own world**: its pages, contacts, policies and steps. The creative content that v1 wrongly failed (descriptions, pitches, plans, question lists) is not.

## Decision

- **v3 = v2 plus one rule:** *never accept made-up specifics about the app, a company or a user: links, page or section names, contact details, policies, prices, dates, or account and reset steps. FAIL an answer that states one that neither the prompt nor the reference gives, even if it is written vaguely or as one of several options.*
- **The same checks as ADR 0060**, re-run with v3:
  1. re-judge the corpus into `run-v3` (cached answers; the same 5 cases dropped);
  2. the probes, against the labels already given (free);
  3. both labelled corpus sheets as development checks (`--report`);
  4. one **fresh blind sheet of 100** that leaves out every answer labelled so far (both keys with `--exclude-key`), as the test.
- **The judge ModelBump ships** is the one that does best on the development checks and the probes together. The paper reports its fresh-sheet numbers, plus every earlier version's numbers to show the trade-off.
- **This is the last change to the judge's instructions in Phase 5.** Each round spends fresh labels and tunes the judge more to this corpus. Better judging (several references, checking claims one by one, a judge per task type) is later work.

## Alternatives considered

- **Release v2 as it is:** the higher corpus agreement, but it misses invented support details, which is what a regression test is for.
- **Go back to v1:** it catches the probes, but almost half of its FAILs are good answers, so its REGRESSED verdicts on free text cannot be trusted.
- **A judge prompt chosen per call site (support, creative, source-based):** probably better, but it needs a classifier and its own labels.

## Consequences

- The paper can show the trade-off with three judge versions on the same answers, labels and probes.
- The final fresh sheet is the third set of labels on the corpus. After it, about 200 judged answers remain unlabelled.

## Results (29 October 2026)

v3 did best on every check, so it is the judge ModelBump ships.

| | Probes caught | 1st corpus sheet (dev) | 2nd corpus sheet (dev) |
|---|---|---|---|
| v1 (ADR 0056) | 22 of 24 | 73%, kappa 0.47 | |
| v2 (ADR 0060) | 9 of 24 | 81%, kappa 0.26 | 79%, kappa 0.47 |
| **v3** | **22 of 24** | **84%, kappa 0.53** | **88%, kappa 0.65** |

(For v1 and v2, a sheet's numbers are its own fresh measurement where it was drawn from that judge's run, and a check otherwise.) Paraphrases passed 8 of 8 under every version.

**The test: a third fresh sheet** (100 answers never labelled before, drawn from `run-v3`, 261 judge PASSes and 37 FAILs left to draw from):

| | Agreed | 95% CI |
|---|---|---|
| Judge said PASS | 87% (55 of 63) | 76-94% |
| Judge said FAIL | 68% (25 of 37) | 50-81% |

Agreement weighted to the report: **83%**, kappa 0.56. Corrected to the labels, Qwen 2.5 and Qwen 3 both pass **76%** (64-85%) of free-text answers, against the judge's own 80% and 79%. The corpus verdicts with v3: 4 REGRESSED (app-05 and app-07 free text, app-19 and app-33 JSON), 2 IMPROVED, 64 INCONCLUSIVE.

The judge is still more often wrong when it fails an answer (about 1 in 3) than when it passes one (about 1 in 8). So a REGRESSED verdict on free text deserves a look at the failed answers, which `modelbump test --format json` lists with each verdict.
