"""Where each model is served.

Every endpoint speaks the OpenAI-compatible chat completions API, so one
small HTTP client covers all of them (ADR 0036). Only free endpoints are
listed: local models through Ollama, and free cloud tiers (ADR 0040).
"""

import os
from dataclasses import dataclass
from typing import Any

from modelbump.runner.types import ChatRequest, RunnerError


@dataclass(frozen=True)
class Endpoint:
    """An OpenAI-compatible server.

    - `api_key_env`: the environment variable that holds the key, if one is needed.
    - `rpm`: requests per minute to stay under; the runner spaces requests to
      this endpoint so a free tier's per-minute limit is never hit.
    - `local`: True when the model runs on this machine. Prompts sent to a
      cloud endpoint leave the machine, and free tiers may keep and read them.
    """

    name: str
    base_url: str
    api_key_env: str | None = None
    rpm: float | None = None
    local: bool = False

    def headers(self) -> dict[str, str]:
        """HTTP headers, with the API key read from the environment if one is needed."""
        if self.api_key_env is None:
            return {}
        key = os.environ.get(self.api_key_env)
        if not key:
            raise RunnerError(f"Set {self.api_key_env} to use the {self.name} endpoint.")
        return {"Authorization": f"Bearer {key}"}


# Ollama listens on port 11434 of this machine unless MODELBUMP_OLLAMA_URL says otherwise.
OLLAMA_URL = os.environ.get("MODELBUMP_OLLAMA_URL", "http://localhost:11434").rstrip("/")

# Free tiers only. Limits change often: the rpm values sit at or below the
# free limits checked on 2026-10-27 (ADR 0040). Their keys are free and need no card.
ENDPOINTS: dict[str, Endpoint] = {
    "ollama": Endpoint("ollama", f"{OLLAMA_URL}/v1", local=True),
    "groq": Endpoint("groq", "https://api.groq.com/openai/v1", "GROQ_API_KEY", rpm=30),
    "gemini": Endpoint(
        "gemini",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "GEMINI_API_KEY",
        rpm=10,
    ),
    "openrouter": Endpoint(
        "openrouter", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", rpm=20
    ),
}


def resolve_model(model: str) -> tuple[Endpoint, str]:
    """Split `endpoint/model` into the endpoint and the model name it expects.

    Only the first `/` splits, so model names may contain `/` themselves.
    """
    name, sep, rest = model.partition("/")
    if not sep or not rest:
        raise ValueError(
            f"Write the model as endpoint/model, e.g. ollama/qwen2.5:7b (got {model!r})."
        )
    if name not in ENDPOINTS:
        known = ", ".join(sorted(ENDPOINTS))
        raise ValueError(f"Unknown endpoint {name!r} in {model!r}. Known: {known}.")
    return ENDPOINTS[name], rest


def request_body(request: ChatRequest, model_name: str) -> dict[str, Any]:
    """The JSON body for POST /chat/completions."""
    body: dict[str, Any] = {
        "model": model_name,
        "messages": [{"role": m.role, "content": m.content} for m in request.messages],
        "temperature": request.temperature,
        "stream": False,
    }
    if request.max_tokens is not None:
        body["max_tokens"] = request.max_tokens
    if request.seed is not None:
        body["seed"] = request.seed
    if request.reasoning_effort is not None:
        body["reasoning_effort"] = request.reasoning_effort
    return body
