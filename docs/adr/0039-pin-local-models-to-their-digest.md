# ADR 0039: Pin local models to their Ollama digest, and let callers turn thinking off

- **Status:** Accepted
- **Date:** 2026-10-26

## Context

The experiments in later phases compare an old and a new open-weight model, for example `qwen2.5:7b` and `qwen3:8b`, run locally through Ollama ([ADR 0036](0036-runner-speaks-openai-compatible-http.md)). Two problems showed up once more than one model was pulled:

- **A model name is not a version.** `ollama pull qwen2.5:7b` can bring new weights under the same name. The cache ([ADR 0037](0037-response-cache-in-sqlite.md)) keyed only on the name would then serve answers from the old weights, and a paper could not say exactly which weights produced its numbers.
- **Newer models think before they answer.** Qwen 3 and others reason first, which costs many tokens and seconds on a laptop, and some versions put the reasoning in the answer between `<think>` tags. Ollama's OpenAI-compatible API accepts `reasoning_effort` to control this; for models that only know thinking on or off, `none` turns it off ([Ollama docs](https://docs.ollama.com/api/openai-compatibility)).

## Decision

- **`ChatRequest.model_version`** names the exact weights. It is part of the cache key and is never sent to the model.
- **`pin_versions(requests)`** asks Ollama for its local models (`GET /api/tags`) once, and fills in each `ollama/...` request's `model_version` with that model's SHA-256 digest. A name without a tag means `:latest`, as in Ollama. A model that is not pulled is an error that says `Run: ollama pull NAME`, before anything is sent. Other endpoints are left as they are.
- **`modelbump ask` pins every request**, and **`modelbump models`** lists the pulled models with their size, parameters, quantization and the first 12 characters of the digest.
- **`ChatRequest.reasoning_effort`** (`none`, `low`, `medium`, `high`) is sent as `reasoning_effort` when set, and is part of the cache key. `modelbump ask --think none` sets it.
- **A `<think>…</think>` block at the very start of an answer is removed** from the text. Tokens spent on it still count in the budget, because they cost time.
- **The cache key version goes from 1 to 2.** Answers stored before this step are no longer found and are asked again once; `modelbump cache clear` removes them.

## Alternatives considered

- **Look up the digest inside the runner before every call:** automatic, but one more request per call, and the runner would need to know about Ollama's own API. Pinning once per batch keeps the runner endpoint-neutral.
- **Write the digest into the model string (`ollama/qwen2.5:7b@845dbda0ea48`):** explicit, but Ollama does not accept that form, so it would have to be stripped before every call.
- **Keep the reasoning text in the result:** useful for some studies, but our tests compare final answers. It can be added as a field if a later phase needs it.

## Consequences

- Every cached answer from a local model is tied to the exact weights that produced it, and the paper can list the digests.
- Re-pulling a model no longer needs a manual `cache clear`.
- Callers outside the CLI must call `pin_versions` themselves to get this protection; the experiment code in later phases will do so.
