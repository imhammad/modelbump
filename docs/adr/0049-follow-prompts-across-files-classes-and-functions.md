# ADR 0049: Follow prompts into other files, class attributes and the app's own prompt functions

- **Status:** Accepted
- **Date:** 2026-10-28
- **Extends:** [ADR 0048](0048-find-llm-calls-and-prompt-templates.md), which followed names inside one file only

## Context

ADR 0048 left a known gap: prompts kept in another file, on `self`, or built by a function stay slots, and the call is marked partial. Before choosing what to follow, we looked at why calls were partial in five open-source Python LLM apps: [aider](https://github.com/Aider-AI/aider), [gpt-researcher](https://github.com/assafelovic/gpt-researcher), [swarm](https://github.com/openai/swarm), [anthropic-quickstarts](https://github.com/anthropics/anthropic-quickstarts) and [babyagi](https://github.com/yoheinakajima/babyagi). Following imports alone changed nothing in any of them. The partial calls had other causes:

- **Prompt functions.** gpt-researcher builds almost every prompt in a method such as `prompt_family.generate_report_conclusion(query=..., report_content=...)`, a static method of a `PromptFamily` class kept in `prompts.py`, reached through a parameter typed `prompt_family: type[PromptFamily] | PromptFamily`.
- **`create(**params)`.** swarm builds `create_params = {"model": ..., "messages": ...}` and calls `client.chat.completions.create(**create_params)`, so the call showed no model and no messages at all.
- **History.** Chat apps send `[system] + history`. The history only exists at run time, but the system message is in the code, and the whole list was dropped as unreadable.
- **Wrappers.** Apps call the SDK inside their own function (`def create_chat_completion(model, messages)`), so the prompt is an argument there. The wrapper's callers are found already when they pass `model=` and `messages=` (`Api.OTHER`), and their prompts can be read at the caller.

## Decision

The resolver (`_Resolver` in `src/modelbump/synth/callsites.py`) now reads, besides names in the same file:

- **Other files in the scanned folder.** `from .x import NAME` (any level), `from app.x import NAME as A`, `import app.x as m` then `m.NAME`, `from app import x` then `x.NAME`, and `import app.x` then `app.x.NAME`. A module is found by its full dotted path from the folder, or by a folder suffix when exactly one file matches (`app.prompts` finds `backend/src/app/prompts.py`), because apps often run from a subfolder or `src/`. Two matches mean we do not know which, so the name stays a slot. Files that do not parse are never followed. Files left out with `--exclude` or `--skip-tests` are still followed into, but not listed.
- **Class attributes.** `self.x` is the value set earlier in the same method, else in `__init__`, else in the class body, else in the only other method that sets it. Two other methods setting it is ambiguous, so it stays a slot. Class-body names are not visible from methods, as in Python.
- **The app's own functions.** A call to a function or method with exactly one `return` is read by binding its parameters to the call's arguments (positional, keyword, then defaults) and reading the returned expression. `def build(q): return f"Q: {q}"` called as `build(question)` gives `Q: {question}`, with the slot named after the caller's code. Methods are found through `self`, the class name, a parameter annotated with the class (`X`, `"X"`, `type[X]`, `X | None`, `Optional[X]`), or `x = X(...)`. Functions with several returns, `*args` at the call, and recursion are not read.
- **`create(**params)`.** Keywords come from a dict literal, written in the call or in a name assigned in the same function. Keywords written in the call win, as in Python.
- **Lists with unknown parts.** `[system] + history`, `[*messages, *more]` and `.extend(unknown)` keep the messages they can read, plus one `unknown` part for each piece they cannot.
- **`messages.count_tokens(...)`** is no longer an LLM call: it does not generate an answer.

## Results on the five apps

Calls with all prompt text, before (Step P5-1) and after (this step), from `modelbump prompts` on each app's default branch cloned on 2026-10-28 (commits: aider `5dc9490`, gpt-researcher `3582a68`, swarm `6af0b4c`, anthropic-quickstarts `930ad10`, babyagi `fa8930e`):

| App | Calls | Complete before | Complete after |
|-----|------:|----------------:|---------------:|
| gpt-researcher | 33 | 13 | 18 |
| aider | 11 | 7 | 7 |
| babyagi | 13 | 6 | 6 |
| swarm | 7 | 1 | 1 |
| anthropic-quickstarts | 19 → 18 | 8 | 7 |
| **All** | **83 → 82** | **35** | **39** |

anthropic-quickstarts lost a `count_tokens` call, which had counted as complete. swarm's main call now shows its system message and an `unknown` history part instead of nothing, but it stays partial: the system prompt is `agent.instructions`, set by whoever builds the agent. These are small samples cloned to look for causes, not the benchmark corpus. Phase 5 measures extraction on the corpus later.

## Alternatives considered

- **Matching a method by a unique name across the app** (`anything.generate_report_conclusion(...)` → the one method with that name): it would read more gpt-researcher calls, but it is a guess about the object's type. We follow types only when the code states them.
- **Type inference with mypy or pyright:** it would find many more types, but it needs the app's dependencies installed and is much slower. A type-hint-only rule is cheap and never wrong about the hint.
- **Following a wrapper's callers** (one call site per caller of `create_chat_completion`): useful, and the next step for the synthesizer. Many callers are already found as `Api.OTHER` calls with their own prompts.

## Consequences

- Prompts built in a `prompts.py` module or in prompt functions now come out as real templates with slots, which the synthesizer needs to make test inputs.
- What remains partial is mostly run-time data (history, user input passed through wrappers), which a test suite has to supply anyway.
- `modelbump prompts FILE` reads one file alone; following imports needs the folder.
