"""Tests for the reports of `modelbump prompts`."""

import json

from modelbump.synth import CallSiteResult, extract_calls
from modelbump.synth.report import render_json, render_text, summary_line

SOURCE = (
    'MODEL = "gpt-4o-mini"\n'
    "def ask(q, history):\n"
    "    client.chat.completions.create(model=MODEL, messages=[\n"
    '        {"role": "system", "content": "Be brief.\\nUse {braces}."},\n'
    '        {"role": "user", "content": f"Q: {q}"},\n'
    "    ])\n"
    "    client.chat.completions.create(model=cfg.model, messages=history)\n"
    "    client.completions.create(prompt=build(q))\n"
)


def result() -> CallSiteResult:
    return CallSiteResult(tuple(extract_calls("app.py", SOURCE)), 2, ("old.py",))


def test_text_report_lists_each_call() -> None:
    assert render_text(result()).splitlines() == [
        "app.py:3  openai_chat  client.chat.completions.create",
        "  model: gpt-4o-mini",
        '  system: "Be brief.\\nUse {{braces}}."',
        '  user: "Q: {q}"',
        "  slots: q",
        "app.py:7  openai_chat  client.chat.completions.create  (partial)",
        "  model: cfg.model (value not found in the code)",
        "  unknown: (could not read: history)",
        "app.py:8  openai_completions  client.completions.create  (partial)",
        "  model: (not given in the call)",
        '  prompt: "{build(q)}"',
        "  slots: build(q)",
        "Could not parse old.py",
        "Found 3 LLM calls in 1 file (read 2 Python files): 1 with all prompt text, "
        "2 partial. 1 file did not parse.",
    ]


def test_long_templates_are_cut_in_the_text_report() -> None:
    source = f'client.completions.create(model="m", prompt="{"a" * 300}")\n'
    text = render_text(CallSiteResult(tuple(extract_calls("a.py", source)), 1))
    assert '  prompt: "' + "a" * 97 + '..."' in text.splitlines()


def test_json_report_has_full_templates() -> None:
    data = json.loads(render_json(result()))
    assert data["version"] == 1
    assert (data["files_read"], data["unparsed"]) == (2, ["old.py"])
    first = data["calls"][0]
    assert first["model"] == "gpt-4o-mini"
    assert first["model_source"] == "MODEL"
    assert first["output"] is None
    assert first["complete"] is True
    assert first["slots"] == ["q"]
    assert first["parts"][0] == {
        "role": "system",
        "template": "Be brief.\nUse {{braces}}.",
        "slots": [],
        "line": 4,
        "source": "'Be brief.\\nUse {braces}.'",
    }
    assert data["calls"][1]["parts"][0]["template"] is None


def test_summary_line_for_one_call() -> None:
    one = CallSiteResult(result().calls[:1], 1)
    assert summary_line(one) == (
        "Found 1 LLM call in 1 file (read 1 Python file): 1 with all prompt text, 0 partial."
    )
