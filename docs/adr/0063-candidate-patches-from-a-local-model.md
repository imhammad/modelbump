# ADR 0063: Let a local model write candidate patches from the failing answers, and check each one before keeping it

- **Status:** Accepted
- **Date:** 2026-10-30

## Context

[ADR 0062](0062-prompt-patches.md) made a prompt fix a patch file that can be shown and tested. The repair loop needs candidates to test, and writing them by hand does not scale to a corpus. Three questions:

- **Who writes them?** Free options only: a local model through Ollama, or a free cloud tier.
- **What does the writer see?** A model that only sees the prompt has to guess what went wrong. The test report already says it: the old model's reference answer, the new model's answers, and the checks they failed.
- **What if a candidate is malformed, or edits a test input?** A model's answer is not trusted. Every candidate must pass the same checks as a hand-written patch.

## Decision

1. **`modelbump repair propose SUITE REPORT`** reads a suite and a `modelbump test --format json` report of it, run **without** a patch (a report from a patched run is refused). For each call with at least one REGRESSED case it asks a proposer model for `--candidates` answers (default 5), with samples 0, 1, 2, ... as seeds and temperature 0.8, so the answers differ and are cached.
2. **What the proposer sees:** the app's prompt (from the call's first REGRESSED case), the old model's reference answer, and up to 3 distinct failing new answers, each with the checks it failed (and "the judge failed it" for a judge FAIL). It is told to keep the task the same, not to give the answer away, and not to write anything specific to this input. Long messages and answers are cut (4,000 and 800 characters).
3. **What it answers:** one JSON object with `add_system`, `edits` and `why`. Prose or a code fence around it is allowed.
4. **Edits only where they can be checked.** When a call has one test case, the "exactly once in every case" rule cannot tell prompt text from input (ADR 0062). For such calls the proposer is asked for `add_system` only, and any edits it still writes are dropped. A call with two or more cases may get edits.
5. **Every answer is checked before it is kept**, and a refused answer is listed with its reason: no readable JSON, a patch that changes nothing, an edit that does not match exactly once in every case, a failed request, or the same patch as an earlier sample.
6. **Output:** one ordinary patch file per candidate (`support.py-24.00.json`, the number is the sample) in `--output-dir` (default `modelbump-proposals`), with the reason in its `note`, and `proposals.json` listing every call, its REGRESSED cases, its candidates with their `why`, and what was refused. A rerun replaces the earlier candidate files of the same call.
7. **Default proposer: `ollama/gemma3:12b`.** It is the strongest model that fits next to the others on a 16 GB laptop, it is already pulled as the judge, and it is neither the old nor the new model, so the model under test does not write its own fix. `--model` takes any other `endpoint/model`, and a free cloud tier prints the same privacy note as `modelbump test`.

Proposing says nothing about whether a candidate works. Only the repair loop decides that, on fresh answers (next step).

## Alternatives considered

- **The new model proposes its own fix:** it knows its own habits, but it can be a small model, and it is the model being tested. It can still be chosen with `--model`.
- **A fixed list of fixes** ("answer only with the label", "reply in JSON only"): cheap and predictable, but it only covers failures someone thought of in advance. It stays possible as a hand-written patch, and the naive baselines come in a later step.
- **One answer with several candidates:** fewer requests, but the candidates in one answer tend to be variations of one idea, and one bad JSON loses all of them. One sample per candidate also makes each one reproducible from its sample number.
- **Showing every failing answer:** more evidence, but long prompts would not fit a local model's context, and the same failure repeated adds nothing. Distinct answers, at most 3, are shown.

## Consequences

- From a test report to patch files is one command, with no paid model.
- With the corpus, where each call has one case (ADR 0059), every candidate is `add_system` only until the repair loop gives calls more cases.
- The judge (Gemma 3 12B) and the default proposer are the same model. The judge only ever reads the app's own prompt (ADR 0062), but a proposer could still learn to write instructions whose answers that judge likes. The RQ3 experiment reports a run with another proposer as a check.
