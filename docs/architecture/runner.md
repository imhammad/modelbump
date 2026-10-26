# Runner

**Job:** send prompts to models and get answers back, reliably and for free.

**Code:** `src/modelbump/runner/` · **Command:** `modelbump ask PROMPT --model ollama/qwen2.5:7b` · **Decisions:** [ADR 0036](../adr/0036-runner-speaks-openai-compatible-http.md)

```mermaid
flowchart LR
    req[ChatRequest<br/>model, messages,<br/>temperature, max_tokens, seed] --> run[Runner<br/>timeout, retries,<br/>concurrency limit]
    run --> resolve[backends.py<br/>endpoint/model to URL]
    resolve --> ollama[(Ollama on this machine<br/>/v1/chat/completions)]
    ollama --> result[ChatResult<br/>text, tokens, attempts, seconds]
```

## What happens on a failure

| Failure | What the runner does |
|---------|----------------------|
| Timeout, connection refused | Wait, then try again |
| HTTP 408, 429, 500, 502, 503, 504 | Wait (at least `Retry-After`, up to 30 s), then try again |
| Any other HTTP error, e.g. 404 model not found | Stop at once with `RunnerError` |
| Still failing after the last attempt | Stop with `RunnerError`, saying why and how many attempts |

The wait before attempt *n* + 1 is a random time between 0 and min(30 s, 1 s × 2<sup>*n*−1</sup>). The randomness ("full jitter") stops many requests from retrying at the same moment.

## Endpoints

| Endpoint | URL | Key |
|----------|-----|-----|
| `ollama` | `http://localhost:11434/v1` (or `MODELBUMP_OLLAMA_URL`) | none |

Free API tiers come in a later step. ModelBump never needs a paid key.

## Coming next

- A cache, so the same request is never paid for (in time or tokens) twice.
- A budget limit on tokens.
