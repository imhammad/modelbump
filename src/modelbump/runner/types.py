"""What goes into a model call and what comes back."""

from dataclasses import dataclass
from typing import Literal

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class Message:
    """One chat message."""

    role: Role
    content: str


@dataclass(frozen=True)
class ChatRequest:
    """One model call.

    `model` is written as `endpoint/model`, for example `ollama/qwen2.5:7b`.
    Everything that can change the answer lives here, so a later step can hash
    a request into a cache key.
    """

    model: str
    messages: tuple[Message, ...]
    temperature: float = 0.0
    max_tokens: int | None = None
    seed: int | None = None

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
    ) -> "ChatRequest":
        """A request with one user message and an optional system message."""
        messages = [Message("user", prompt)]
        if system is not None:
            messages.insert(0, Message("system", system))
        return cls(model, tuple(messages), temperature, max_tokens, seed)


@dataclass(frozen=True)
class ChatResult:
    """The model's answer and what it took to get it."""

    text: str
    model: str
    input_tokens: int
    output_tokens: int
    finish_reason: str
    attempts: int
    seconds: float
