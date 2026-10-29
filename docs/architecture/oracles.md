# Oracles

An oracle decides whether an answer still does the job. In a migration, the old model's answers are the reference: the app worked with them ([ADR 0052](../adr/0052-oracles-by-output-type.md)). Each call gets an oracle by the kind of answer it expects, and each answer gets a score in [0, 1] for the [stats engine](stats.md).

## Picking the kind

| Kind | Picked when | Checks |
|------|-------------|--------|
| `tools` | the call passes `tools=` or `functions=` | not scored yet |
| `json` | the call's settings ask for JSON, or the prompt says "JSON" | valid JSON, same type and keys as before, values the old model always gave are kept |
| `label` | the prompt lists the allowed answers ("one label: bug, feature, question", "yes or no") | one of the labels, same label as before |
| `text` | anything else | not empty, not a refusal, length like before, keeps list and code format, keeps a word or sentence limit in the prompt |

In `modelbump test`, an LLM judge also reads each free-text answer and decides its score ([ADR 0054](../adr/0054-llm-judge-for-free-text.md)). See [Judging free text](#judging-free-text) below.

```console
$ modelbump oracles tests/fixtures/prompt-demo
bot.py:14  openai_chat  text
  why: free text (no JSON or label list in the prompt)
  checks: not empty, not a refusal, length like before, keeps list and code format, keeps a word or sentence limit in the prompt
extract.py:9  gemini  json
  why: the prompt says "JSON"
  checks: valid JSON, same type and keys as before, values the old model always gave are kept
support.py:24  openai_chat  label
  why: the prompt lists labels: bug, feature, question
  checks: one of the labels, same label as before
...
Picked oracles for 5 LLM calls: 1 json, 1 label, 3 text.
```

## Scoring

```python
from modelbump.oracles import build_reference, choose_oracle, score

# site is a CallSite from modelbump.synth; old_answers are a few old-model answers to one case.
choice = choose_oracle(site)
reference = build_reference(choice, old_answers)
result = score(reference, new_answer)
result.value  # 0.83
result.failed  # ("has total",)
```

The answers that build the reference are kept apart from the answers that are compared, so the old model is not graded on its own reference. [`modelbump test`](suite.md) does this for every case.

## Judging free text

Property checks cannot tell a wrong summary from a right one. So `modelbump test` sends each free-text answer to a third model, `ollama/gemma3:12b` by default ([ADR 0056](../adr/0056-bigger-judge-and-no-invented-facts.md)) (`--judge`, or `--no-judge` to turn it off). The judge sees the app's prompt, the old model's first reference answer and the answer to check, but not which model wrote it. Its instructions treat the reference as one acceptable answer, not the only one; let answers to open-ended prompts add content; and fail answers that invent or misstate facts when the prompt gives source text ([ADR 0060](../adr/0060-judge-instructions-from-corpus-labels.md)). It replies PASS or FAIL, and that sets the score (1 or 0). An empty answer or a refusal scores 0 whatever the judge says. The property checks stay in the report to explain a FAIL.

## Limits (for now)

- The judge's agreement with people is measured with `modelbump judge` (below). The 200 labels for the paper come from the benchmark corpus ([ADR 0057](../adr/0057-benchmark-corpus-from-migration-snapshots.md)).
- Tool calls are not scored.
- A label list filled in at run time (`one of: {labels}`) is not read, so that call falls back to text.

## Checking the judge

How far the judge can be trusted is measured against a person's labels ([ADR 0055](../adr/0055-check-the-judge-against-hand-labels.md)):

```console
$ modelbump test demo-suite.json --from ollama/qwen2.5:7b --to ollama/qwen3:8b --to-think none --format json --output report.json
$ modelbump judge sheet report.json --size 40 --output judge-sheet.csv --key judge-key.json
Wrote 40 rows (40 answers: 20 judged PASS, 20 FAIL) to judge-sheet.csv, and the key to judge-key.json.
```

The sheet shows the prompt, the reference answer and the answer, with no model name and no judge verdict. Fill in `your_label` with PASS or FAIL without opening the key, then:

```console
$ modelbump judge agreement judge-sheet.csv judge-key.json
Labelled 40 answers.
When the judge said PASS, you agreed 95% (19/20, 95% CI ...).
When the judge said FAIL, you agreed 60% (12/20, 95% CI ...).
...
ollama/qwen3:8b: judge pass rate 78%, corrected 84% (range ...)
```

To test a change to the judge without reusing labels it was tuned on, compare old labels with the re-judged run (`--report NEW_REPORT`, a check only), then draw a fresh sheet that leaves out answers already labelled (`modelbump judge sheet NEW_REPORT --exclude-key OLD_KEY`). See [ADR 0056](../adr/0056-bigger-judge-and-no-invented-facts.md).

The numbers above only show the format. The corrected pass rate assumes that, given its verdict, the judge is as often wrong on one model's answers as on the other's. The per-model lines show whether that holds.

## Judge probes

Hand labels show how often the judge is right on the answers models happen to give, but each kind of mistake turns up only a few times. Probes test the kinds directly ([ADR 0058](../adr/0058-judge-probes.md)). A local model (`ollama/qwen2.5:7b`, `--breaker`) edits each free-text case's reference answer in one known way, and the judge grades the edit against the unchanged reference:

| Kind | The edit | A good judge says |
|---|---|---|
| `changed_source` | Word for word, except where it sends the reader (or one name or number) | FAIL |
| `flipped_meaning` | Mostly the same words, wrong meaning | FAIL |
| `missing_fact` | The most important fact left out | FAIL |
| `hedged_invention` | One invented detail, written vaguely or as an option | FAIL |
| `paraphrase` | Other words, same meaning (a control) | PASS |

```console
$ modelbump judge probes report.json --output probe-sheet.csv --key probe-key.json
Wrote 40 probes for 4 free-text cases to probe-sheet.csv, and the key to probe-key.json.
$ modelbump judge probe-check probe-sheet.csv probe-key.json
changed_source: 8 labelled, 8 really wrong by you; judge failed 5/8 (...)
...
All broken kinds: judge caught ...
```

The breaker can get an edit wrong too, so you label every probe blind, like the judge sheet, and only probes you confirm count. The numbers above only show the format.
