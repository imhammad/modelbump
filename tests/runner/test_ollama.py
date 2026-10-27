"""Tests for listing Ollama models and pinning requests to their digests."""

import httpx
import pytest

from modelbump.runner import (
    ChatRequest,
    RunnerError,
    find_model,
    list_local_models,
    pin_versions,
)

TAGS = {
    "models": [
        {
            "name": "qwen3:8b",
            "model": "qwen3:8b",
            "size": 5_225_388_164,
            "digest": "500a1f067a9f" + "0" * 52,
            "details": {
                "family": "qwen3",
                "parameter_size": "8.2B",
                "quantization_level": "Q4_K_M",
            },
        },
        {
            "name": "qwen2.5:7b",
            "size": 4_683_087_332,
            "digest": "845dbda0ea48" + "1" * 52,
            "details": {
                "family": "qwen2",
                "parameter_size": "7.6B",
                "quantization_level": "Q4_K_M",
            },
        },
        {"name": "llama3.1:latest", "digest": "46e0c10c039e" + "2" * 52},
    ]
}


def tags_server(payload: object = TAGS, status: int = 200) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(status, json=payload)

    return httpx.MockTransport(handle)


def test_list_local_models_reads_the_tags_sorted_by_name() -> None:
    models = list_local_models("http://ollama.test", tags_server())
    assert [m.name for m in models] == ["llama3.1:latest", "qwen2.5:7b", "qwen3:8b"]
    qwen3 = models[2]
    assert (qwen3.family, qwen3.parameter_size, qwen3.quantization) == ("qwen3", "8.2B", "Q4_K_M")
    assert qwen3.size_bytes == 5_225_388_164
    assert models[0].family == ""  # missing details are empty, not an error


def test_list_local_models_with_none_pulled() -> None:
    assert list_local_models("http://ollama.test", tags_server({"models": []})) == []


def test_list_local_models_explains_failures() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(RunnerError, match=r"could not reach http://ollama.test \(ConnectError\)"):
        list_local_models("http://ollama.test", httpx.MockTransport(refuse))
    with pytest.raises(RunnerError, match="HTTP 500"):
        list_local_models("http://ollama.test", tags_server({}, status=500))


def test_find_model_treats_a_bare_name_as_latest() -> None:
    models = list_local_models("http://ollama.test", tags_server())
    assert find_model("llama3.1", models) is not None
    assert find_model("llama3.1:latest", models) is not None
    assert find_model("qwen3", models) is None
    found = find_model("qwen3:8b", models)
    assert found is not None
    assert found.digest.startswith("500a1f067a9f")


def test_pin_versions_fills_in_the_digest_of_ollama_models() -> None:
    requests = [
        ChatRequest.ask("ollama/qwen2.5:7b", "hi"),
        ChatRequest.ask("ollama/qwen3:8b", "hi", reasoning_effort="none"),
        ChatRequest.ask("other/model", "hi"),
    ]
    pinned = pin_versions(requests, "http://ollama.test", tags_server())
    assert pinned[0].model_version.startswith("845dbda0ea48")
    assert pinned[1].model_version.startswith("500a1f067a9f")
    assert pinned[1].reasoning_effort == "none"
    assert pinned[2] == requests[2]
    assert requests[0].model_version == ""  # the originals are unchanged


def test_pin_versions_says_how_to_pull_a_missing_model() -> None:
    with pytest.raises(RunnerError, match=r"not pulled\. Run: ollama pull gemma3:4b"):
        pin_versions(
            [ChatRequest.ask("ollama/gemma3:4b", "hi")], "http://ollama.test", tags_server()
        )


def test_pin_versions_does_not_call_ollama_for_other_endpoints() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Ollama should not be asked")

    requests = [ChatRequest.ask("other/model", "hi")]
    assert pin_versions(requests, "http://ollama.test", httpx.MockTransport(fail)) == requests
