"""Tests for picking an oracle from what each LLM call asks for (ADR 0052)."""

import pytest

from modelbump.oracles import OutputKind, choose_oracle, normalize_label
from modelbump.synth import CallSite, extract_calls


def one(source: str) -> CallSite:
    calls = extract_calls("app.py", source)
    assert len(calls) == 1, calls
    return calls[0]


def chat(system: str, user: str = "{text}", extra: str = "") -> CallSite:
    return one(
        "def f(client, text):\n"
        "    return client.chat.completions.create(\n"
        f'        model="m", {extra}\n'
        f"        messages=[{{'role': 'system', 'content': {system!r}}},\n"
        f"                  {{'role': 'user', 'content': f{user!r}}}],\n"
        "    )\n"
    )


# --- What the call's own settings say -------------------------------------------


@pytest.mark.parametrize(
    "extra",
    [
        'response_format={"type": "json_object"},',
        'response_format={"type": "json_schema", "json_schema": {}},',
        'format="json",',
    ],
)
def test_json_settings_pick_the_json_oracle(extra: str) -> None:
    site = chat("Summarize.", extra=extra)
    assert site.output == "json"
    choice = choose_oracle(site)
    assert choice.kind is OutputKind.JSON
    assert choice.reason == "the call's settings ask for JSON"


def test_parse_with_a_response_model_is_json() -> None:
    site = one(
        'client.beta.chat.completions.parse(model="m", messages=[], response_format=Order)\n'
    )
    assert site.output == "json"


def test_responses_api_text_format_is_json() -> None:
    site = one(
        'client.responses.create(model="m", input="hi", '
        'text={"format": {"type": "json_schema", "name": "x"}})\n'
    )
    assert site.output == "json"


def test_gemini_config_json_and_tools() -> None:
    json_site = one(
        'client.models.generate_content(model="m", contents="hi", '
        'config={"response_mime_type": "application/json"})\n'
    )
    assert json_site.output == "json"
    tools_site = one(
        'client.models.generate_content(model="m", contents="hi", config={"tools": [search]})\n'
    )
    assert tools_site.output == "tools"


def test_settings_read_through_a_name() -> None:
    site = one(
        'FMT = {"type": "json_object"}\n'
        'client.chat.completions.create(model="m", messages=[], response_format=FMT)\n'
    )
    assert site.output == "json"


def test_tools_win_over_json() -> None:
    site = chat("Return JSON.", extra='tools=TOOLS, response_format={"type": "json_object"},')
    assert site.output == "tools"
    choice = choose_oracle(site)
    assert choice.kind is OutputKind.TOOLS
    assert "not scored yet" in choice.reason


def test_tools_none_and_plain_text_settings_are_not_formats() -> None:
    assert chat("Hi.", extra="tools=None,").output is None
    # A plain string in `text=` is text, even when it says "json".
    site = one('my_llm(model="m", prompt="hi", text="explain json")\n')
    assert site.output is None
    assert chat("Hi.", extra='response_format={"type": "text"},').output is None


# --- What the prompt says --------------------------------------------------------


def test_prompt_that_says_json_picks_json() -> None:
    choice = choose_oracle(chat("Return valid JSON only, with the key answer."))
    assert choice.kind is OutputKind.JSON
    assert choice.reason == 'the prompt says "JSON"'


def test_json_in_a_slot_name_is_not_an_ask_for_json() -> None:
    site = chat("Summarize these results.", user="{json.dumps(results)}")
    assert choose_oracle(site).kind is OutputKind.TEXT


@pytest.mark.parametrize(
    ("system", "labels"),
    [
        (
            "You sort tickets.\nAnswer with one label: bug, feature, question.\n",
            ("bug", "feature", "question"),
        ),
        ("Reply with one of: positive, negative or neutral.", ("positive", "negative", "neutral")),
        ("Pick one category from 'billing' | 'tech' | 'other'.", ("billing", "tech", "other")),
        ("Is this spam? Answer yes or no.", ("yes", "no")),
        ("Return exactly one of the following labels: Toxic, Safe", ("toxic", "safe")),
    ],
)
def test_prompt_that_lists_labels_picks_the_label_oracle(
    system: str, labels: tuple[str, ...]
) -> None:
    choice = choose_oracle(chat(system))
    assert choice.kind is OutputKind.LABEL
    assert choice.labels == labels
    assert choice.reason == f"the prompt lists labels: {', '.join(labels)}"


@pytest.mark.parametrize(
    "system",
    [
        "Answer with one label: {labels}.",  # filled in at run time
        "Answer with one label: bug.",  # one label is not a choice
        "Answer with one word: the longest word you can think of in any language today.",
        "Summarize in one sentence.",
    ],
)
def test_prompts_without_a_usable_label_list_are_text(system: str) -> None:
    assert choose_oracle(chat(system)).kind is OutputKind.TEXT


def test_unread_messages_are_text_with_a_reason() -> None:
    site = one('client.chat.completions.create(model="m", messages=history)\n')
    choice = choose_oracle(site)
    assert choice.kind is OutputKind.TEXT
    assert choice.reason == "no prompt text was read, so free text"


def test_normalize_label() -> None:
    assert normalize_label('  "Bug." ') == "bug"
    assert normalize_label("**Feature**") == "feature"
    assert normalize_label("[Question]!") == "question"
