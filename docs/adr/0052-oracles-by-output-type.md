# ADR 0052: Check answers against the old model's answers, with an oracle picked by output type

- **Status:** Accepted
- **Date:** 2026-10-28

## Context

[ADRs 0048-0051](0048-find-llm-calls-and-prompt-templates.md) give each LLM call a set of test cases. The stats engine ([ADR 0045](0045-scores-and-stopping-cases-that-look-fine.md)) needs a score in [0, 1] for every answer. So something must decide whether an answer is good. That is the oracle. Three things shape it:

- **A migration has no answer key.** The app worked with the old model. What the app needs from the new one is the same behaviour, not a "right" answer someone wrote down. So the old model's answers are the reference.
- **Calls want different things.** The master plan says: JSON and tool calls get schema and field checks, classification gets exact match, free text gets property checks plus an LLM judge.
- **The pick must be explainable.** A developer reading a report must see why a call was checked the way it was.

## Decision

- **Pick the kind from the call, in a fixed order** (`src/modelbump/oracles/choose.py`):
  1. `tools=` or `functions=` on the call: **tools**. These are listed but not scored yet, because the runner does not send tool definitions.
  2. The call's settings ask for JSON (`response_format` with "json", `.parse(response_format=Model)`, the Responses API's `text` format, Ollama `format="json"`, Gemini `response_mime_type="application/json"` or `response_schema`): **json**. The finder now records this as `CallSite.output`, which is also in the `modelbump prompts` JSON.
  3. The prompt's written text says "JSON". Slot names don't count, so `{json.dumps(x)}` is not an ask for JSON: **json**.
  4. The prompt lists the allowed answers ("one label: bug, feature, question", "one of: a, b or c", "answer yes or no"), with 2 to 20 labels of at most 3 words and none filled in at run time: **label**.
  5. Anything else: **text**.
- **Build a reference from old answers** (`build_reference`, `src/modelbump/oracles/score.py`):
  - **JSON:** the top-level type, the keys more than half the old answers had with their usual type, and the values every old answer agreed on (with two or more answers).
  - **Label:** the label more than half the old answers gave, if any.
  - **Text:** the fewest and most words, the list and code formats every old answer had, whether any old answer refused, and an "at most N words/sentences" limit stated in the prompt.
- **Score an answer as the share of checks it passes** (`score`):
  - **JSON:** no JSON in the answer scores 0. The JSON may sit in a code fence or after some prose.
  - **Label:** 1 or 0. With a majority old label the answer must match it; otherwise it must be one of the labels.
  - **Text:** not empty, not a refusal (skipped if the old model refused too), 0.5x to 2x the old length range, kept formats, kept stated limit.
- **Keep reference answers apart from compared answers.** If the old answers that build the reference were also scored, the old model would pass its own checks by construction. The suite step will draw the reference from separate old samples (their own sample numbers in the cache).
- **`modelbump oracles PATH`** lists each call's kind, the reason, and the checks it runs (`--format json`, `--model`, `--exclude`, `--skip-tests`, `--output`, as for `modelbump prompts`).

On the five apps of [ADR 0049](0049-follow-prompts-across-files-classes-and-functions.md) (82 calls), the oracles are 57 text, 14 json, 11 tools and 0 label. Each of the 14 JSON picks was checked against its prompt, and each prompt does ask for JSON. One of them also has `{json.dumps(search_results)}` as a slot, which is why only written text counts (rule 3). None of the five apps asks for a label from a list, so the corpus step must include classification apps.

## Alternatives considered

- **An LLM judge for everything:** one oracle, but slow, costly in local compute, and itself biased. It is kept for free text, where nothing cheaper can tell good from bad, and it is calibrated against hand labels in a later step.
- **Exact match against the old answer:** too strict for anything but labels. Two correct summaries rarely share a word order, and even JSON key order or a changed number format would fail.
- **Embedding similarity to the old answer:** needs a model download, a threshold to tune per app, and treats "the order total is 4" and "the order total is 40" as almost the same.
- **Inferring a full JSON Schema from old answers:** more precise, but it needs a dependency (the plan listed `jsonschema`) and overfits optional fields seen once. Keys seen in most answers, with their types, catch the common breakages (a missing field, a string where a list was) with no dependency.
- **Using the app's own assertions as oracles:** the best source where they exist, but real apps rarely test their LLM calls (Paper 1: 17.3% of migrations touch a test file). Left for later.

## Consequences

- Every scored call gets a number in [0, 1] from cheap, deterministic checks, ready for the stats engine.
- Text checks are coarse. They catch empty answers, refusals, length blow-ups and lost formats, not a wrong summary. A free-text call needs the judge (next steps) before a REGRESSED verdict on it means much.
- Tool calls are listed but not scored until the runner sends tool definitions.
- The reference is only as good as the old model's answers. If the old model was already wrong, a new model that copies it scores well. That is the point of a migration test, and it is reported as such.
