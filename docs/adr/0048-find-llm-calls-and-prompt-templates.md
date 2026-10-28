# ADR 0048: Find each LLM call and its prompt template with Python's own parser, inside one file

- **Status:** Accepted
- **Date:** 2026-10-28

## Context

Phase 5 builds a regression suite from an app's own prompts: the test cases that `modelbump test --from X --to Y` will run on the old and new model. The first job is to find the prompts. The scanner ([ADR 0023](0023-scanner-finds-ids-as-text-first.md), [ADR 0027](0027-python-context-with-tree-sitter.md)) finds model IDs, but a test case needs more than an ID:

- **where** the app calls a model, and through which API (OpenAI chat or Responses, Anthropic, Gemini, LiteLLM, Ollama);
- **which model** the call uses, even when the ID sits in a constant or an environment default;
- **what it sends:** each message with its role, as text with a slot wherever the code puts in a value at run time (`f"Ticket:\n{ticket}"` → `Ticket:\n{ticket}`), so a later step can fill the slots with test inputs.

Real code builds prompts in many ways: string literals, f-strings, `.format()`, `%`, `+`, `textwrap.dedent`, `"\n".join(...)`, a `messages` list filled with `.append`, a system prompt in a module constant. We tried the finder on the example folders of the OpenAI and Anthropic Python SDKs (68 and 31 files): it found 32 and 29 calls, with all prompt text for 30 and 24 of them.

## Decision

- **Python's own `ast` module, not tree-sitter, for Python call sites** (`src/modelbump/synth/callsites.py`). The prompt is the point here, and `ast` gives the exact value of every string (escapes, implicit concatenation, triple quotes) and the pieces of every f-string. Tree-sitter stays in the scanner, where surviving broken files matters more than exact strings. A file that does not parse is listed in the report, never guessed at.
- **What counts as an LLM call:** a call whose name ends like a provider SDK method (`chat.completions.create/parse/stream`, `responses.create`, `completions.create`, `messages.create/stream/parse`, `generate_content`, `litellm.completion`, `ollama.chat/generate`), or any call with both `model=` and `messages=`/`prompt=` keywords (`Api.OTHER`). OpenAI Assistants thread messages and image, audio, video and embedding calls are left out: they have no text answer to compare.
- **Templates use Python's format syntax.** `{name}` is a slot and a literal brace is doubled, so `render(template, values)` fills it and `slot_names` lists it with the standard library's `string.Formatter`. A slot is named after the code that fills it (`{ticket.body}`), or after the template's own field for `.format(labels=...)` (`{labels}`).
- **Names are followed inside one file.** The last assignment before the call in the same function wins; module names are visible from every function; `+=`, `.append` and `.extend` after it are added in order. A value the file states (a constant string or number) is written into the template instead of a slot (`f"Labels: {LABELS}"` → `Labels: bug, feature`). `os.getenv("X", "default")`, `os.environ.get("X", "default")` and `... or "default"` give the default as the model.
- **Unknowns are marked, not guessed.** A value from a function argument, an attribute, another file or a function call stays a slot; a message the finder cannot read (`messages=history`, tool results) has no template. A call is **complete** only when every message was read and each holds written text, and the report marks the others `(partial)`.
- **Command:** `modelbump prompts PATH [--model ID] [--format text|json] [--output FILE] [--exclude ...] [--skip-tests]`. The text report shows each call, its model and a preview of each message; the JSON report (version 1) keeps the full templates for the next steps.

## Alternatives considered

- **Tree-sitter for Python too**, as in the scanner: one parser for all languages, and it survives syntax errors. But reading exact string values out of its tree means re-implementing Python's escape and f-string rules, and a wrong prompt text is worse than a skipped file. TypeScript and JavaScript will need tree-sitter in a later step.
- **Running the app and recording the prompts it sends (traces):** exact, but needs the app's keys, data and setup, and it calls a paid model. Traces stay an optional input for later, as the master plan says.
- **Asking an LLM to find the prompts:** flexible, but not reproducible, it can make up a prompt that is not there, and it sends the code to a model.
- **Following names across files and function calls:** needed for many real apps (`from .prompts import SYSTEM`), but it is a bigger piece of work. The first version marks those calls partial, so the gap is counted, not hidden.

## Consequences

- The synthesizer knows each call's model and prompt templates, with slots for test inputs, from static code alone: no keys, no model calls, no cost.
- Partial calls tell us how much is missing. Measuring this on the benchmark corpus later gives the extraction numbers for the paper.
- Known gaps, each a later step: other files and function arguments, class attributes (`self.prompt`), branches (`if`/`else` keep the last assignment), LangChain prompt templates, notebooks, and TypeScript/JavaScript.
