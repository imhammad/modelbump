# ADR 0036: The runner calls OpenAI-compatible endpoints with httpx, not LiteLLM, and uses only free models

- **Status:** Accepted
- **Date:** 2026-10-26

## Context

Phase 3 builds the runner: the part of ModelBump that sends prompts to models, for the regression tests of later phases. The master plan said "a LiteLLM-based async runner". Two things changed since then:

- **No money is spent on this project.** Every experiment runs on local open-weight models through [Ollama](https://ollama.com) on a 16 GB laptop, or on free API tiers. No paid API keys.
- **LiteLLM's PyPI package was compromised.** On 2026-03-24, versions 1.82.7 and 1.82.8 were published with a credential stealer that ran on every Python start ([FutureSearch write-up](https://futuresearch.ai/blog/litellm-pypi-supply-chain-attack/)). ModelBump is meant to run in CI next to secrets, so every dependency is a risk to its users.

Ollama, and the free tiers we may use later, all serve the same OpenAI-compatible `POST /chat/completions` API.

## Decision

- **One small HTTP client, `httpx`, talks to every endpoint** through the OpenAI-compatible chat completions API. `httpx` moves from the research group into the package dependencies.
- **A model is written `endpoint/model`**, for example `ollama/qwen2.5:7b`. Only the first `/` splits, so model names that contain `/` still work. The endpoint list holds only free endpoints; Ollama is the first.
- **Each attempt has a timeout** (120 s by default, because a 7B model takes a while to load the first time).
- **Retries with exponential backoff and full jitter**, at most 4 attempts by default, on timeouts, connection errors and HTTP 408, 429, 500, 502, 503 and 504. A `Retry-After` header in seconds is respected, up to the 30 s cap. Other 4xx errors (a missing model, a bad key) fail at once, because trying again cannot fix them.
- **`run_many` limits concurrency** with a semaphore (2 at a time by default; a laptop runs one 7B model at a time anyway) and keeps results in input order.
- **Sleep and randomness are injected**, so the tests check retries and backoff without waiting or touching the network.
- **`modelbump ask`** sends one prompt from the command line, to try the runner by hand.

## Alternatives considered

- **LiteLLM:** covers a hundred providers, but pulls in a large dependency tree, and we need one API shape. Its compromise shows the cost of a large tree in a tool that runs in CI.
- **The `openai` Python SDK pointed at other base URLs:** works with Ollama, but adds a heavier dependency for one POST request, and retry behaviour we would have to configure around anyway.
- **Ollama's own `/api/chat` endpoint:** gives a few extra fields, but then each free tier would need its own client.
- **vLLM:** faster on a GPU server, but needs a GPU we do not have. Ollama runs on Apple Silicon.

## Consequences

- Adding a free endpoint later is one line in `ENDPOINTS`, plus the environment variable that holds its key.
- Provider-specific features that are not in the OpenAI-compatible API are out of reach. The regression tests only need text in and text out, plus token counts.
- The cache and the budget limit come next, on top of `ChatRequest`, which already holds everything that can change an answer.
