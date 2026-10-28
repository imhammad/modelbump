"""Tests for finding LLM calls and their prompt templates (ADR 0048)."""

from pathlib import Path

import pytest

from modelbump.synth import Api, CallSite, extract_calls, find_call_sites, render, slot_names


def one(source: str) -> CallSite:
    calls = extract_calls("app.py", source)
    assert len(calls) == 1, calls
    return calls[0]


def templates(call: CallSite) -> list[tuple[str, str | None]]:
    return [(part.role, part.template) for part in call.parts]


# --- Which calls are found ----------------------------------------------------


@pytest.mark.parametrize(
    ("code", "api"),
    [
        ('client.chat.completions.create(model="m", messages=[])', Api.OPENAI_CHAT),
        ('await client.beta.chat.completions.parse(model="m", messages=[])', Api.OPENAI_CHAT),
        ('client.responses.create(model="m", input="hi")', Api.OPENAI_RESPONSES),
        ('client.completions.create(model="m", prompt="hi")', Api.OPENAI_COMPLETIONS),
        ('client.messages.create(model="m", max_tokens=5, messages=[])', Api.ANTHROPIC),
        ('client.messages.stream(model="m", max_tokens=5, messages=[])', Api.ANTHROPIC),
        ('client.models.generate_content(model="m", contents="hi")', Api.GEMINI),
        ('litellm.completion(model="m", messages=[])', Api.LITELLM),
        ('ollama.chat(model="m", messages=[])', Api.OLLAMA),
        ('ollama.generate(model="m", prompt="hi")', Api.OLLAMA),
        ('my_llm(model="m", messages=[])', Api.OTHER),
        ('OpenAI().chat.completions.create(model="m", messages=[])', Api.OPENAI_CHAT),
    ],
)
def test_each_api_is_recognised(code: str, api: Api) -> None:
    assert one(code + "\n").api is api


@pytest.mark.parametrize(
    "code",
    [
        'ChatOpenAI(model="gpt-4o")',
        'print("messages")',
        "items.append(1)",
        'client.files.create(file=f, purpose="batch")',
        'client.beta.threads.messages.create(thread_id=t, role="user", content="hi")',
        'client.images.generate(model="dall-e-3", prompt="A cat")',
        'client.audio.speech.create(model="tts-1", input="Hi", voice="alloy")',
    ],
)
def test_other_calls_are_not_llm_calls(code: str) -> None:
    assert extract_calls("app.py", code + "\n") == []


def test_calls_are_found_inside_functions_classes_and_awaits() -> None:
    source = (
        "class Bot:\n"
        "    async def run(self, q):\n"
        "        r = await self.client.chat.completions.create(\n"
        '            model="gpt-4o", messages=[{"role": "user", "content": q}]\n'
        "        )\n"
        "        return r\n"
    )
    call = one(source)
    assert (call.line, call.call) == (3, "self.client.chat.completions.create")
    assert templates(call) == [("user", "{q}")]


def test_a_file_that_does_not_parse_raises() -> None:
    with pytest.raises(SyntaxError):
        extract_calls("old.py", 'print "python 2"\n')


# --- Models --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("setup", "expr", "model"),
    [
        ("", '"gpt-4o-mini"', "gpt-4o-mini"),
        ('MODEL = "gpt-4o-mini"\n', "MODEL", "gpt-4o-mini"),
        ('A = "gpt-4o"\nMODEL = A\n', "MODEL", "gpt-4o"),
        ('MODEL = os.getenv("M", "gpt-4o")\n', "MODEL", "gpt-4o"),
        ('MODEL = os.environ.get("M", "gpt-4o")\n', "MODEL", "gpt-4o"),
        ('MODEL = os.getenv("M", default="gpt-4o")\n', "MODEL", "gpt-4o"),
        ('MODEL = os.environ.get("M") or "gpt-4o"\n', "MODEL", "gpt-4o"),
        ('MODEL = os.environ["M"]\n', "MODEL", None),
        ("", "settings.model", None),
    ],
)
def test_the_model_is_followed_through_names(setup: str, expr: str, model: str | None) -> None:
    call = one(setup + f"client.chat.completions.create(model={expr}, messages=[])\n")
    assert call.model == model
    assert call.model_source == expr.replace('"', "'")


def test_a_name_uses_the_last_value_before_the_call() -> None:
    source = (
        'MODEL = "gpt-3.5-turbo"\n'
        'MODEL = "gpt-4o"\n'
        "client.chat.completions.create(model=MODEL, messages=[])\n"
        'MODEL = "later"\n'
    )
    assert one(source).model == "gpt-4o"


def test_a_function_sees_module_names_assigned_after_it() -> None:
    source = (
        "def ask(q):\n"
        "    return client.chat.completions.create(model=MODEL, messages=[])\n"
        'MODEL = "gpt-4o"\n'
    )
    assert one(source).model == "gpt-4o"


def test_a_local_name_hides_the_module_name() -> None:
    source = (
        'MODEL = "gpt-4o"\n'
        "def ask(q):\n"
        '    MODEL = "o3-mini"\n'
        "    return client.chat.completions.create(model=MODEL, messages=[])\n"
    )
    assert one(source).model == "o3-mini"


def test_a_call_without_a_model_says_so() -> None:
    call = one('client.chat.completions.create(messages=[{"role": "user", "content": "hi"}])\n')
    assert (call.model, call.model_source) == (None, None)


# --- Messages ------------------------------------------------------------------


def test_chat_messages_keep_their_roles_and_lines() -> None:
    source = (
        "client.chat.completions.create(\n"
        '    model="gpt-4o",\n'
        "    messages=[\n"
        '        {"role": "system", "content": "Be brief."},\n'
        '        {"role": "user", "content": f"Q: {question}"},\n'
        "    ],\n"
        ")\n"
    )
    call = one(source)
    assert templates(call) == [("system", "Be brief."), ("user", "Q: {question}")]
    assert [part.line for part in call.parts] == [4, 5]
    assert call.slots == ("question",)
    assert call.complete


def test_messages_built_in_a_variable_with_appends() -> None:
    source = (
        "def ask(q, extra):\n"
        '    messages = [{"role": "system", "content": "Sys"}]\n'
        '    messages.append({"role": "user", "content": q})\n'
        '    messages += [{"role": "assistant", "content": "Ok"}]\n'
        '    messages.extend([("user", "More")])\n'
        '    return client.chat.completions.create(model="m", messages=messages)\n'
    )
    assert templates(one(source)) == [
        ("system", "Sys"),
        ("user", "{q}"),
        ("assistant", "Ok"),
        ("user", "More"),
    ]


def test_messages_joined_with_plus_and_star() -> None:
    source = (
        'BASE = [{"role": "system", "content": "Sys"}]\n'
        "client.chat.completions.create(model='m', messages=BASE + "
        '[{"role": "user", "content": "A"}])\n'
        "client.chat.completions.create(model='m', messages=[*BASE, "
        '{"role": "user", "content": "B"}])\n'
    )
    first, second = extract_calls("app.py", source)
    assert templates(first) == [("system", "Sys"), ("user", "A")]
    assert templates(second) == [("system", "Sys"), ("user", "B")]


def test_unknown_messages_are_kept_as_unreadable_and_partial() -> None:
    call = one('client.chat.completions.create(model="m", messages=history)\n')
    assert templates(call) == [("unknown", None)]
    assert call.parts[0].source == "history"
    assert not call.complete


def test_one_unreadable_message_in_a_list() -> None:
    source = (
        'client.chat.completions.create(model="m", messages=['
        '{"role": "system", "content": "Sys"}, last_message])\n'
    )
    call = one(source)
    assert templates(call) == [("system", "Sys"), ("unknown", None)]
    assert not call.complete


def test_message_forms_dict_call_tuple_and_classes() -> None:
    source = (
        'client.chat.completions.create(model="m", messages=[\n'
        '    dict(role="system", content="A"),\n'
        '    ("human", "B"),\n'
        '    SystemMessage(content="C"),\n'
        '    HumanMessage("D"),\n'
        '    AIMessage(content="E"),\n'
        "])\n"
    )
    assert templates(one(source)) == [
        ("system", "A"),
        ("user", "B"),
        ("system", "C"),
        ("user", "D"),
        ("assistant", "E"),
    ]


def test_tool_results_have_no_template() -> None:
    source = (
        'client.messages.create(model="m", max_tokens=9, messages=[{"role": "user", "content": [\n'
        '    {"type": "tool_result", "tool_use_id": t, "content": "72F"},\n'
        "]}])\n"
    )
    call = one(source)
    assert templates(call) == [("user", None)]
    assert not call.complete


def test_content_blocks_keep_only_the_text() -> None:
    source = (
        'client.messages.create(model="m", max_tokens=9, messages=[{"role": "user", "content": [\n'
        '    {"type": "image", "source": img},\n'
        '    {"type": "text", "text": "What is this?"},\n'
        '    {"type": "text", "text": f"Context: {ctx}"},\n'
        "]}])\n"
    )
    assert templates(one(source)) == [("user", "What is this?\nContext: {ctx}")]


def test_anthropic_system_as_string_or_blocks() -> None:
    source = (
        'client.messages.create(model="m", max_tokens=9, system="Sys A", messages=[])\n'
        'client.messages.create(model="m", max_tokens=9, '
        'system=[{"type": "text", "text": "Sys B", "cache_control": c}], messages=[])\n'
    )
    first, second = extract_calls("app.py", source)
    assert templates(first) == [("system", "Sys A")]
    assert templates(second) == [("system", "Sys B")]


def test_responses_api_instructions_and_input() -> None:
    source = (
        'client.responses.create(model="m", instructions="Sys", input=f"Q: {q}")\n'
        'client.responses.create(model="m", input=[{"role": "user", "content": "Hi"}])\n'
    )
    first, second = extract_calls("app.py", source)
    assert templates(first) == [("system", "Sys"), ("user", "Q: {q}")]
    assert templates(second) == [("user", "Hi")]


def test_completions_and_generate_take_one_prompt() -> None:
    source = (
        'client.completions.create(model="m", prompt="Say hi")\n'
        'ollama.generate(model="m", system="Sys", prompt=f"{a} and {b}")\n'
    )
    first, second = extract_calls("app.py", source)
    assert templates(first) == [("prompt", "Say hi")]
    assert templates(second) == [("system", "Sys"), ("prompt", "{a} and {b}")]


def test_gemini_contents_and_system_instruction() -> None:
    source = (
        "client.models.generate_content(\n"
        '    model="gemini-2.5-flash",\n'
        '    contents=["Part one", f"Part {two}"],\n'
        '    config=types.GenerateContentConfig(system_instruction="Sys"),\n'
        ")\n"
        'client.models.generate_content(model="m", contents=[\n'
        '    {"role": "user", "parts": [{"text": "Hello"}]},\n'
        '], config={"system_instruction": "Sys 2"})\n'
    )
    first, second = extract_calls("app.py", source)
    assert templates(first) == [("system", "Sys"), ("user", "Part one"), ("user", "Part {two}")]
    assert templates(second) == [("system", "Sys 2"), ("user", "Hello")]


def test_gemini_old_sdk_model_object() -> None:
    source = (
        "m = genai.GenerativeModel('gemini-1.5-flash', system_instruction='Sys')\n"
        "def ask(q):\n"
        "    return m.generate_content(q)\n"
    )
    call = one(source)
    assert call.model == "gemini-1.5-flash"
    assert templates(call) == [("system", "Sys"), ("user", "{q}")]
    assert not call.complete


# --- Templates -----------------------------------------------------------------


def prompt_of(setup: str, expr: str) -> str | None:
    call = one(setup + f'client.completions.create(model="m", prompt={expr})\n')
    return call.parts[0].template


@pytest.mark.parametrize(
    ("setup", "expr", "template"),
    [
        ("", '"Plain {braces} stay"', "Plain {{braces}} stay"),
        ("", 'f"Hi {user.name}, {items[0]!r:>5}"', "Hi {user.name}, {items(0)}"),
        ("", '"Hi " + name + "!"', "Hi {name}!"),
        ("", '"Hi {}, {who}".format(a, who=b)', "Hi {a}, {who}"),
        ("", '"Hi {0} {0}".format(a)', "Hi {a} {a}"),
        ("", '"Total %d of %s" % (n, kind)', "Total {n} of {kind}"),
        ("", '"%(name)s is 100%%" % data', "{name} is 100%"),
        ("", '"Hi %s" % name', "Hi {name}"),
        ('P = "Ask: {q}"\n', "P.format(q=question)", "Ask: {q}"),
        ('L = "a, b"\n', 'f"Labels: {L}"', "Labels: a, b"),
        ("N = 3\n", 'f"Top {N} of {m}"', "Top 3 of {m}"),
        ('L = "a, b"\n', '"Labels: {labels}".format(labels=L)', "Labels: a, b"),
        ('p = "A"\np += f" {x}"\np += "!"\n', "p", "A {x}!"),
        ("", 'textwrap.dedent("""\n    One\n      Two\n""")', "\nOne\n  Two\n"),
        ("", 'inspect.cleandoc("""\n    One\n    Two\n""")', "One\nTwo"),
        ("", '"  padded  ".strip()', "padded"),
        ("", 'dedent("""\n    Hi {n}\n""").format(n=x)', "\nHi {n}\n"),
        ("", '"\\n".join(["A", f"B {x}"])', "A\nB {x}"),
        ("", '"\\n".join(lines)', "{lines}"),
        ("", "prompt", "{prompt}"),
        ("", "build_prompt(q)", "{build_prompt(q)}"),
        ("", 'f"{a}" + some_call()', "{a}{some_call()}"),
    ],
)
def test_templates(setup: str, expr: str, template: str) -> None:
    assert prompt_of(setup, expr) == template


def test_a_name_that_refers_to_itself_does_not_loop() -> None:
    assert prompt_of("p = p\n", "p") == "{p}"


def test_slots_only_is_not_complete() -> None:
    call = one('client.completions.create(model="m", prompt=prompt)\n')
    assert call.parts[0].slots == ("prompt",)
    assert not call.parts[0].has_text
    assert not call.complete


def test_render_fills_slots_and_keeps_literal_braces() -> None:
    template = 'Return JSON like {{"a": 1}} for {user.name}: {q}'
    assert slot_names(template) == ("user.name", "q")
    assert (
        render(template, {"user.name": "Ann", "q": "hi"}) == 'Return JSON like {"a": 1} for Ann: hi'
    )
    with pytest.raises(KeyError, match="q"):
        render(template, {"user.name": "Ann"})


# --- Folders --------------------------------------------------------------------


def test_find_call_sites_reads_python_files_only(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text('client.completions.create(model="m", prompt="A")\n')
    (tmp_path / "web.ts").write_text('client.completions.create({model: "m", prompt: "B"})\n')
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text(
        'client.completions.create(model="m", prompt="T")\n'
    )
    (tmp_path / "old.py").write_text('print "python 2"\n')
    result = find_call_sites(tmp_path)
    assert [(c.path, c.parts[0].template) for c in result.calls] == [
        ("app.py", "A"),
        ("tests/test_app.py", "T"),
    ]
    assert (result.files_read, result.unparsed) == (3, ("old.py",))
    skipped = find_call_sites(tmp_path, exclude=["old.py"], skip_tests=True)
    assert [c.path for c in skipped.calls] == ["app.py"]
    assert (skipped.files_read, skipped.unparsed) == (1, ())


def test_find_call_sites_on_one_file(tmp_path: Path) -> None:
    path = tmp_path / "app.py"
    path.write_text('client.completions.create(model="m", prompt="A")\n')
    result = find_call_sites(path)
    assert [c.path for c in result.calls] == ["app.py"]
