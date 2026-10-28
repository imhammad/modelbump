# ADR 0050: Take the first test inputs from the values the app's own tests and code pass in

- **Status:** Accepted
- **Date:** 2026-10-28

## Context

After [ADR 0048](0048-find-llm-calls-and-prompt-templates.md) and [ADR 0049](0049-follow-prompts-across-files-classes-and-functions.md), each LLM call comes out as templates with slots, such as `Ticket:\n{ticket}`. To compare two models on a call, we need values for its slots: one set of values is one test case. The master plan's order is: inputs the repository already has first, then inputs a model generates within the template's limits, then traces.

Values a developer chose are the best inputs we can get. They are real, they cost nothing, and nobody can say we made them up. The commonest place for them is a test or an example that calls the function the LLM call sits in: `classify(client, "The app crashes on login")`, often with `pytest.mark.parametrize` rows.

## Decision

- **A case is a call site read again with its function's parameters bound to one caller's arguments** (`src/modelbump/synth/cases.py`). We find every call of that function in every Python file of the folder, including tests and files left out of the listing. The parameters are bound the same way as for prompt functions in ADR 0049 (positional, keyword, then defaults; skipped with `*args`). Then the whole call site is read again, so a value is followed through names, constants, imports, `"\n".join(lines)` and the app's prompt functions, the same way a prompt is.
- **Only values written in the code count.** A string, a number, or a literal list, dict or tuple. A caller that passes its own variable (a wrapper) gives no value, and a caller whose arguments give no value at all gives no case. Defaults fill slots in the case, but they do not make a case on their own.
- **`pytest.mark.parametrize`** is read as pytest does: names as `"a, b"` or a list of strings, rows as a list or tuple (also through a module constant), `pytest.param(...)` rows, and several decorators multiplied together. Each row is a caller, located at its own line. At most 50 rows (`MAX_ROWS`) are read per test.
- **Complete cases** have every slot filled and every message readable. Their `messages` are the final `(role, text)` pairs to send. Cases with open slots are kept and marked, because a later step can fill the rest. Identical cases are kept once. A call with a fixed prompt (no slots) needs no inputs: it is its own single case.
- **Command:** `modelbump cases PATH [--model ID] [--format text|json] [--output FILE] [--exclude ...] [--skip-tests]`. `--exclude` and `--skip-tests` only choose which calls are listed; inputs are still read from tests. JSON version 1 adds a `cases` list to each call of the `modelbump prompts` JSON.
- **ModelBump's own test run skips `tests/fixtures/`** (`collect_ignore_glob` in `tests/conftest.py`), so the demo app can have its own tests as data.

## Results on the same five apps

On the apps of ADR 0049, at the same commits, this source finds almost nothing: **1 case (with an open slot) for 82 calls.** 17 calls have a fixed prompt and need no inputs. The apps' tests mock the LLM or the wrapper around it, and never call a prompt function with written values. On the demo app (`tests/fixtures/prompt-demo`), whose tests do, it finds 5 complete cases for 3 of its 4 calls with slots.

So the app's own values are a first source, not the main one. Most cases will come from generated inputs, which is the next step. This step still gives that step what it needs: binding values to a call's parameters and reading the call again is how generated values will be put in as well.

## Alternatives considered

- **Running the app's tests and recording what reaches the SDK:** exact, but it needs the app's dependencies and keys, and a mocked client records only what the test passed to the mock, which we read statically anyway.
- **Reading fixture files (JSON, YAML, CSV) next to the tests:** useful when the files hold inputs, but which field fills which slot is a guess. It is left for later, and only if the corpus shows such files are common.
- **Following callers more than one level up** (a test calls `run(...)`, which calls `classify(...)`): more cases, but each level multiplies the work and the chance of a wrong binding. The five apps did not have such chains with written values either.

## Consequences

- The demo app now has 5 complete test cases that can go to two models as they are.
- The low yield on real apps is a result in itself: it supports generating inputs, and it goes into the paper's account of where test inputs come from.
- Generated inputs come next and must be marked as generated, so a reader can tell them from the app's own values.
