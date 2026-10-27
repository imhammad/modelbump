# ADR 0040: Add three free cloud tiers, paced under their per-minute limits, and warn before prompts leave the machine

- **Status:** Accepted
- **Date:** 2026-10-27

## Context

Local models through Ollama ([ADR 0039](0039-pin-local-models-to-their-digest.md)) cover the controlled experiments. Some later work needs models a laptop cannot run, or a hosted model to check results against. ModelBump spends no money ([ADR 0036](0036-runner-speaks-openai-compatible-http.md)), so only free tiers qualify. We checked the current free offers on 2026-10-27:

| Provider | Free limits found | Card needed | Notes |
|----------|-------------------|-------------|-------|
| [Groq](https://klymentiev.com/blog/groq-api-free-tier) | `llama-3.1-8b-instant`: 30 requests/min, 14,400/day, 6,000 tokens/min; `llama-3.3-70b-versatile`: 30/min, 1,000/day | No | OpenAI-compatible at `https://api.groq.com/openai/v1` |
| [Google Gemini](https://apidog.com/blog/gemini-api-free-tier/) | Flash and Flash-Lite models and Gemma 4 are free; Google no longer publishes the numbers, AI Studio shows each project's limits | No | Free-tier prompts and answers may be used to improve Google's products and read by human reviewers. OpenAI-compatible at `.../v1beta/openai/` ([docs](https://ai.google.dev/gemini-api/docs/openai)). Reasoning cannot be turned off for Gemini 3 models |
| [OpenRouter](https://openrouter.ai/blog/tutorials/free-llm-apis-compared/) | `:free` models: 20 requests/min, 50/day without bought credits | No | Free models are served by third parties; their logging policies vary |
| GitHub Models | none | n/a | [Retired on 2026-07-30](https://github.blog/changelog/2026-07-01-github-models-is-being-fully-retired-on-july-30-2026/), so it is left out |

Going over a per-minute limit gives HTTP 429 errors. Retries with `Retry-After` recover ([ADR 0036](0036-runner-speaks-openai-compatible-http.md)), but each failed try still counts against the daily allowance.

## Decision

- **Three cloud endpoints are added:** `groq/…`, `gemini/…` and `openrouter/…`. Each reads its key from `GROQ_API_KEY`, `GEMINI_API_KEY` or `OPENROUTER_API_KEY`. A missing key is a `RunnerError` that names the variable. Keys are never written to a file by ModelBump.
- **Each endpoint has an `rpm`**, at or below its free per-minute limit: Groq 30, Gemini 10 (a cautious guess, since Google publishes no numbers), OpenRouter 20. The runner spaces requests to that endpoint at least 60/rpm seconds apart, retries included. Concurrent requests book their slots in turn, so they cannot burst past the limit. Ollama has no `rpm`, so local calls are never slowed.
- **Daily limits are left to the budget** ([ADR 0038](0038-budget-in-tokens-and-requests.md)): `--budget-requests 50` keeps an OpenRouter run inside its free day.
- **Endpoints say whether they are local.** `modelbump ask` prints a note on stderr before using a cloud endpoint: the prompts leave the machine and may be kept or read by the provider, so private data must never be sent. Experiments send only public benchmark prompts to cloud tiers.
- **Model names keep the provider's own form after the first `/`**, for example `openrouter/PUBLISHER/MODEL:free` as listed on OpenRouter.

## Alternatives considered

- **Leave cloud tiers out:** local models are enough for the core experiments, but a few comparisons need bigger hosted models, and adding endpoints now costs a few lines.
- **A token-bucket rate limiter that allows short bursts:** more flexible, but free tiers also limit tokens per minute in ways we cannot see in advance. Even spacing is simple and predictable.
- **Reading keys from a `.env` file:** convenient, but it is one more place a key can leak. `.env` is already git-ignored, and people who want one can load it into their shell.
- **Mistral, Cerebras, Cloudflare and other free tiers:** possible later, each as one more line. Three providers are enough to start.

## Consequences

- Any free OpenAI-compatible provider can be added as one `Endpoint` line with its key variable and limit.
- Free-tier limits change often. The `rpm` values may need updating, and the date of each check is kept here.
- Results from cloud models cannot be pinned to exact weights the way local models are, because providers can change a model behind its name. Experiments that need exact reproducibility use local models.
