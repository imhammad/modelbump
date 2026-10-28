"""Tests for test inputs from the app's own callers (ADR 0050)."""

import json
from pathlib import Path

import pytest

from modelbump.synth.cases import MAX_ROWS, CaseResult, SiteCases, find_cases
from modelbump.synth.report import cases_summary, render_cases_json, render_cases_text

APP = (
    'MODEL = "gpt-4o-mini"\n'
    "def classify(client, ticket, labels='bug, feature'):\n"
    "    return client.chat.completions.create(model=MODEL, messages=[\n"
    '        {"role": "system", "content": f"Pick one of: {labels}."},\n'
    '        {"role": "user", "content": f"Ticket: {ticket}"},\n'
    "    ])\n"
)


def run(root: Path, files: dict[str, str], **options: object) -> CaseResult:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return find_cases(root, **options)  # type: ignore[arg-type]


def only(result: CaseResult) -> SiteCases:
    (entry,) = result.sites
    return entry


def test_a_test_that_calls_the_function_gives_a_complete_case(tmp_path: Path) -> None:
    test = "from app import classify\ndef test_it():\n    classify(None, 'App crashes')\n"
    entry = only(run(tmp_path, {"app.py": APP, "tests/test_app.py": test}, skip_tests=True))
    (case,) = entry.cases
    assert case.source == "tests/test_app.py:3"
    assert case.values == (("ticket", "App crashes"),)
    assert case.complete
    assert case.messages == (
        ("system", "Pick one of: bug, feature."),
        ("user", "Ticket: App crashes"),
    )
    assert entry.site.slots == ("labels", "ticket")


def test_values_through_names_constants_and_keywords(tmp_path: Path) -> None:
    other = (
        "from app import classify\n"
        'TEXT = "From a constant"\n'
        "def main():\n"
        '    t = "From a variable"\n'
        "    classify(None, t)\n"
        "    classify(None, ticket=TEXT, labels='a, b')\n"
        "    classify(None, ticket=3)\n"
    )
    cases = only(run(tmp_path, {"app.py": APP, "main.py": other})).cases
    assert [c.values for c in cases] == [
        (("ticket", "From a variable"),),
        (("labels", "a, b"), ("ticket", "From a constant")),
        (("ticket", "3"),),
    ]
    assert cases[1].messages[0] == ("system", "Pick one of: a, b.")


def test_a_caller_without_values_gives_no_case(tmp_path: Path) -> None:
    other = (
        "from app import classify\n"
        "def wrapper(client, text):\n"
        "    return classify(client, text)\n"
        "def spread(args):\n"
        "    return classify(*args)\n"
    )
    assert only(run(tmp_path, {"app.py": APP, "main.py": other})).cases == ()


def test_the_same_values_twice_give_one_case(tmp_path: Path) -> None:
    other = "from app import classify\nclassify(None, 'x')\nclassify(None, 'x')\n"
    assert len(only(run(tmp_path, {"app.py": APP, "main.py": other})).cases) == 1


def test_a_case_with_an_open_slot_is_not_complete(tmp_path: Path) -> None:
    app = (
        "def summarize(client, text, words):\n"
        '    return client.completions.create(model="m", prompt=f"In {words} words: {text}")\n'
    )
    other = "from app import summarize\ndef go(doc):\n    summarize(None, doc, 40)\n"
    (case,) = only(run(tmp_path, {"app.py": app, "main.py": other})).cases
    assert case.values == (("words", "40"),)
    assert not case.complete
    assert case.site.slots == ("doc",)
    with pytest.raises(ValueError, match="open slots"):
        _ = case.messages


def test_a_list_argument_fills_a_join(tmp_path: Path) -> None:
    app = (
        "def summarize(client, lines):\n"
        '    prompt = "Summarize:\\n" + "\\n".join(lines)\n'
        '    return client.completions.create(model="m", prompt=prompt)\n'
    )
    other = "from app import summarize\nsummarize(None, ['a', 'b'])\n"
    (case,) = only(run(tmp_path, {"app.py": app, "main.py": other})).cases
    assert case.values == (("lines", "['a', 'b']"),)
    assert case.messages == (("prompt", "Summarize:\na\nb"),)


def test_methods_called_on_an_instance(tmp_path: Path) -> None:
    app = (
        "class Bot:\n"
        "    def __init__(self, client):\n"
        "        self.client = client\n"
        "    def ask(self, question):\n"
        '        return self.client.completions.create(model="m", prompt=f"Q: {question}")\n'
    )
    other = "from app import Bot\ndef test_bot():\n    bot = Bot(None)\n    bot.ask('Why?')\n"
    (case,) = only(run(tmp_path, {"app.py": app, "tests/test_bot.py": other})).cases
    assert case.messages == (("prompt", "Q: Why?"),)


def test_calls_at_module_level_have_no_cases(tmp_path: Path) -> None:
    app = 'q = input()\nclient.completions.create(model="m", prompt=f"Q: {q}")\n'
    entry = only(run(tmp_path, {"app.py": app}))
    assert (entry.site.slots, entry.cases) == (("q",), ())


# --- pytest.mark.parametrize ----------------------------------------------------------


def parametrized(decorators: str, call: str = "classify(None, ticket)") -> str:
    return (
        "import pytest\n"
        "from app import classify\n"
        "ROWS = ['From ROWS 1', 'From ROWS 2']\n"
        f"{decorators}"
        "def test_it(ticket, labels):\n"
        f"    {call}\n"
    )


def values_of(tmp_path: Path, test: str) -> list[tuple[tuple[str, str], ...]]:
    result = run(tmp_path, {"app.py": APP, "tests/test_app.py": test})
    return [case.values for case in only(result).cases]


def test_parametrize_one_name(tmp_path: Path) -> None:
    test = parametrized('@pytest.mark.parametrize("ticket", ["One", "Two"])\n')
    assert values_of(tmp_path, test) == [(("ticket", "One"),), (("ticket", "Two"),)]


def test_parametrize_several_names_and_pytest_param(tmp_path: Path) -> None:
    test = parametrized(
        '@pytest.mark.parametrize("ticket, labels", [\n'
        '    ("One", "a, b"),\n'
        '    pytest.param("Two", "c, d", id="two"),\n'
        '    ("too", "many", "items"),\n'
        "])\n",
        "classify(None, ticket, labels)",
    )
    assert values_of(tmp_path, test) == [
        (("labels", "a, b"), ("ticket", "One")),
        (("labels", "c, d"), ("ticket", "Two")),
    ]


def test_parametrize_names_as_a_list_and_rows_in_a_constant(tmp_path: Path) -> None:
    test = parametrized('@pytest.mark.parametrize(["ticket"], ROWS)\n')
    assert values_of(tmp_path, test) == [(("ticket", "From ROWS 1"),), (("ticket", "From ROWS 2"),)]


def test_two_parametrize_decorators_multiply(tmp_path: Path) -> None:
    test = parametrized(
        '@pytest.mark.parametrize("ticket", ["One", "Two"])\n'
        '@mark.parametrize("labels", ["x", "y"])\n',
        "classify(None, ticket, labels)",
    )
    assert len(values_of(tmp_path, test)) == 4


def test_parametrize_rows_are_capped_and_give_their_own_lines(tmp_path: Path) -> None:
    rows = ", ".join(f'"T{i}"' for i in range(MAX_ROWS + 10))
    test = parametrized(f'@pytest.mark.parametrize("ticket", [\n    {rows},\n])\n')
    result = run(tmp_path, {"app.py": APP, "tests/test_app.py": test})
    cases = only(result).cases
    assert len(cases) == MAX_ROWS
    assert cases[0].source == "tests/test_app.py:5"


def test_unreadable_parametrize_falls_back_to_the_plain_call(tmp_path: Path) -> None:
    test = parametrized("@pytest.mark.parametrize(NAMES, ROWS)\n", "classify(None, 'Plain')")
    assert values_of(tmp_path, test) == [(("ticket", "Plain"),)]


# --- Reports ----------------------------------------------------------------------------


def demo(tmp_path: Path) -> CaseResult:
    fixed = 'def hello(client):\n    return client.completions.create(model="m", prompt="Hi")\n'
    test = "from app import classify\nclassify(None, 'App crashes')\n"
    return run(
        tmp_path,
        {
            "app.py": APP,
            "fixed.py": fixed,
            "loose.py": APP.replace("classify", "other"),
            "t.py": test,
        },
    )


def test_text_report(tmp_path: Path) -> None:
    assert render_cases_text(demo(tmp_path)).splitlines() == [
        "app.py:3  openai_chat  client.chat.completions.create  model: gpt-4o-mini",
        '  t.py:2  ticket="App crashes"',
        "fixed.py:2  openai_completions  client.completions.create  model: m",
        "  fixed prompt: no slots to fill",
        "loose.py:3  openai_chat  client.chat.completions.create  model: gpt-4o-mini",
        "  no cases (slots: labels, ticket)",
        "Found 1 test case (1 complete) for 1 of 3 LLM calls. 1 with a fixed prompt need no "
        "inputs. No case yet for 1 with slots (loose.py:3).",
    ]


def test_json_report(tmp_path: Path) -> None:
    data = json.loads(render_cases_json(demo(tmp_path)))
    first = data["calls"][0]
    assert first["slots"] == ["labels", "ticket"]
    assert first["cases"] == [
        {
            "source": "t.py:2",
            "values": {"ticket": "App crashes"},
            "complete": True,
            "messages": [
                {"role": "system", "content": "Pick one of: bug, feature."},
                {"role": "user", "content": "Ticket: App crashes"},
            ],
        }
    ]


def test_json_report_of_an_open_case(tmp_path: Path) -> None:
    app = (
        'def f(client, a, b):\n    return client.completions.create(model="m", prompt=f"{a} {b}")\n'
    )
    result = run(
        tmp_path, {"app.py": app, "m.py": "from app import f\ndef g(x):\n    f(None, 'A', x)\n"}
    )
    (case,) = json.loads(render_cases_json(result))["calls"][0]["cases"]
    assert case["open_slots"] == ["x"]
    assert case["parts"][0]["template"] == "A {x}"
    assert "messages" not in case


def test_summary_with_many_waiting_calls(tmp_path: Path) -> None:
    files = {f"m{i}.py": APP for i in range(4)}
    files["bad.py"] = 'print "py2"\n'
    assert cases_summary(run(tmp_path, files)) == (
        "Found 0 test cases (0 complete) for 0 of 4 LLM calls. No case yet for 4 with slots "
        "(m0.py:3, m1.py:3, m2.py:3, ...). 1 file did not parse."
    )
