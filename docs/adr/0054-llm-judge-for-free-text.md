# ADR 0054: Judge free-text answers with a third local model, against an old reference answer

- **Status:** Accepted
- **Date:** 2026-10-28

## Context

On the demo suite, Qwen 2.5 → Qwen 3 came out EQUIVALENT on all 9 cases (50 runs each, run on a MacBook Air M5). For the 4 free-text cases that says little, because the property checks of [ADR 0052](0052-oracles-by-output-type.md) only see length, format, refusals and stated limits. A summary that is wrong but the right length passes them. The master plan asks for "properties + LLM-judge" on free text, with the judge's agreement with people measured later. The constraints:

- **Free and local.** The judge runs on the same laptop as the two models (ADR 0036).
- **Not one of the two models.** A model judging its own answers tends to favour them.
- **The same treatment for both models.** The comparison is old against new, so any bias the judge has must hit both alike.
- **Cheap.** A judge call per answer doubles the requests on text cases, so each call must be short and cached.

## Decision

- **A third model judges, from another family:** `ollama/llama3.1:8b` by default (`--judge` picks another, `--no-judge` turns it off). It is pinned to its Ollama digest like the compared models ([ADR 0039](0039-pin-local-models-to-their-digest.md)).
- **Reference-guided, one answer at a time** (`src/modelbump/oracles/judge.py`). The judge sees the app's prompt (every message, with its role), the first reference answer from the old model (sample 0, the same for every answer of that case), and the answer to check. It never sees which model wrote the answer. It replies with one word: PASS means the answer does what the prompt asks at least as well as the reference (correct, answers the request, follows the prompt's instructions), and FAIL means it does not. Temperature 0, seed 0, at most 8 tokens. Each call is cached, so an answer seen before costs nothing.
- **Only free-text cases are judged.** JSON and label cases already have exact checks.
- **The judge sets the text score.** With a judge, a text answer scores 1 (PASS) or 0 (FAIL). An empty answer or a refusal (when the old model did not refuse) scores 0 whatever the judge says. The other property checks stay in the report, to explain a FAIL, but no longer change the score. A reply that is neither PASS nor FAIL keeps the property score and is listed as `judge: no clear verdict`.
- **The judge's verdict is in the JSON report** (`"judge": "PASS" | "FAIL" | "unclear"`) for every answer, so the next step can sample answers for hand labels and measure agreement.

## Alternatives considered

- **Pairwise (A or B better?):** closer to how people compare, but it has a known order bias, needs both orders to cancel it (twice the calls), and gives no per-answer score for the stats engine.
- **A 1-10 rating:** finer, but small judges spread ratings unevenly and differently per prompt, and the number would need its own calibration per case. A binary verdict is what the hand labels will check.
- **Qwen 2.5 or Qwen 3 as the judge:** no extra download, but each is one of the two models compared.
- **A larger judge (Gemma 3 12B and up):** probably better, but slower on a 16 GB laptop for the hundreds of calls one run needs. The judge is a setting, and the calibration will show whether the default is good enough.
- **Judging without a reference:** the judge would grade against its own idea of a good answer, not against what the app accepted, which is the question a migration asks.

## Consequences

- A free-text case can now be REGRESSED because answers got worse, not only because they got longer or empty.
- A run costs one judge call per compared text answer: 100 per text case at 50 runs.
- The judge can be wrong. Until its agreement with hand labels is measured (next step), a verdict on a text case rests on an unmeasured judge, and reports say which judge was used.
- The judge sees the reference first and the answer second for every answer, so an order bias affects old and new answers alike rather than one model.
