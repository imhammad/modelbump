"""Find model IDs in text, one line at a time (ADR 0023).

A model ID is written as one unbroken run of letters, digits, dots, dashes
and underscores, such as ``gpt-4o-mini`` or ``claude-3-haiku-20240307``. The
finder splits each line into such runs and keeps a run when it is:

1. an ID in the retirement registry, exactly as written (case matters), or
2. shaped like a model ID from a provider we track: a lowercase ``gpt-``,
   ``chatgpt-``, ``claude-``, ``gemini-`` or ``text-embedding-`` name with
   at least one digit, or an OpenAI ``o1``/``o3``/``o4`` name.

The digit rule keeps out names such as ``gpt-tokenizer`` and ``claude-code``,
and the case rule keeps out prose such as "GPT-4". A few registry IDs are
plain words (``ada``, ``davinci``); those count only when they are a whole
quoted string, as in ``model="davinci"``.

Wrapped forms are found too: ``anthropic.claude-3-haiku-20240307-v1`` yields
the part after the dot, and ``openai/gpt-4o`` yields ``gpt-4o``.
"""

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

_RUN = re.compile(r"[A-Za-z0-9._-]+")
_SHAPE = re.compile(
    r"(?:gpt|chatgpt|claude|gemini|text-embedding)-[a-z0-9.-]*[0-9][a-z0-9.-]*"
    r"|o[1-9](?:-[a-z0-9.-]+)?"
)
_QUOTES = "\"'`"
_TRAILING = "._-"


@dataclass(frozen=True, slots=True)
class IdMatch:
    """One model ID found in a text."""

    line: int
    """Line number, starting at 1."""
    column: int
    """Column of the first character, starting at 1."""
    model_id: str
    in_registry: bool


class ModelIdFinder:
    """Find model IDs in text, knowing which IDs the registry lists."""

    def __init__(self, registry_ids: Iterable[str]) -> None:
        self._known = frozenset(registry_ids)

    def find(self, text: str) -> Iterator[IdMatch]:
        """Yield every model ID in ``text``, in reading order."""
        for line_no, line in enumerate(text.splitlines(), start=1):
            for run in _RUN.finditer(line):
                hit = self._match_run(line, run.start(), run.group())
                if hit is not None:
                    start, model_id = hit
                    yield IdMatch(line_no, start + 1, model_id, model_id in self._known)

    def _match_run(self, line: str, start: int, run: str) -> tuple[int, str] | None:
        for offset in _candidate_starts(run):
            candidate = run[offset:].rstrip(_TRAILING)
            if self._accept(line, start + offset, candidate):
                return start + offset, candidate
        return None

    def _accept(self, line: str, pos: int, candidate: str) -> bool:
        if not candidate:
            return False
        if candidate in self._known:
            return _has_digit(candidate) or _is_quoted(line, pos, len(candidate))
        return _SHAPE.fullmatch(candidate) is not None


def _candidate_starts(run: str) -> Iterator[int]:
    """Offsets where an ID may start: the run itself, and after each ``.`` + letter."""
    yield 0
    for i, char in enumerate(run[:-1]):
        if char == "." and run[i + 1].isalpha():
            yield i + 1


def _has_digit(text: str) -> bool:
    return any(char.isdigit() for char in text)


def _is_quoted(line: str, pos: int, length: int) -> bool:
    end = pos + length
    if pos == 0 or end >= len(line):
        return False
    quote = line[pos - 1]
    return quote in _QUOTES and line[end] == quote
