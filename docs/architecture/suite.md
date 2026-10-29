# Suites and `modelbump test`

A suite is the list of test cases a comparison runs: each case's final messages, its [oracle](oracles.md), and where its inputs came from ([ADR 0053](../adr/0053-suite-file-and-modelbump-test.md)). It is a JSON file, so a team can read it, edit it and commit it.

A case's inputs come from the app's own code, from a generator model (`--generate`), or from nowhere: a call whose prompt is all written text, with no slots, is one case as it is (source `fixed prompt in the code`).

```console
$ modelbump suite tests/fixtures/prompt-demo --generate 2 --output demo-suite.json
Wrote 9 test cases for 4 LLM calls to demo-suite.json.
  left out support.py:39: no complete test case
```

`modelbump test` runs the suite on two models and decides each case with the [stats engine](stats.md):

```console
$ modelbump test demo-suite.json --from ollama/qwen2.5:7b --to ollama/qwen3:8b --to-think none
Compared ollama/qwen2.5:7b -> ollama/qwen3:8b on 9 test cases: fixed k=50 + BH (q 0.05, margin 0.10), 3 reference answers per case, free text judged by ollama/gemma3:12b.
REGRESSED    support.py:24#1  label  old 1.00 -> new 0.12  (50 runs)
             new model failed: same label as before (bug) (44/50)
...
Result: 1 regressed, 2 inconclusive, 6 equivalent, 0 improved.
```

The lines above only show the format; the verdicts depend on the models.

## How a case is run

1. The old model answers `--reference` times (default 3). These answers build the oracle's reference and are never scored.
2. Both models answer the same requests, with the sample number as the seed, `--runs` times each (default 50).
3. Each answer is scored in [0, 1] by the case's oracle. A free-text answer also goes to the judge, which decides its score.
4. **Fixed k + BH** (up to 100 runs) or **sequential + e-BH** (above that, or `--method sequential`) gives the verdict.

Every answer is cached, so running the same command again costs nothing. The exit code is 1 when a case REGRESSED or could not be run, and 2 when the suite or a model cannot be used.

## Options

| Option | Default | What it does |
|--------|---------|--------------|
| `--from`, `--to` | (required) | The old and the new model, as `endpoint/model`. They replace the model the app names. |
| `--runs` | 50 | Answers per model per case (the most, for sequential). |
| `--reference` | 3 | Old answers per case that set the reference. |
| `--method` | `auto` | `fixed`, `sequential`, or `auto` (fixed up to 100 runs). |
| `--from-think`, `--to-think` | none set | Reasoning effort for a thinking model, e.g. `--to-think none` for Qwen 3. |
| `--judge` | `ollama/gemma3:12b` | The model that judges free-text answers ([ADR 0054](../adr/0054-llm-judge-for-free-text.md)). |
| `--no-judge` | off | Check free text with property checks only. |
| `--temperature` | 0.7 | Sampling temperature for both models. |
| `--max-tokens` | 400 | Longest answer. |
| `--budget-requests` | no limit | Stop after this many requests; run again with a higher limit to continue from the cache. |
| `--format`, `--output` | text, screen | `json` has every answer, score and failed check. |
