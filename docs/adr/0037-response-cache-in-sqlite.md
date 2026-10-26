# ADR 0037: Cache model answers in one SQLite file, keyed by a hash of the whole request

- **Status:** Accepted
- **Date:** 2026-10-26

## Context

Later phases compare an old and a new model on the same test cases, many times over. On a laptop, one 7B model answer takes a few seconds, and free API tiers allow only a limited number of calls a day. Re-running an experiment, after a bug fix in the scoring code or for a reviewer, must not call the models again. It must also give exactly the same numbers. The master plan's definition of done for Phase 3 says: "the same suite run twice costs $0 the second time".

## Decision

- **The key is the SHA-256 hash of the request's canonical JSON:** a key version, the `endpoint/model` string, every message with its role, `temperature`, `max_tokens`, `seed`, and a new `sample` number. JSON is written with sorted keys and no spaces, so the same request always gives the same key.
- **`sample` numbers repeated draws** of the same request (0, 1, 2, ...). The statistics engine (Phase 4) draws each test case k times, and each draw needs its own entry. `sample` is not sent to the model.
- **One SQLite file** (Python's built-in `sqlite3`, no new dependency) holds the answers: text, token counts, finish reason, and the time stored. WAL mode lets two processes use it at once.
- **Default place:** `$MODELBUMP_CACHE_DIR/responses.sqlite`, else `$XDG_CACHE_HOME/modelbump/`, else `~/.cache/modelbump/`. It sits outside the repository, so it is never committed by accident.
- **Only successful answers are stored.** A timeout or an HTTP error is never cached, so a flaky moment cannot become a permanent wrong result.
- **A cached result says so:** `cached=True`, `attempts=0`, `seconds=0`, so later budget code can count only real calls.
- **The runner reads the cache first** and writes to it after a successful call. `modelbump ask` uses the cache by default (`--no-cache` skips it). `modelbump cache info` shows what is stored, and `modelbump cache clear` empties it after asking for confirmation.

## Alternatives considered

- **One JSON file per answer in a folder:** easy to read by hand, but tens of thousands of small files are slow to copy and count. SQLite can still be opened with any SQLite viewer.
- **`diskcache`:** a good library, but another dependency for something the standard library already does.
- **Caching inside the HTTP client:** it would key on raw bytes, which change with JSON key order, and it cannot hold the `sample` number.
- **A key that includes runner settings (timeout, retries):** these change how we ask, not what the model answers, so they stay out of the key.

## Consequences

- Re-running an experiment is free and repeatable as long as the cache file is kept. For a paper, the cache file can be archived next to the results.
- If a model tag is re-pulled with new weights under the same name (for example `qwen2.5:7b`), old answers would still be served. A later step can add the model's digest to the key; until then, `modelbump cache clear` after a re-pull.
- Changing the key recipe means bumping `KEY_VERSION`, which leaves old entries unused rather than misread.
