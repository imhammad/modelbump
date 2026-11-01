"""Tests for finding model IDs in text."""

import re

import pytest

from modelbump.registry import load_registry
from modelbump.scanner import IdMatch, ModelIdFinder

REGISTRY_IDS = ["claude-3-haiku-20240307", "gpt-3.5-turbo-0613", "o1-preview", "davinci", "ada"]


@pytest.fixture
def finder() -> ModelIdFinder:
    return ModelIdFinder(REGISTRY_IDS)


def ids(finder: ModelIdFinder, text: str) -> list[str]:
    return [match.model_id for match in finder.find(text)]


def test_registry_id_with_its_position(finder: ModelIdFinder) -> None:
    text = 'import anthropic\nclient.messages.create(model="claude-3-haiku-20240307")\n'
    assert list(finder.find(text)) == [IdMatch(2, 31, "claude-3-haiku-20240307", True)]


@pytest.mark.parametrize(
    "model_id",
    [
        "gpt-4o",
        "gpt-4o-mini-2024-07-18",
        "gpt-4.1",
        "chatgpt-4o-latest",
        "claude-sonnet-4-5",
        "claude-opus-4-1-20250805",
        "gemini-2.5-flash",
        "gemini-1.5-pro-002",
        "text-embedding-3-small",
        "o1",
        "o3-mini",
        "o4-mini-2025-04-16",
    ],
)
def test_ids_shaped_like_a_model_are_found(finder: ModelIdFinder, model_id: str) -> None:
    assert list(finder.find(f'model = "{model_id}"')) == [IdMatch(1, 10, model_id, False)]


@pytest.mark.parametrize(
    "text",
    [
        "pip install gpt-tokenizer",  # no digit: a package, not a model
        "npx claude-code",
        "We compared GPT-4 with Claude 3.",  # prose, not an ID
        "MyGpt-4 = 1",
        "my-gpt-4o",  # part of a longer name
        "gpt_4o = 1",  # underscores are Python names
        "x = o1_count",
        "level: -O3",
        "x = ...",
    ],
)
def test_names_that_are_not_model_ids_are_ignored(finder: ModelIdFinder, text: str) -> None:
    assert ids(finder, text) == []


def test_plain_word_ids_count_only_when_quoted(finder: ModelIdFinder) -> None:
    assert ids(finder, 'engine="davinci"') == ["davinci"]
    assert ids(finder, "engine='ada'") == ["ada"]
    assert ids(finder, "Ada Lovelace and davinci were here, ada") == []
    assert ids(finder, '"davinci-like"') == []


def test_wrapped_forms_yield_the_model_id(finder: ModelIdFinder) -> None:
    assert ids(finder, '"anthropic.claude-3-haiku-20240307-v1:0"') == ["claude-3-haiku-20240307-v1"]
    assert ids(finder, "model: openai/gpt-4o") == ["gpt-4o"]
    assert ids(finder, "models/gemini-2.0-flash") == ["gemini-2.0-flash"]
    assert ids(finder, 'model="claude-3-5-sonnet@20240620"') == ["claude-3-5-sonnet@20240620"]
    assert ids(finder, "user@20240620 claude-x@2024") == []


def test_dots_inside_an_id_are_kept(finder: ModelIdFinder) -> None:
    assert ids(finder, "MODEL=gpt-3.5-turbo-0613") == ["gpt-3.5-turbo-0613"]
    assert ids(finder, "Use gpt-4.1.") == ["gpt-4.1"]


def test_several_ids_on_one_line(finder: ModelIdFinder) -> None:
    text = 'MODELS = ["gpt-4o", "o1-preview", "claude-3-haiku-20240307"]'
    assert [(m.column, m.model_id, m.in_registry) for m in finder.find(text)] == [
        (12, "gpt-4o", False),
        (22, "o1-preview", True),
        (36, "claude-3-haiku-20240307", True),
    ]


def test_every_shipped_registry_id_is_found_when_quoted() -> None:
    registry_ids = [model_id for _, model in load_registry() for model_id in model.all_ids()]
    finder = ModelIdFinder(registry_ids)
    for model_id in registry_ids:
        assert ids(finder, f'model="{model_id}"') == [model_id], model_id


def test_quick_line_check_finds_the_same_ids() -> None:
    # The finder skips lines that hold no registry ID and no provider prefix
    # (ADR 0073). With the check turned off it must find exactly the same.
    known = [model_id for _, model in load_registry() for model_id in model.all_ids()]
    fast = ModelIdFinder(known)
    slow = ModelIdFinder(known)
    slow._hint = re.compile("")  # matches every line
    text = "\n".join(
        [
            "x = 1  # nothing here",
            'model = "anthropic.claude-3-haiku-20240307-v1:0"',
            "metadata = {'ada': 'davinci', 'k': \"ada\"}",
            "openai/gpt-4o and o3-mini, foo1 bar.o1-preview",
            "",
            *[f'M{n} = "{model_id}"' for n, model_id in enumerate(known)],
            "gemini-2.5-flash@20250101 text-embedding-3-small chatgpt-4o-latest",
        ]
    )
    assert list(fast.find(text)) == list(slow.find(text))
    assert len(list(fast.find(text))) > len(known)


def test_text_without_any_hint_is_skipped_whole(finder: ModelIdFinder) -> None:
    assert ids(finder, "def f(x):\n    return x + 1\n" * 100) == []
    assert ids(finder, "\n" * 50 + 'M = "claude-3-haiku-20240307"') == ["claude-3-haiku-20240307"]
    assert next(finder.find("\n" * 50 + 'M = "o1"')).line == 51
