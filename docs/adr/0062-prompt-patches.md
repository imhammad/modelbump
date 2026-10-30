# ADR 0062: Describe a prompt fix as a patch to one LLM call, and test it like a model change

- **Status:** Accepted
- **Date:** 2026-10-30

## Context

Phase 6 repairs prompts that regress after a model change: it proposes edits, tests them, and keeps only edits that fix the regressions without breaking anything else. Before any edit can be proposed or searched for, three questions need an answer:

- **What is an edit?** A suite case holds final messages: the prompt the developer wrote with the inputs already filled in ([ADR 0053](0053-suite-file-and-modelbump-test.md)). A fix must change the prompt, never one case's inputs, or it fixes the test instead of the app.
- **What does an edit apply to?** The same prompt serves every case of one call, so a fix to that prompt changes all of them.
- **How is a fixed prompt judged?** If the patched prompt also changed the reference or the judge's view of the task, an edit such as "answer `bug` to everything" or "keep it to one word" could pass by making the task easier.

## Decision

1. **A patch belongs to one LLM call** (`support.py:24`) and applies to every test case of that call. It has two parts, both optional but not both empty:
   - **edits:** `find` and `replace` pairs, applied in order. Each `find` must occur **exactly once** in every case's messages, or the patch is refused. With two or more cases, text that is in every case is the developer's prompt, not an input, so inputs cannot be edited by accident.
   - **`add_system`:** text added at the end of the system message, or sent as a new first system message when the call has none. Most published prompt fixes for a new model are an added instruction, and this needs no `find`.
2. **A patch file** is plain JSON (`version: 1`, a list of patches, each with `call`, `edits`, `add_system` and a `note` that no model sees). People can write one by hand; later steps write them from proposals. Two patches for one call, or a patch for a call with no case in the suite, are errors.
3. **The patch changes what the new model is sent, and nothing else.** `modelbump test SUITE --from OLD --to NEW --patch FILE` sends the new model the patched messages. The old model, its reference answers, the oracle and the judge all keep the app's own prompt. A patched prompt is therefore held to the original task, and a patch is tested with the same stats as a model change (fixed k + BH or sequential + e-BH).
4. **`modelbump repair show SUITE FILE`** prints a diff of every case the patch changes, with no model calls, and names each call that has only one case: there, an edit could still touch an input, so the diff must be read.
5. Reports mark patched cases (`[patched]` in text; `patched` and `patched_messages` in JSON).

## Alternatives considered

- **Edit the source files directly:** what a developer finally wants, and Phase 7 does it. But the suite holds final messages, not source spans, and a prompt is often built from several strings in several files ([ADR 0049](0049-follow-prompts-across-files-classes-and-functions.md)). Testing first on the messages keeps repair separate from rewriting code. A `find` taken from the prompt's own text can be found again in the source later.
- **Replace the whole prompt:** simpler to generate, but it hides what changed, and a model asked to rewrite a whole prompt can drop instructions or change the inputs.
- **A patch per case:** could fit each case better, but the app has one prompt per call. A fix that only works with one input is not a fix to the app.
- **Judge a patched case against the patched prompt:** the judge would then grade the new task, and an edit that makes the task easier would pass.

## Consequences

- A developer can test a hand-written fix today, with the same guarantees as `modelbump test`.
- The search in later Phase 6 steps only has to produce patch files; checking and testing them is done.
- A call with a single test case cannot be checked for input edits automatically. `repair show` points it out, and the repair loop in a later step adds generated cases or limits itself to `add_system` there.
- Patched answers are new requests (new messages), so they are cached apart from the unpatched ones and cost new answers.
