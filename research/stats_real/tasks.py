"""Test cases with answers we can compute, so every model answer can be checked (ADR 0046).

Six families of short tasks. Each prompt asks for a short answer, and each
answer is computed by Python, never written by hand, so the oracle is exact.
The families differ in how hard they are for 7-8B models, which spreads pass
rates between 0 and 1. All prompts are made up here: nothing private is sent.
"""

import random
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

WORDS = (
    "apple", "banana", "cherry", "planet", "rocket", "garden", "silver", "window",
    "pencil", "orange", "summer", "winter", "bridge", "candle", "forest", "island",
    "jungle", "kitten", "ladder", "marble", "needle", "office", "parrot", "rabbit",
    "saddle", "tunnel", "violin", "walnut", "yellow", "zipper", "strawberry", "mississippi",
    "committee", "bookkeeper", "balloon", "coffee", "letter", "address", "success",
)  # fmt: skip
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
SYSTEM = "You answer with the answer only: no explanation, no extra words."


@dataclass(frozen=True)
class Task:
    """One test case: a prompt and the answer an exact oracle accepts."""

    id: str
    family: str
    prompt: str
    answer: str


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z]+", text.lower())


def _last_int(text: str) -> str | None:
    numbers = re.findall(r"-?\d+", text.replace(",", ""))
    return numbers[-1] if numbers else None


def _multiply(rng: random.Random, index: int) -> Task:
    a, b = rng.randint(12, 99), rng.randint(102, 999)
    return Task(
        f"multiply-{index:02d}",
        "multiply",
        f"What is {a} times {b}? Reply with the number only.",
        str(a * b),
    )


def _count_letter(rng: random.Random, index: int) -> Task:
    word = rng.choice(WORDS)
    letter = rng.choice(sorted(set(word)))
    return Task(
        f"count-{index:02d}",
        "count",
        f"How many times does the letter '{letter}' appear in the word '{word}'? "
        "Reply with the number only.",
        str(word.count(letter)),
    )


def _reverse(rng: random.Random, index: int) -> Task:
    word = rng.choice(WORDS)
    return Task(
        f"reverse-{index:02d}",
        "reverse",
        f"Write the word '{word}' backwards, letter by letter. Reply with the reversed word only.",
        word[::-1],
    )


def _weekday(rng: random.Random, index: int) -> Task:
    day = date(1990, 1, 1) + timedelta(days=rng.randint(0, 365 * 35))
    return Task(
        f"weekday-{index:02d}",
        "weekday",
        f"What day of the week was {day.day} {day.strftime('%B')} {day.year}? "
        "Reply with the day's name only.",
        WEEKDAYS[day.weekday()],
    )


def _sort(rng: random.Random, index: int) -> Task:
    words = rng.sample(sorted(set(WORDS)), 5)
    return Task(
        f"sort-{index:02d}",
        "sort",
        f"Sort these words alphabetically: {', '.join(words)}. "
        "Reply with the words separated by commas.",
        ", ".join(sorted(words)),
    )


def _last_letters(rng: random.Random, index: int) -> Task:
    words = rng.sample(sorted(set(WORDS)), 4)
    return Task(
        f"letters-{index:02d}",
        "letters",
        f"Take the last letter of each word in '{' '.join(words)}' and join them in order. "
        "Reply with the letters only.",
        "".join(w[-1] for w in words),
    )


FAMILIES: dict[str, Callable[[random.Random, int], Task]] = {
    "multiply": _multiply,
    "count": _count_letter,
    "reverse": _reverse,
    "weekday": _weekday,
    "sort": _sort,
    "letters": _last_letters,
}


def make_tasks(per_family: int, seed: int = 2046) -> list[Task]:
    """`per_family` tasks from each family, the same for the same seed on any machine."""
    if per_family < 1:
        raise ValueError(f"per_family must be at least 1, got {per_family}")
    tasks: list[Task] = []
    for name, make in FAMILIES.items():
        rng = random.Random(f"{seed}-{name}")
        tasks.extend(make(rng, index + 1) for index in range(per_family))
    return tasks


def score(task: Task, text: str) -> float:
    """1.0 if the answer is right, else 0.0. Lenient about case, quotes and full stops."""
    if task.family in ("multiply", "count"):
        return float(_last_int(text) == task.answer)
    words = _words(text)
    if task.family == "weekday":
        named = [w for w in words if w in WEEKDAYS]
        return float(named == [task.answer] or set(named) == {task.answer})
    if task.family == "sort":
        return float(words == _words(task.answer))
    # reverse and letters: one word; allow it to come last, e.g. "Answer: elppa".
    joined = "".join(words)
    return float(joined == task.answer or (bool(words) and words[-1] == task.answer))
