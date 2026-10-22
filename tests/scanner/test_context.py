"""Tests for the place of a model ID in a file."""

import pytest

from modelbump.registry import load_registry
from modelbump.scanner import Context, ModelIdFinder, Place, places
from modelbump.scanner.context import file_kind


def place_of(path: str, text: str) -> list[Place]:
    """Find the IDs in ``text`` and return their places, as the scanner does."""
    registry_ids = [i for _, model in load_registry() for i in model.all_ids()]
    matches = list(ModelIdFinder(registry_ids).find(text))
    return places(path, text, [(m.line, m.column, len(m.model_id)) for m in matches])


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (
            'client.messages.create(model="claude-3-haiku-20240307", max_tokens=5)',
            Place(Context.CALL_ARGUMENT, "client.messages.create(model=)"),
        ),
        (
            'genai.GenerativeModel("gemini-2.5-pro")',
            Place(Context.CALL_ARGUMENT, "genai.GenerativeModel(argument 1)"),
        ),
        (
            'ChatOpenAI(temperature=0, model_name=("gpt-4o"))',
            Place(Context.CALL_ARGUMENT, "ChatOpenAI(model_name=)"),
        ),
        ('MODEL = "gpt-4o"', Place(Context.ASSIGNMENT, "MODEL")),
        ('MODEL: str = "gpt-4o"', Place(Context.ASSIGNMENT, "MODEL")),
        ('self.model = "gpt-4o"', Place(Context.ASSIGNMENT, "self.model")),
        ('def ask(q, model="gpt-4o"): ...', Place(Context.ASSIGNMENT, "model")),
        ('def ask(q, model: str = "gpt-4o"): ...', Place(Context.ASSIGNMENT, "model")),
        ('cfg = {"model": "gpt-4o"}', Place(Context.STRING, "model")),
        ('MODELS = ["gpt-4o"]', Place(Context.STRING)),
        ('"""Talks to gpt-4o."""', Place(Context.DOCSTRING)),
        ("x = 1  # was gpt-4o", Place(Context.COMMENT)),
        ('print "gpt-4o"', Place(Context.STRING)),  # Python 2 still parses
    ],
)
def test_python_places(code: str, expected: Place) -> None:
    assert place_of("app.py", code + "\n") == [expected]


def test_python_places_with_wide_characters_before_the_id() -> None:
    code = 'GREETING = "héllo 😀"; MODEL = "gpt-4o"  # é gpt-4.1\n'
    assert place_of("app.py", code) == [
        Place(Context.ASSIGNMENT, "MODEL"),
        Place(Context.COMMENT),
    ]


def test_long_call_names_keep_their_end() -> None:
    code = 'very.long.chain.of.attributes.that.goes.on.and.on.forever.create(model="gpt-4o")\n'
    [found] = place_of("app.py", code)
    assert found.detail is not None
    assert len(found.detail) == 60
    assert found.detail.startswith("...")
    assert found.detail.endswith(".create(model=)")


@pytest.mark.parametrize(
    ("path", "text", "expected"),
    [
        ("config.yaml", "summary_model: gpt-4o\n", Place(Context.CONFIG, "summary_model")),
        ("config.yaml", "models:\n  - gpt-4o\n", Place(Context.CONFIG)),
        ("settings.json", '{"model": "gpt-4o"}\n', Place(Context.CONFIG)),
        ("settings.json", '  "model": "gpt-4o",\n', Place(Context.CONFIG, "model")),
        ("app.toml", 'model = "gpt-4o"\n', Place(Context.CONFIG, "model")),
        (".env.example", "export OPENAI_MODEL=gpt-4o\n", Place(Context.CONFIG, "OPENAI_MODEL")),
        ("index.ts", 'const model = "gpt-4o";\n', Place(Context.TEXT)),
    ],
)
def test_config_and_text_places(path: str, text: str, expected: Place) -> None:
    assert place_of(path, text) == [expected]


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        ("a.py", "python"),
        ("a.pyi", "python"),
        ("a.YAML", "config"),
        (".env", "config"),
        (".env.local", "config"),
        ("a.ts", "text"),
        ("a.ipynb", "text"),
    ],
)
def test_file_kind(path: str, kind: str) -> None:
    assert file_kind(path) == kind
