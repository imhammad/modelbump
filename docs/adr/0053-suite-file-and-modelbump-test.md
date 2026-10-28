# ADR 0053: Write the suite to a file, then run it on both models with `modelbump test`

- **Status:** Accepted
- **Date:** 2026-10-28

## Context

Phase 5 has every piece apart: LLM calls and their prompts ([ADRs 0048](0048-find-llm-calls-and-prompt-templates.md)-[0049](0049-follow-prompts-across-files-classes-and-functions.md)), test inputs from the app and from a local model ([0050](0050-test-inputs-from-the-apps-own-callers.md)-[0051](0051-generated-test-inputs-from-a-local-model.md)), oracles ([0052](0052-oracles-by-output-type.md)), and the stats engine (Phase 4). The Definition of Done asks for `modelbump test --from X --to Y` end to end. Three questions:

- **What does a run test?** Inputs written by a model change when the writer or the code changes. A comparison must say exactly which cases it ran.
- **Which answers build the reference?** If an old answer is both the reference and one of the scored answers, the old model passes its own checks by construction (ADR 0052).
- **Fixed or sequential?** ADR 0047 says the comparison command offers both, chosen by budget.

## Decision

- **Two commands.** `modelbump suite PATH` writes a suite file (`modelbump-suite.json` by default, `--output`), with the same `--generate`, `--model`, `--exclude` and `--skip-tests` as `modelbump cases`. `modelbump test SUITE --from OLD --to NEW` runs it. The file is plain JSON (version 1). Each case has an id (`support.py:24#2`), its final messages, its oracle and where its inputs came from. A team can read the file, edit it, commit it, and rerun the same suite later. Calls with no complete case, and tool calls, are listed under `left_out` with the reason.
- **`--from` and `--to` replace the app's model.** The app may name `gpt-4o-mini`. The test sends its prompts to the two models given, so a pair of free local models (Qwen 2.5 → Qwen 3) can stand in for a paid pair. The app's model stays in the file as `app_model`.
- **Reference answers are separate.** For each case the old model first answers `--reference` times (default 3, samples 0-2). Those answers build the reference and are not scored. Then both models answer the same requests with samples 3 onwards, where the sample number is also the seed. Every answer is cached, so a second run costs nothing.
- **Method by ADR 0047.** `--method auto` (default) uses **fixed k + BH** for up to 100 `--runs`, and **sequential + e-BH** above that. Either can be forced. The default `--runs` is 50, as in the Phase 4 study. With 10 runs even identical models stay INCONCLUSIVE at the 0.10 margin, and equivalence first becomes provable at about 40.
  - **Fixed:** each case gets `runs` answers per model. Fractional scores are rounded to pass counts. REGRESSED needs Benjamini-Hochberg across the suite on the one-sided regression p-values. EQUIVALENT and IMPROVED come from each case's own interval (ADR 0041).
  - **Sequential:** answers come one round (one old, one new) at a time. A case stops when its verdict is clear, and e-BH decides the suite (ADRs 0042-0043).
- **Defaults for answers:** temperature 0.7 (repeated answers must be able to differ), at most 400 tokens, and `--from-think` / `--to-think` for thinking models (`--to-think none` for Qwen 3, as in ADR 0046).
- **Report:** one line per case, regressions first, with old and new mean scores and the checks the new model failed most. `--format json` adds every answer, its score and its failed checks, for hand checks and the judge step. The exit code is 1 when a case REGRESSED or could not be run, so CI can fail on it, and 2 when the suite or a model cannot be used at all.
- **Failures stay local.** A case whose request fails (or that runs out of `--budget-requests`) is reported as NOT RUN with the error. The other cases still run and are decided among themselves.

## Alternatives considered

- **One command from code to verdict:** shorter, but the cases would be rebuilt (and maybe regenerated) on every run, so two runs could test different things without anyone seeing it.
- **Scoring old answers against a reference built from the same answers:** simpler and cheaper by three requests per case, but biased towards the old model (ADR 0052).
- **The app's own temperature and token limit:** more faithful, but the finder does not read them yet, and temperature 0 would make repeated answers identical, which defeats the stats engine.
- **A fixed `--runs 10` default:** about five times faster, but it can almost never say EQUIVALENT, so a report would be nearly all INCONCLUSIVE.

## Consequences

- `modelbump test --from X --to Y` works end to end on a laptop, with free local models: the Phase 5 DoD apart from the corpus and the judge.
- A demo suite of 9 cases with 50 runs is about 900 answers, which takes minutes to tens of minutes on a laptop. A quick `--runs 5` check of the pipeline is cheap, but its verdicts are INCONCLUSIVE.
- Free-text cases are checked only by properties until the judge step. A text case that is EQUIVALENT may still have lost quality.
