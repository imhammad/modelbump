"""Score one answer in [0, 1] against what the old model did (ADR 0052).

A migration has no answer key: the app worked with the old model, so the old
model's answers are the reference. :func:`build_reference` reads a few of them
(reference samples, kept apart from the samples that are compared), and
:func:`score` checks a new answer against that reference with the checks of
the call's :class:`~modelbump.oracles.choose.OutputKind`:

- JSON: the answer parses, has the same top-level type, has each key the old
  answers mostly had, with the same JSON type, and keeps each value the old
  answers always agreed on.
- Label: the answer is one of the allowed labels and is the label the old
  model mostly gave. The score is 1 or 0: a label is right or wrong.
- Text: the answer is not empty, is not a refusal (unless the old answers
  were), is about as long as the old answers, keeps their list or code
  format, and keeps a word or sentence limit the prompt states.

Free text needs a judge as well; that comes in a later step.
"""

import json
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from modelbump.oracles.choose import OracleChoice, OutputKind, normalize_label

LENGTH_LOW = 0.5
"""A text answer may be down to half as long as the shortest old answer..."""
LENGTH_HIGH = 2.0
"""...and up to twice as long as the longest."""

_FENCE = re.compile(r"```(?:json)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
_REFUSAL = re.compile(
    r"\b(?:i can(?:no|')t (?:help|assist|do)|i(?: am|'m) (?:sorry|unable)|"
    r"i (?:won't|will not) (?:help|be able)|as an ai)\b",
    re.IGNORECASE,
)
_BULLET = re.compile(r"^\s*(?:[-*•])\s+\S", re.MULTILINE)
_NUMBERED = re.compile(r"^\s*\d+[.)]\s+\S", re.MULTILINE)
_LIMIT = re.compile(r"\bat most (\d+) (words?|sentences?)\b", re.IGNORECASE)
_SENTENCE_END = re.compile(r"[.!?]+(?:\s|$)")

_MISSING = object()


@dataclass(frozen=True, slots=True)
class Check:
    """One named check and whether the answer passed it."""

    name: str
    passed: bool


@dataclass(frozen=True, slots=True)
class Score:
    """An answer's score in [0, 1] and the checks behind it."""

    value: float
    checks: tuple[Check, ...]

    @property
    def failed(self) -> tuple[str, ...]:
        """The names of the checks the answer failed."""
        return tuple(check.name for check in self.checks if not check.passed)


@dataclass(frozen=True, slots=True)
class Reference:
    """What the old model's answers had in common, for one test case."""

    choice: OracleChoice
    answers: int
    """How many old answers this was built from."""
    json_type: str | None = None
    keys: tuple[tuple[str, str], ...] = ()
    """``(key, JSON type)`` the old answers mostly had, for a JSON object."""
    fixed: tuple[tuple[str, Any], ...] = ()
    """Keys whose value was the same in every old answer, with that value."""
    label: str | None = None
    """The label most old answers gave, if more than half gave it."""
    words: tuple[int, int] | None = None
    """Fewest and most words in the old answers."""
    formats: tuple[str, ...] = ()
    """``bullets``, ``numbered`` or ``code`` when every old answer had it."""
    refusals: bool = False
    """True when any old answer was a refusal."""
    limit: tuple[int, str] | None = None
    """``(n, "words" | "sentences")`` from "at most n words" in the prompt."""


def parse_json(text: str) -> Any:
    """The JSON value in an answer, even inside a code fence or after some prose.

    Returns the missing marker (not None, which is valid JSON) when there is none.
    """
    fenced = _FENCE.search(text)
    candidates = [fenced.group(1)] if fenced else []
    candidates.append(text)
    decoder = json.JSONDecoder()
    for candidate in candidates:
        candidate = candidate.strip()
        for start, char in enumerate(candidate):
            if char in "{[":
                try:
                    return decoder.raw_decode(candidate, start)[0]
                except json.JSONDecodeError:
                    continue
    return _MISSING


def has_json(text: str) -> bool:
    """True when the answer holds a JSON object or array."""
    return parse_json(text) is not _MISSING


def json_type(value: Any) -> str:
    """The JSON type name of a parsed value."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "null"


def find_label(text: str, labels: Sequence[str]) -> str | None:
    """The allowed label an answer gives, or None.

    The whole answer may be the label ("Bug."), or the answer may name
    exactly one of the labels as a word ("The label is bug.").
    """
    answer = normalize_label(text)
    if answer in labels:
        return answer
    named = [
        label for label in labels if re.search(rf"(?<![\w-]){re.escape(label)}(?![\w-])", answer)
    ]
    return named[0] if len(named) == 1 else None


def _word_count(text: str) -> int:
    return len(text.split())


def _sentence_count(text: str) -> int:
    return len([s for s in _SENTENCE_END.split(text.strip()) if s.strip()])


def _formats(text: str) -> set[str]:
    found = set()
    if _BULLET.search(text):
        found.add("bullets")
    if _NUMBERED.search(text):
        found.add("numbered")
    if "```" in text:
        found.add("code")
    return found


def _limit(prompt: str) -> tuple[int, str] | None:
    match = _LIMIT.search(prompt)
    if match is None:
        return None
    unit = "words" if match.group(2).lower().startswith("word") else "sentences"
    return int(match.group(1)), unit


def build_reference(
    choice: OracleChoice, old_answers: Sequence[str], prompt: str = ""
) -> Reference:
    """What the old answers to one test case had in common.

    ``prompt`` is the case's full prompt text, read for a stated length limit.
    """
    if not old_answers:
        raise ValueError("A reference needs at least one old answer.")
    count = len(old_answers)
    if choice.kind is OutputKind.TOOLS:
        raise ValueError("Tool calls are not scored yet (ADR 0052).")
    if choice.kind is OutputKind.JSON:
        parsed = [v for v in (parse_json(a) for a in old_answers) if v is not _MISSING]
        if not parsed:
            return Reference(choice, count)
        top = Counter(json_type(v) for v in parsed).most_common(1)[0][0]
        objects = [v for v in parsed if isinstance(v, dict)]
        keys: list[tuple[str, str]] = []
        fixed: list[tuple[str, Any]] = []
        if top == "object":
            seen = Counter(key for value in objects for key in value)
            for key, times in seen.items():
                if times * 2 <= len(objects):
                    continue
                types = Counter(json_type(v[key]) for v in objects if key in v)
                keys.append((key, types.most_common(1)[0][0]))
                values = [v.get(key, _MISSING) for v in objects]
                if len(objects) > 1 and all(value == values[0] for value in values):
                    fixed.append((key, values[0]))
        return Reference(choice, count, json_type=top, keys=tuple(keys), fixed=tuple(fixed))
    if choice.kind is OutputKind.LABEL:
        given = [find_label(a, choice.labels) for a in old_answers]
        top_label, times = Counter(given).most_common(1)[0]
        label = top_label if top_label is not None and times * 2 > count else None
        return Reference(choice, count, label=label)
    words = [_word_count(a) for a in old_answers]
    shared = set.intersection(*(_formats(a) for a in old_answers))
    return Reference(
        choice,
        count,
        words=(min(words), max(words)),
        formats=tuple(sorted(shared)),
        refusals=any(_REFUSAL.search(a) for a in old_answers),
        limit=_limit(prompt),
    )


def _a(kind: str) -> str:
    return f"an {kind}" if kind[0] in "aeiou" else f"a {kind}"


def _result(checks: list[Check]) -> Score:
    passed = sum(check.passed for check in checks)
    return Score(passed / len(checks) if checks else 1.0, tuple(checks))


def _score_json(reference: Reference, answer: str) -> Score:
    value = parse_json(answer)
    if value is _MISSING:
        return Score(0.0, (Check("valid JSON", False),))
    checks = [Check("valid JSON", True)]
    if reference.json_type is not None:
        checks.append(
            Check(f"is a JSON {reference.json_type}", json_type(value) == reference.json_type)
        )
    data = value if isinstance(value, dict) else {}
    for key, kind in reference.keys:
        checks.append(Check(f"has {key}", key in data))
        checks.append(Check(f"{key} is {_a(kind)}", key in data and json_type(data[key]) == kind))
    for key, expected in reference.fixed:
        checks.append(Check(f"{key} same as before", data.get(key, _MISSING) == expected))
    return _result(checks)


def _score_label(reference: Reference, answer: str) -> Score:
    label = find_label(answer, reference.choice.labels)
    checks = [Check("one of the labels", label is not None)]
    if reference.label is not None:
        same = label == reference.label
        checks.append(Check(f"same label as before ({reference.label})", same))
        return Score(1.0 if same else 0.0, tuple(checks))
    return Score(1.0 if label is not None else 0.0, tuple(checks))


def _score_text(reference: Reference, answer: str) -> Score:
    words = _word_count(answer)
    checks = [Check("not empty", words > 0)]
    if not reference.refusals:
        checks.append(Check("not a refusal", not _REFUSAL.search(answer)))
    if reference.words is not None:
        low, high = reference.words
        checks.append(Check("length like before", LENGTH_LOW * low <= words <= LENGTH_HIGH * high))
    found = _formats(answer)
    checks.extend(Check(f"keeps {name}", name in found) for name in reference.formats)
    if reference.limit is not None:
        limit, unit = reference.limit
        count = words if unit == "words" else _sentence_count(answer)
        checks.append(Check(f"at most {limit} {unit}", count <= limit))
    return _result(checks)


def score(reference: Reference, answer: str) -> Score:
    """Score a new (or old) answer against the reference, in [0, 1]."""
    kind = reference.choice.kind
    if kind is OutputKind.TOOLS:
        raise ValueError("Tool calls are not scored yet (ADR 0052).")
    if kind is OutputKind.JSON:
        return _score_json(reference, answer)
    if kind is OutputKind.LABEL:
        return _score_label(reference, answer)
    return _score_text(reference, answer)
