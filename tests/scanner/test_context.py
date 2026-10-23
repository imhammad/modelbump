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
        ("main.go", 'model := "gpt-4o"\n', Place(Context.TEXT)),
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
        ("a.ts", "typescript"),
        ("a.mts", "typescript"),
        ("a.tsx", "tsx"),
        ("a.js", "tsx"),
        ("a.cjs", "tsx"),
        ("a.go", "text"),
        ("a.ipynb", "text"),
        ("env.example", "config"),
        ("config.exs", "text"),
        ("index.html", "text"),
    ],
)
def test_file_kind(path: str, kind: str) -> None:
    assert file_kind(path) == kind


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (
            'await openai.chat.completions.create({ model: "gpt-4o", messages });',
            Place(Context.CALL_ARGUMENT, "openai.chat.completions.create({model})"),
        ),
        (
            "const llm = new ChatOpenAI({ modelName: 'gpt-4o' });",
            Place(Context.CALL_ARGUMENT, "new ChatOpenAI({modelName})"),
        ),
        ("const m = google(`gemini-2.5-pro`);", Place(Context.CALL_ARGUMENT, "google(argument 1)")),
        ('const MODEL = "gpt-4o";', Place(Context.ASSIGNMENT, "MODEL")),
        ('config.model = "gpt-4o";', Place(Context.ASSIGNMENT, "config.model")),
        ('const model = process.env.MODEL ?? "gpt-4o";', Place(Context.ASSIGNMENT, "model")),
        ('const MODEL = ("gpt-4o");', Place(Context.ASSIGNMENT, "MODEL")),
        ('function ask(q, model = "gpt-4o") {}', Place(Context.ASSIGNMENT, "model")),
        ('const ask = ({ model = "gpt-4o" }) => model;', Place(Context.ASSIGNMENT, "model")),
        ('class Bot { model = "gpt-4o"; }', Place(Context.ASSIGNMENT, "model")),
        ('const cfg = { "model": "gpt-4o" };', Place(Context.STRING, "model")),
        ('const models = ["gpt-4o"];', Place(Context.STRING)),
        ("// was gpt-4o", Place(Context.COMMENT)),
        ("/** Uses gpt-4o. */", Place(Context.COMMENT)),
        ('const el = <Chat model="gpt-4o" />;', Place(Context.STRING, "model")),
    ],
)
def test_javascript_places(code: str, expected: Place) -> None:
    assert place_of("app.jsx", code + "\n") == [expected]


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ('const MODEL: string = "gpt-4o";', Place(Context.ASSIGNMENT, "MODEL")),
        ('const MODEL = "gpt-4o" as const;', Place(Context.ASSIGNMENT, "MODEL")),
        (
            'function ask(q: string, model: string = "gpt-4o") {}',
            Place(Context.ASSIGNMENT, "model"),
        ),
        (
            'function ask(model?: string) {} ask("gpt-4o");',
            Place(Context.CALL_ARGUMENT, "ask(argument 1)"),
        ),
        ('type Model = "gpt-4o" | "o3";', Place(Context.STRING)),
        ('const x = <string>"gpt-4o";', Place(Context.STRING)),  # a cast, not JSX, in .ts
    ],
)
def test_typescript_places(code: str, expected: Place) -> None:
    found = place_of("app.ts", code + "\n")
    assert found[0] == expected


@pytest.mark.parametrize(
    ("path", "text", "expected"),
    [
        # Whole-line comments in files without a parser.
        ("main.go", "// Some models (gpt-4o) do not stream.\n", Place(Context.COMMENT)),
        ("Provider.swift", '/// let ai = Provider(model: "gpt-4o")\n', Place(Context.COMMENT)),
        ("Agent.php", "  # uses gpt-4o\n", Place(Context.COMMENT)),
        ("helper.go", " * Defaults to gpt-4o.\n", Place(Context.COMMENT)),
        (".env.example", "# PLUGIN_MODELS=gpt-4o\n", Place(Context.COMMENT)),
        ("env.example", "# MODEL=gpt-4o\n", Place(Context.COMMENT)),
        ("config.yaml", "# model: gpt-4o\n", Place(Context.COMMENT)),
        ("config.exs", '# config :app, model: "gpt-4o"\n', Place(Context.COMMENT)),
        ("index.html", "<!-- gpt-4o -->\n", Place(Context.COMMENT)),
        # A comment after code does not make the line a comment.
        ("main.go", 'model := "gpt-4o" // cheap\n', Place(Context.TEXT)),
        ("run.sh", 'python app.py --model "gpt-4o"\n', Place(Context.TEXT)),
        # JSON has no comments, and notebooks are JSON.
        ("flow.json", '// "gpt-4o"\n', Place(Context.CONFIG)),
        ("nb.ipynb", '"# gpt-4o"\n', Place(Context.PROSE)),
        # Price and limit tables.
        ("pricing.py", 'PRICES = {\n    "gpt-4o": (2.50, 10.00),\n}\n', Place(Context.TABLE)),
        ("tokens.js", "const t = {\n  'gpt-4o': 128000,\n};\n", Place(Context.TABLE)),
        (
            "tx.js",
            "const t = {\n  'gpt-4o': { prompt: 1.1, completion: 4.4 },\n};\n",
            Place(Context.TABLE),
        ),
        ("prices.json", '{"gpt-4o": 0.5}\n', Place(Context.TABLE)),
        ("rates.php", "$r = ['gpt-4o' => 2.5];\n", Place(Context.TABLE)),
        # A display name or a mapping to another ID is not a table.
        ("names.py", 'NAMES = {\n    "gpt-4o": "GPT-4o",\n}\n', Place(Context.STRING)),
        ("cfg.json", '{"model": "gpt-4o", "max_tokens": 100}\n', Place(Context.CONFIG)),
        # IDs inside sentences.
        (
            "svc.py",
            'log.info("Model to use (default: gpt-4o)")\n',
            Place(Context.PROSE),
        ),
        (
            "manifest.json",
            '{"help": "Native image model. gemini-2.5-pro = best"}\n',
            Place(Context.PROSE),
        ),
        ("main.go", 'fmt.Println("calling gpt-4o now")\n', Place(Context.PROSE)),
        # Code stored in a string keeps its place: notebooks and saved flows.
        (
            "nb.ipynb",
            '    "kernel.add(OpenAIChatCompletion(\\"gpt-4o\\", key))\\n",\n',
            Place(Context.TEXT),
        ),
        # A plain ID string, or one with a provider prefix, is not prose.
        (
            "svc.py",
            'client.create(model="openai/gpt-4o")\n',
            Place(Context.CALL_ARGUMENT, "client.create(model=)"),
        ),
    ],
)
def test_describing_rules(path: str, text: str, expected: Place) -> None:
    assert place_of(path, text) == [expected]


def test_comments_and_docstrings_are_not_changed_by_the_rules() -> None:
    assert place_of("a.py", "# price: 'gpt-4o': 2.5\n") == [Place(Context.COMMENT)]


def test_an_unclosed_quote_is_not_a_string() -> None:
    assert place_of("main.go", 'x := "gpt-4o\n') == [Place(Context.TEXT)]
