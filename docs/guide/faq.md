# FAQ

## Does it cost anything?

No. ModelBump is free and open source (Apache 2.0). By default every model call goes to [Ollama](https://ollama.com/) on your own computer. You can also use the free tiers of Groq, Google Gemini and OpenRouter. ModelBump paces its requests so it stays under their per-minute limits, and `--budget-requests` stops a run before it uses too many.

## Which models can I test with?

Write a model as `endpoint/model`:

| Endpoint | Example | Key |
|----------|---------|-----|
| `ollama` | `ollama/qwen2.5:7b` | none, runs locally |
| `groq` | `groq/llama-3.1-8b-instant` | `GROQ_API_KEY` |
| `gemini` | `gemini/gemini-3.8-flash` | `GEMINI_API_KEY` |
| `openrouter` | `openrouter/PUBLISHER/MODEL:free` (see openrouter.ai/models) | `OPENROUTER_API_KEY` |

The keys for these free tiers need no card. Paid endpoints are not built in. When the model your app uses has no free tier, test with stand-ins, two models that differ the way yours do. The pull request then says the tested models stood in for the real ones, so a reviewer knows what the evidence covers.

## Do my prompts leave my computer?

Not with `ollama/` models. With a cloud endpoint, the prompts and answers go to that provider, and free tiers may keep and read them. The commands that send prompts print a note when a cloud model is used.

## What ends up in the pull request?

- **The code changes:** the new model ID, and any accepted prompt repairs.
- **The description:** verdicts and scores, never prompts or answers.
- **`.modelbump/`:** the suite, the test report with every answer, and the repairs, so anyone can rerun the test.

Before writing `.modelbump/`, the bump replaces API keys, tokens, private keys and email addresses with `[REDACTED:kind]`. Names, addresses and phone numbers cannot be found reliably by pattern, so read `.modelbump/test.json` before merging. If your prompts handle personal data, run the bump without `--report`, so no answers are committed.

## Will it change my comments, docs or price tables?

Not by default. The bump changes only places where the code uses the model: call arguments, variables, config values and strings. It lists comments, docstrings, sentences and price tables as "Left alone, check by hand". `--include-docs` also changes comments, docstrings and sentences. Price tables and platform forms such as Bedrock or Vertex IDs are never changed, because their right new value is not a plain swap.

## Which languages does it support?

- **Scan and bump the model ID:** Python, JavaScript and TypeScript (with full context), Go, Java, Kotlin, Ruby, Rust, C#, PHP, Swift, shell, Elixir, HTML, and config files (JSON, YAML, TOML, INI, `.env`).
- **Build test suites, repair prompts, move IDs to an environment variable:** Python.

## How fresh is the retirement registry?

It ships inside the package, with dates taken from the providers' deprecation pages, and every release updates it. `modelbump check MODEL_ID` shows what it knows about one model. A model the registry does not list shows as `UNKNOWN`, not as safe.

## The scheduled Action opened nothing. Why?

Check, in order:

1. `open-prs: "dry-run"` lists what it would open, in the job summary.
2. The model must be used in code (not only in a comment), shut down within `within` days, and have a replacement in the registry that is not retired.
3. A branch `modelbump/OLD-to-NEW` already exists. Delete it to get a new pull request.
4. The repository setting "Allow GitHub Actions to create and approve pull requests" must be on.

## Can ModelBump merge the pull request for me?

No, on purpose. A model change can alter what an app says to its users, so a person should read the evidence and decide.

## How do I cite it?

The research behind ModelBump is described in the [research section](../research/index.md). Until the papers are out, cite the repository: `https://github.com/imhammad/modelbump`.
