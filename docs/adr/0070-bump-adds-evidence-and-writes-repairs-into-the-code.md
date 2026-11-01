# ADR 0070: The bump takes the test and repair results as files, adds them to `.modelbump/`, and writes a repair into the code only where its place is certain

- **Status:** Accepted
- **Date:** 2026-11-01

## Context

A bump pull request should not just say "changed the model ID". It should carry the evidence that the new model still does the app's job. Where the new model did regress, it should also carry the prompt fix that was shown to work. The pieces exist already:

- `modelbump suite` writes the test cases;
- `modelbump test --format json` writes every answer and verdict;
- `modelbump repair run` accepts a patch only when fresh answers show it is safe ([ADR 0064](0064-repair-loop-screen-then-confirm.md)).

Two questions are open:

1. **Should `bump` call the models itself?** The models to test with are the developer's choice. They are often stand-ins: the old model may already be shut down, and this project uses free local models only. Running them also takes minutes to hours.
2. **How does a patch get into the code?** A patch edits the messages a call sends ([ADR 0062](0062-prompt-patches.md)). In the source, those messages are string literals, often in another file, sometimes built at runtime with `.format()` or f-strings. A wrong edit to a prompt would ship a prompt that was never tested.

## Decision

1. **The bump calls no model.** It takes the files the other commands wrote:
   - `--suite FILE`
   - `--report FILE` (from `test --format json`)
   - either `--repairs FILE` with `--proposals DIR` (from `repair run` and `repair propose`), or `--patch FILE` for a fix written by hand and checked with `test --patch`.

   Each file is checked before anything is planned. A report or a patch needs its suite, and every patch must fit the suite.
2. **The evidence goes into `.modelbump/`, copied byte for byte:**
   - `suite.json`;
   - `test.json`;
   - `repair.json`, when there was a repair report;
   - `repairs.json`, the accepted patches as one patch file, so `modelbump test .modelbump/suite.json --patch .modelbump/repairs.json` reproduces the run.

   The dry run lists these files without showing their contents. A file that is already there with the same text is left alone. The scanner skips `.modelbump/`, since the evidence names the old model on purpose and the next bump must not rewrite it.
3. **A repair is written into Python source only where its place is certain.** Literals inside f-strings and bytes are never candidates.
   - **An edit:** its `find` text must occur exactly once across all plain string literals in the app's Python files (test files are not searched). Only that literal changes.
   - **An added system instruction:** the call's whole system message, after the patch's edits, must be exactly one literal. The instruction is appended as the test appended it: `text.rstrip() + "\n\n" + added`.
   - **The new literal** keeps its quote style when that is safe, and is otherwise written as a plain escaped string.
   - **A last check** parses the file again and confirms that the new literal holds the tested text.
4. **Everything else is "apply by hand", with the reason.** Examples: a system message built at runtime, text found in two places, or a call with no system message. The patch is still in `.modelbump/repairs.json`, so nothing tested is lost.

## Alternatives considered

- **`bump` runs suite, test and repair itself:** one command, but it would hide model choices and hours of compute behind a refactoring tool, and a failed run would leave a half-done bump. The scheduled Action in a later step chains the commands.
- **Ship the patch file only, with the app loading it at runtime:** no source edit is needed, but the app gets a new runtime dependency on ModelBump and the prompt in the code is no longer the prompt that runs.
- **Edit the template source by mapping slots back to code:** possible for some `.format()` and f-string prompts, but each kind needs its own mapping, and a mistake ships an untested prompt. Leaving these to a person is safer.
- **Search test files for prompt text too:** tests often hold the inputs, and a match there is never the prompt the app sends.

## Consequences

- `modelbump bump ... --suite --report --patch` gives a branch with the model change, the tested prompt fix and the evidence, ready for the pull request step.
- For the demo app, a fix to a literal system prompt is written into the code. A fix to the support classifier is left by hand, because its system prompt is built with `textwrap.dedent(...).format(...)`.
- The test report holds every answer the models gave. Before reports are published in pull requests, a later step reviews them for secrets and personal data.
