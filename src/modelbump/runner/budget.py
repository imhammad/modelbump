"""A spending limit for model calls, counted in tokens and requests (ADR 0038).

ModelBump spends no money: local models cost time and free API tiers allow
a fixed number of requests and tokens a day. So the budget counts tokens and
HTTP requests, not dollars. Answers read from the cache cost nothing and are
counted separately, as savings.
"""

from dataclasses import dataclass

from modelbump.runner.types import ChatResult, RunnerError


class BudgetExceeded(RunnerError):
    """The budget ran out before this request could be sent."""


@dataclass(frozen=True)
class Spend:
    """What a run used so far."""

    requests: int
    answers: int
    input_tokens: int
    output_tokens: int
    cached_answers: int
    cached_tokens: int

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class Budget:
    """Stops sending requests once a limit is reached.

    - `max_tokens`: input plus output tokens of real (not cached) answers.
    - `max_requests`: HTTP requests sent, retries included, because free
      tiers count every request.

    A limit is checked before each request is sent. Requests already in
    flight are allowed to finish, so the token total can end slightly above
    `max_tokens` (by at most what the in-flight answers use).
    """

    def __init__(self, max_tokens: int | None = None, max_requests: int | None = None) -> None:
        if max_tokens is not None and max_tokens < 1:
            raise ValueError("max_tokens must be at least 1.")
        if max_requests is not None and max_requests < 1:
            raise ValueError("max_requests must be at least 1.")
        self.max_tokens = max_tokens
        self.max_requests = max_requests
        self._requests = 0
        self._answers = 0
        self._input = 0
        self._output = 0
        self._cached_answers = 0
        self._cached_tokens = 0

    def before_request(self) -> None:
        """Count one request about to be sent, or raise BudgetExceeded."""
        if self.max_requests is not None and self._requests >= self.max_requests:
            raise BudgetExceeded(
                f"Budget reached: {self._requests:,} of {self.max_requests:,} requests sent."
            )
        if self.max_tokens is not None and self._input + self._output >= self.max_tokens:
            raise BudgetExceeded(
                f"Budget reached: {self._input + self._output:,} of "
                f"{self.max_tokens:,} tokens used."
            )
        self._requests += 1

    def record(self, result: ChatResult) -> None:
        """Count an answer: real ones use the budget, cached ones are savings."""
        if result.cached:
            self._cached_answers += 1
            self._cached_tokens += result.input_tokens + result.output_tokens
            return
        self._answers += 1
        self._input += result.input_tokens
        self._output += result.output_tokens

    @property
    def spend(self) -> Spend:
        return Spend(
            requests=self._requests,
            answers=self._answers,
            input_tokens=self._input,
            output_tokens=self._output,
            cached_answers=self._cached_answers,
            cached_tokens=self._cached_tokens,
        )

    def summary(self) -> str:
        """One line for people, e.g. at the end of a run."""
        s = self.spend
        line = (
            f"Spent: {s.requests:,} requests, {s.tokens:,} tokens "
            f"({s.input_tokens:,} in, {s.output_tokens:,} out). "
            f"From cache: {s.cached_answers:,} answers ({s.cached_tokens:,} tokens saved)."
        )
        limits = []
        if self.max_tokens is not None:
            limits.append(f"{s.tokens / self.max_tokens:.0%} of {self.max_tokens:,} tokens")
        if self.max_requests is not None:
            limits.append(f"{s.requests / self.max_requests:.0%} of {self.max_requests:,} requests")
        if limits:
            line += " Budget used: " + ", ".join(limits) + "."
        return line
