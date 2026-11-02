# Tutorial: move an app off a retired model

This tutorial takes a small demo app from a retired Claude model to its replacement, end to end:

1. find the models the app uses;
2. build a test suite from its prompts;
3. compare the old and the new model;
4. repair a prompt that got worse;
5. open the pull request.

Every model call runs on your own computer through [Ollama](https://ollama.com/), so it costs nothing. Two local models stand in for the hosted ones: `qwen2.5:7b` plays the old model and `qwen3:4b-instruct` the new one. The tutorial takes about 30 minutes, most of it waiting for answers. A laptop with 16 GB of memory is enough.

## Before you start

You need Python 3.12 or newer, git, and Ollama running. Install ModelBump and pull the three models (the third one judges free-text answers):

```bash
pip install modelbump
ollama pull qwen2.5:7b
ollama pull qwen3:4b-instruct
ollama pull gemma3:12b
```

Get the demo app, a copy of the one in ModelBump's own tests:

```bash
git clone --depth 1 https://github.com/imhammad/modelbump
cp -R modelbump/tests/fixtures/prompt-demo my-app
```

`my-app` has three Python files that call OpenAI, Anthropic and Google, and a small test file.

## 1. Find the models

```console
$ modelbump scan my-app
extract.py:10:16  gemini-2.0-flash  RETIRED  shut down no earlier than 2026-06-01; suggested replacement gemini-3.6-flash  [in client.models.generate_content(model=)]
prompts.py:3:14  gpt-4o-mini  UNKNOWN  no retirement announced  [assigned to BOT_MODEL]
support.py:10:37  gpt-4o-mini  UNKNOWN  no retirement announced  [in os.getenv(argument 2)]
support.py:31:16  claude-3-haiku-20240307  RETIRED  shut down on 2026-04-20; suggested replacement claude-haiku-4-5-20251001  [in client.messages.create(model=)]
Found 4 model IDs in 3 files (scanned 5 files): 2 RETIRED, 2 UNKNOWN.
```

(The dates are checked against today, so your statuses may differ.) Two models are already shut down. This tutorial moves `claude-3-haiku-20240307`, which `support.py` uses for a summary call and a labelling call.

## 2. Build a test suite from the app's prompts

```console
$ modelbump suite my-app --output suite.json
Wrote 5 test cases for 3 LLM calls to suite.json.
  left out extract.py:9: no complete test case
  left out support.py:39: no complete test case
```

ModelBump read each LLM call's prompt, found real inputs where the app's code and tests call it, and picked a check for each answer: the right label from a list, the right JSON keys, or free text graded by the judge. Two calls were left out because nothing in the code gives them a complete input. Add `--generate 2` to have a local model write inputs for them.

## 3. Compare the old and the new model

```bash
modelbump test suite.json --from ollama/qwen2.5:7b --to ollama/qwen3:4b-instruct --runs 10 --format json --output test.json
```

Each case runs 10 times on each model, because LLM answers change from run to run. A statistics engine then decides each case, keeping false alarms rare across the whole suite:

- **REGRESSED:** the new model is worse;
- **EQUIVALENT:** no worse than the margin;
- **IMPROVED:** the new model is better;
- **INCONCLUSIVE:** 10 runs were not enough to tell.

The command exits with code 1 when a case regressed. `test.json` keeps every answer, so you can read why.

## 4. Repair the prompts that got worse

```bash
modelbump repair propose suite.json test.json
modelbump repair run suite.json modelbump-proposals --from ollama/qwen2.5:7b --to ollama/qwen3:4b-instruct --report repair.json
```

`propose` shows the failing answers to a local model and asks it for small prompt fixes. `run` screens every candidate, then checks the best one on fresh answers. It accepts a fix only if every case of that call is shown to be no worse than the old model. The accepted fixes go to `modelbump-repair.json`, and the full report to `repair.json`. Often no fix is accepted. That is a result too: it means the call needs a person.

## 5. Bump the model

See what would change (nothing is written yet):

```bash
modelbump bump claude-3-haiku-20240307 my-app --suite suite.json --report test.json --repairs repair.json --proposals modelbump-proposals
```

The bump:

- shows a diff of every place that uses the model;
- writes the accepted prompt fixes into the code where their place is certain;
- lists what it left for you to check by hand, such as comments and price tables;
- adds the test as evidence in `.modelbump/`, with keys, tokens and email addresses replaced by `[REDACTED:kind]`.

Add `--env ANTHROPIC_MODEL` to make the code read the model from an environment variable, so the next change is one setting.

To open a pull request, `my-app` must be a git repository with a GitHub remote, and the [GitHub CLI](https://cli.github.com/) must be signed in. Then:

```bash
modelbump bump claude-3-haiku-20240307 my-app --suite suite.json --report test.json --repairs repair.json --proposals modelbump-proposals --open-pr
```

The changes go on a new branch, `modelbump/claude-3-haiku-20240307-to-claude-haiku-4-5-20251001`. The pull request says:

- why the model changes;
- what changed;
- what to check by hand;
- every test verdict, with the command that reruns the test.

Read `.modelbump/test.json` in the pull request before you merge it.

## Next

- Bump every due model at once: `modelbump bump-all my-app`, or on a schedule with the [GitHub Action](action.md).
- Use real hosted models instead of stand-ins: see [Which models can I test with?](faq.md#which-models-can-i-test-with).
- What each step does, and its limits: [How it works](how-it-works.md).
