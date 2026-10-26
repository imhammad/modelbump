# ADR 0038: Limit spending in tokens and requests, not dollars, and count cached answers as savings

- **Status:** Accepted
- **Date:** 2026-10-26

## Context

The master plan asked for "a budget manager: stop at a maximum number of tokens or dollars, and report the spend". ModelBump spends no money ([ADR 0036](0036-runner-speaks-openai-compatible-http.md)): local models cost time, and free API tiers allow a fixed number of requests and tokens per minute or per day. Going over a free limit means errors for the rest of the day, not a bill. So the useful limits are tokens and requests.

## Decision

- **`Budget(max_tokens=..., max_requests=...)`**, either or both, given to the `Runner`.
- **Tokens** are input plus output tokens of real answers, as the server reports them.
- **Requests** are HTTP requests sent, **retries included**, because free tiers count every request, failed or not.
- **The check happens before each request is sent.** Once a limit is reached, every further request fails at once with `BudgetExceeded` (a `RunnerError`), without touching the network. Requests already in flight finish, so the token total can end a little above the limit, by at most what the in-flight answers use. With the default concurrency of 2, that is one answer.
- **Cached answers cost nothing.** They are counted separately, as answers and tokens saved. Since every answer that came back was cached ([ADR 0037](0037-response-cache-in-sqlite.md)), running the same suite again with the same limit continues where the last run stopped.
- **`run_many` tries every request before raising the first error**, so no answer that could be had is lost. The new `run_each` returns each request's result or its error, in order, for callers that want partial results.
- **`budget.summary()`** gives one line: requests, tokens in and out, answers and tokens from the cache, and the share of each limit used.
- **`modelbump ask` takes several prompts**, plus `--budget-tokens` and `--budget-requests`, to show the cache and the budget working together.
- `RunnerError` moves to `runner/types.py` so the budget can subclass it without a circular import. It is still importable from `modelbump.runner`.

## Alternatives considered

- **Dollars:** every model we use is free. A price table would need upkeep and would always show $0.
- **Reserving tokens before a request (for example `max_tokens` of the answer):** exact, but many requests do not set `max_tokens`, and Ollama's token counts are only known afterwards. A small, bounded overshoot is simpler and honest.
- **Raising at the first error in `run_many`:** the other answers in flight would be thrown away even though they cost time or quota.
- **Per-minute rate limiting:** a different problem. Retries with `Retry-After` handle short bursts ([ADR 0036](0036-runner-speaks-openai-compatible-http.md)); a rate limiter can be added with the free-tier endpoints if they need one.

## Consequences

- An experiment can be capped to a free tier's daily allowance and resumed the next day at no extra cost.
- Spend reports count real model work only, which is what a paper should report as the cost of a method.
- A budget belongs to one run. Totals across runs are not stored; the cache (`modelbump cache info`) shows the overall total.
