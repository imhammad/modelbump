"""What goes into a model call and what comes back."""

from dataclasses import dataclass
from typing import Literal

Role = Literal["system", "user", "assistant"]


class RunnerError(Exception):
    """A call failed for good: a non-retryable error, or every attempt failed."""


@dataclass(frozen=True)
class Message:
    """One chat message."""

    role: Role
    content: str


@dataclass(frozen=True)
class ChatRequest:
    """One model call.

    `model` is written as `endpoint/model`, for example `ollama/qwen2.5:7b`.
    Everything that can change the answer lives here, so the cache can hash a
    request into its key (ADR 0037). `sample` numbers repeated draws of the
    same request (0, 1, 2, ...): it is part of the cache key but is not sent
    to the model. `reasoning_effort` turns a thinking model's reasoning down
    or off (`none`, `low`, `medium`, `high`). `model_version` names the exact
    weights, such as an Ollama digest (ADR 0039); it is part of the cache key
    but is not sent either.
    """

    model: str
    messages: tuple[Message, ...]
    temperature: float = 0.0
    max_tokens: int | None = None
    seed: int | None = None
    sample: int = 0
    reasoning_effort: str | None = None
    model_version: str = ""

    @classmethod
    def ask(
        cls,
        model: str,
        prompt: str,
        system: str | None = None,
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        seed: int | None = None,
        sample: int = 0,
        reasoning_effort: str | None = None,
    ) -> "ChatRequest":
        """A request with one user message and an optional system message."""
        messages = [Message("user", prompt)]
        if system is not None:
            messages.insert(0, Message("system", system))
        return cls(model, tuple(messages), temperature, max_tokens, seed, sample, reasoning_effort)


@dataclass(frozen=True)
class ChatResult:
    """The model's answer and what it took to get it.

    A result read from the cache has `cached=True`, `attempts=0` and `seconds=0`.
    """

    text: str
    model: str
    input_tokens: int
    output_tokens: int
    finish_reason: str
    attempts: int
    seconds: float
    cached: bool = False
