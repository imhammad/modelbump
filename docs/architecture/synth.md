# Suite synthesizer

**Job:** turn an app's own LLM calls into regression test cases that the runner and the stats engine can compare on the old and new model.

**Code:** `src/modelbump/synth/` · **Commands:** `modelbump prompts PATH`, `modelbump cases PATH` · **Decisions:** [ADR 0048](../adr/0048-find-llm-calls-and-prompt-templates.md), [ADR 0049](../adr/0049-follow-prompts-across-files-classes-and-functions.md), [ADR 0050](../adr/0050-test-inputs-from-the-apps-own-callers.md), [ADR 0051](../adr/0051-generated-test-inputs-from-a-local-model.md)

```mermaid
flowchart LR
    repo[Python files] --> calls[callsites.py<br/>find LLM calls with ast]
    calls --> sites[CallSite: path, line, API,<br/>model, messages as templates]
    sites --> report[report.py<br/>text or JSON]
    report --> cli[modelbump prompts]
    sites --> cases[cases.py<br/>values from the app's<br/>tests and callers]
    cases --> generate[generate.py<br/>a local model writes<br/>the missing inputs]
    generate --> cli2[modelbump cases]
    cases --> cli2
    generate --> oracles[oracles by output type]
    oracles --> suite[suite file and modelbump test]
```

The [oracles](oracles.md) and the [suite file with `modelbump test`](suite.md) have their own pages. How it all does on 40 real apps is in [the Phase 5 results](../research/suites.md).

## What a call site holds

| Field | Example |
|-------|---------|
| `path`, `line` | `support.py`, `24` |
| `api` | `openai_chat`, `openai_responses`, `openai_completions`, `anthropic`, `gemini`, `litellm`, `ollama`, `other` |
| `call` | `client.chat.completions.create` |
| `model` | `gpt-4o-mini` (also through `MODEL = os.getenv("M", "gpt-4o-mini")`), or empty when the file does not say |
| `parts` | one per message: role (`system`, `user`, `assistant`, `prompt`, `unknown`) and template |
| `complete` | every message was read and holds written text |

## Templates

A template is the text the code writes, in Python's format syntax: `{slot}` where the code puts in a value at run time, and `{{` for a literal brace. `render(template, values)` fills it.

| Code | Template |
|------|----------|
| `f"Ticket:\n{ticket}"` | `Ticket:\n{ticket}` |
| `"Hi {}, {who}".format(a, who=b)` | `Hi {a}, {who}` |
| `"Total %d of %s" % (n, kind)` | `Total {n} of {kind}` |
| `"Summarize: " + text` | `Summarize: {text}` |
| `f"Labels: {LABELS}"` with `LABELS = "bug, feature"` | `Labels: bug, feature` |
| `textwrap.dedent("""...""").format(...)`, `.strip()`, `"\n".join([...])` | the text after those calls |
| `prompt` (a function argument) | `{prompt}`: only a slot, so the call is partial |

Messages are read from list literals of `{"role": ..., "content": ...}` dicts, `dict(role=..., content=...)`, `("system", "...")` tuples and LangChain-style `SystemMessage(...)` / `HumanMessage(...)`, including lists built in a variable with `.append`, `.extend`, `+=`, `+` and `*`. Anthropic's `system=` and OpenAI's `instructions=` become a system message; content blocks keep their text blocks only.

## Following prompts through the code

Prompts are often not written at the call. The finder follows them, in this order of where a name is looked up:

| Code | What is followed |
|------|------------------|
| `prompt = f"..."` then `create(prompt=prompt)` | The last assignment before the call in the same function, then module names |
| `from .prompts import SYSTEM`, `import app.prompts as p` then `p.SYSTEM` | Other files in the folder, by relative import, full module name, or a unique folder suffix (`app.prompts` finds `backend/src/app/prompts.py`) |
| `self.system` | Set earlier in the same method, else in `__init__`, else in the class body, else in the only other method that sets it |
| `build_prompt(question)` | A function of the app with one `return`, read with the call's arguments: `def build_prompt(q): return f"Q: {q}"` gives `Q: {question}` |
| `self.method(...)`, `Prompts.method(...)`, `family.method(...)` | Methods, through `self`, the class name, a parameter typed `family: Prompts` (or `type[Prompts]`, `Prompts \| None`), or `family = Prompts()` |
| `create(**params)` | A dict literal of keywords in the same function; keywords written in the call win |
| `[system_message] + history` | The messages it can read, plus one `unknown` part for `history` |

Following imports needs the folder: `modelbump prompts app.py` reads that one file alone. Files left out with `--exclude` or `--skip-tests` are still followed into; they are only left out of the report.

## Example

```console
$ modelbump prompts tests/fixtures/prompt-demo
bot.py:14  openai_chat  self.client.chat.completions.create
  model: gpt-4o-mini
  system: "Answer questions about our product from the FAQ. If unsure, say you don't know."
  user: "Question: {question}\nAnswer in at most 2 sentences."
  slots: question
extract.py:9  gemini  client.models.generate_content
  model: gemini-2.0-flash
  system: "Return JSON with the keys order_id, items and total."
  user: "Email:\n{email}\n\nJSON:"
  slots: email
support.py:24  openai_chat  client.chat.completions.create
  model: gpt-4o-mini
  system: "You sort support tickets.\nAnswer with one label: bug, feature, question.\n"
  user: "Ticket:\n{ticket}"
  slots: ticket
...
Found 5 LLM calls in 3 files (read 4 Python files): 4 with all prompt text, 1 partial.
```

`bot.py` takes its model, system prompt and question template from `prompts.py`. `--model gpt-4o-mini` keeps the calls to one model, and `--format json --output calls.json` writes the full templates.

## Test cases from the app's own code

A slot gets a value where the app calls the function that holds the LLM call. `modelbump cases` finds those calls in every Python file, tests included, binds the function's parameters to the call's arguments, and reads the call site again:

```python
# support.py
def classify(client, ticket):
    ...create(model=MODEL, messages=[..., {"role": "user", "content": f"Ticket:\n{ticket}"}])

# tests/test_support.py
@pytest.mark.parametrize("ticket", ["The app crashes when I log in.", "Could you add a dark mode?"])
def test_classify_sends_the_ticket(ticket):
    classify(MagicMock(), ticket)
```

gives two complete cases for `support.py:24`, one per row, with the final messages to send. Only values written in the code count: strings, numbers and literal lists or dicts, through names, constants and imports. A caller that passes its own variable gives no case.

```console
$ modelbump cases tests/fixtures/prompt-demo
bot.py:14  openai_chat  self.client.chat.completions.create  model: gpt-4o-mini
  tests/test_support.py:36  question="How do I reset my password?"
extract.py:9  gemini  client.models.generate_content  model: gemini-2.0-flash
  no cases (slots: email)
support.py:24  openai_chat  client.chat.completions.create  model: gpt-4o-mini
  tests/test_support.py:16  ticket="The app crashes when I log in."
  tests/test_support.py:17  ticket="Could you add a dark mode?"
  tests/test_support.py:18  ticket="How do I export my data?"
...
Found 5 test cases (5 complete) for 3 of 5 LLM calls. No case yet for 1 with slots (extract.py:9).
```

`--format json` gives each complete case's `messages`. Real apps rarely call their prompt functions with written values (1 case for 82 calls in five open-source apps, ADR 0050), so most cases will come from generated inputs, the next step.

## Generated inputs

`modelbump cases PATH --generate 5` has a local model (`ollama/qwen2.5:7b`, or `--generator`) write inputs until each call with slots has 5 complete cases. The model sees the call's templates and slot names and answers with a JSON array of value sets. Each one becomes a case marked `generated by ollama/qwen2.5:7b, sample 0`, so it is never mixed up with the app's own values.

```console
$ modelbump cases tests/fixtures/prompt-demo --generate 2
...
extract.py:9  gemini  client.models.generate_content  model: gemini-2.0-flash
  generated by ollama/qwen2.5:7b, sample 0  email="Hi, I'd like to order 2 blue mugs..."
  generated by ollama/qwen2.5:7b, sample 0  email="Order #4471: 1x desk lamp, ..."
...
Found 9 test cases (9 complete, 4 generated) for 4 of 5 LLM calls.
```

The values above are only an example; the model writes its own. Requests are seeded and cached, so running the same command again prints the same cases from the cache. Calls with a message that cannot be read (such as `history`) are not asked. A call that ends up with too few cases is listed on stderr with the reason.

How each case's answers are checked is on the [Oracles](oracles.md) page.

## Limits (for now)

- Python only. TypeScript and JavaScript come later, with tree-sitter.
- A prompt passed into a function as an argument stays a slot in that function (`def ask(prompt): create(prompt=prompt)`); the callers of a wrapper are not followed yet.
- With `if`/`else` or `a if c else b`, the finder does not pick a branch: the last assignment before the call wins, and a conditional expression stays a slot.
- A function with more than one `return`, an object whose class has no type hint, and conversation history built at run time stay unknown.
