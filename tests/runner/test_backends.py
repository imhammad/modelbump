"""Tests for endpoints and request bodies."""

import pytest

from modelbump.runner import ENDPOINTS, ChatRequest, Endpoint, RunnerError, resolve_model
from modelbump.runner.backends import request_body


def test_resolve_model_splits_on_the_first_slash_only() -> None:
    endpoint, name = resolve_model("ollama/library/qwen2.5:7b")
    assert endpoint.name == "ollama"
    assert name == "library/qwen2.5:7b"


@pytest.mark.parametrize("model", ["qwen2.5:7b", "ollama/", "/qwen2.5:7b"])
def test_resolve_model_needs_endpoint_and_model(model: str) -> None:
    with pytest.raises(ValueError, match=r"endpoint/model|Unknown endpoint"):
        resolve_model(model)


def test_resolve_model_rejects_unknown_endpoints() -> None:
    with pytest.raises(ValueError, match="Unknown endpoint 'paid'"):
        resolve_model("paid/gpt-9")


def test_request_body_sends_only_the_options_that_are_set() -> None:
    plain = request_body(ChatRequest.ask("ollama/m", "hi"), "m")
    assert plain == {
        "model": "m",
        "messages": [{"role": "user", "content": "hi"}],
        "temperature": 0.0,
        "stream": False,
    }
    full = request_body(
        ChatRequest.ask("ollama/m", "hi", "be brief", temperature=0.7, max_tokens=5, seed=3),
        "m",
    )
    assert full["messages"][0] == {"role": "system", "content": "be brief"}
    assert (full["temperature"], full["max_tokens"], full["seed"]) == (0.7, 5, 3)


def test_endpoint_reads_its_key_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    endpoint = Endpoint("free", "https://example.test/v1", api_key_env="FREE_KEY")
    monkeypatch.delenv("FREE_KEY", raising=False)
    with pytest.raises(RunnerError, match="Set FREE_KEY"):
        endpoint.headers()
    monkeypatch.setenv("FREE_KEY", "abc")
    assert endpoint.headers() == {"Authorization": "Bearer abc"}
    assert Endpoint("local", "http://localhost/v1").headers() == {}


def test_request_body_sends_reasoning_effort_but_not_cache_only_fields() -> None:
    request = ChatRequest.ask("ollama/m", "hi", reasoning_effort="none", sample=3)
    body = request_body(request, "m")
    assert body["reasoning_effort"] == "none"
    assert "sample" not in body
    assert "model_version" not in body


def test_every_endpoint_is_free_and_cloud_ones_are_paced() -> None:
    assert set(ENDPOINTS) == {"ollama", "groq", "gemini", "openrouter"}
    assert ENDPOINTS["ollama"].local
    assert ENDPOINTS["ollama"].api_key_env is None
    for name, endpoint in ENDPOINTS.items():
        assert endpoint.name == name
        if name == "ollama":
            continue
        assert not endpoint.local
        assert endpoint.base_url.startswith("https://")
        assert endpoint.api_key_env == f"{name.upper()}_API_KEY"
        assert endpoint.rpm is not None
        assert 0 < endpoint.rpm <= 30


def test_resolve_model_keeps_publisher_prefixes_for_cloud_models() -> None:
    endpoint, name = resolve_model("openrouter/meta-llama/llama-3.3-8b-instruct:free")
    assert endpoint.name == "openrouter"
    assert name == "meta-llama/llama-3.3-8b-instruct:free"
