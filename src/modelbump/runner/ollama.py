"""Ask the local Ollama server which models it has, and their exact versions (ADR 0039)."""

from dataclasses import dataclass, replace

import httpx

from modelbump.runner.backends import OLLAMA_URL
from modelbump.runner.types import ChatRequest, RunnerError


@dataclass(frozen=True)
class LocalModel:
    """A model pulled into Ollama."""

    name: str
    digest: str
    size_bytes: int
    family: str
    parameter_size: str
    quantization: str


def list_local_models(
    base_url: str = OLLAMA_URL, transport: httpx.BaseTransport | None = None
) -> list[LocalModel]:
    """Every model Ollama has, sorted by name (GET /api/tags)."""
    try:
        with httpx.Client(timeout=10.0, transport=transport) as client:
            response = client.get(f"{base_url}/api/tags")
    except httpx.HTTPError as error:
        raise RunnerError(f"could not reach {base_url} ({type(error).__name__})") from error
    if response.status_code != 200:
        raise RunnerError(f"{base_url}/api/tags answered HTTP {response.status_code}")
    models = []
    for item in response.json().get("models") or []:
        details = item.get("details") or {}
        models.append(
            LocalModel(
                name=str(item.get("name") or item.get("model") or ""),
                digest=str(item.get("digest") or ""),
                size_bytes=int(item.get("size") or 0),
                family=str(details.get("family") or ""),
                parameter_size=str(details.get("parameter_size") or ""),
                quantization=str(details.get("quantization_level") or ""),
            )
        )
    return sorted(models, key=lambda m: m.name)


def find_model(name: str, models: list[LocalModel]) -> LocalModel | None:
    """The local model called `name`. A name without a tag means `:latest`, as in Ollama."""
    wanted = name if ":" in name else f"{name}:latest"
    for model in models:
        if model.name == wanted:
            return model
    return None


def pin_versions(
    requests: list[ChatRequest],
    base_url: str = OLLAMA_URL,
    transport: httpx.BaseTransport | None = None,
) -> list[ChatRequest]:
    """Fill in `model_version` with the Ollama digest of every `ollama/...` request.

    Then a model re-pulled with new weights under the same name gets new cache
    entries instead of old answers. A model that is not pulled is an error that
    says how to pull it. Other endpoints are left as they are.
    """
    if not any(r.model.startswith("ollama/") for r in requests):
        return list(requests)
    models = list_local_models(base_url, transport)
    pinned = []
    for request in requests:
        if request.model.startswith("ollama/"):
            name = request.model.removeprefix("ollama/")
            found = find_model(name, models)
            if found is None:
                raise RunnerError(
                    f"{request.model}: this model is not pulled. Run: ollama pull {name}"
                )
            request = replace(request, model_version=found.digest)
        pinned.append(request)
    return pinned
