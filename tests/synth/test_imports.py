"""Tests for following prompts into other files and onto classes (ADR 0049)."""

from pathlib import Path

from modelbump.synth import CallSite, extract_calls, find_call_sites

CALL = (
    "client.chat.completions.create("
    'model={model}, messages=[{{"role": "system", "content": {system}}}])\n'
)


def write(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


def calls(root: Path, files: dict[str, str]) -> list[CallSite]:
    write(root, files)
    return list(find_call_sites(root).calls)


def system_of(root: Path, files: dict[str, str]) -> tuple[str | None, str | None]:
    (call,) = calls(root, files)
    return call.model, call.parts[0].template


PROMPTS = 'MODEL = "gpt-4o-mini"\nSYSTEM = "Be brief."\n'


def test_relative_import_in_a_package(tmp_path: Path) -> None:
    files = {
        "app/__init__.py": "",
        "app/prompts.py": PROMPTS,
        "app/chat.py": "from .prompts import MODEL, SYSTEM\n"
        + CALL.format(model="MODEL", system="SYSTEM"),
    }
    assert system_of(tmp_path, files) == ("gpt-4o-mini", "Be brief.")


def test_relative_import_from_a_parent_package_and_its_init(tmp_path: Path) -> None:
    files = {
        "app/__init__.py": 'SYSTEM = "From init."\n',
        "app/config.py": 'MODEL = "o3-mini"\n',
        "app/bots/__init__.py": "",
        "app/bots/chat.py": "from .. import SYSTEM\nfrom ..config import MODEL\n"
        + CALL.format(model="MODEL", system="SYSTEM"),
    }
    assert system_of(tmp_path, files) == ("o3-mini", "From init.")


def test_absolute_import_with_an_alias(tmp_path: Path) -> None:
    files = {
        "app/prompts.py": PROMPTS,
        "main.py": "from app.prompts import SYSTEM as S, MODEL as M\n"
        + CALL.format(model="M", system="S"),
    }
    assert system_of(tmp_path, files) == ("gpt-4o-mini", "Be brief.")


def test_absolute_import_from_a_src_folder_or_a_subfolder(tmp_path: Path) -> None:
    files = {
        "backend/src/app/prompts.py": PROMPTS,
        "backend/src/app/chat.py": "from app.prompts import MODEL, SYSTEM\n"
        + CALL.format(model="MODEL", system="SYSTEM"),
    }
    assert system_of(tmp_path, files) == ("gpt-4o-mini", "Be brief.")


def test_module_attributes(tmp_path: Path) -> None:
    files = {
        "app/prompts.py": PROMPTS,
        "a.py": "import app.prompts as p\n" + CALL.format(model="p.MODEL", system="p.SYSTEM"),
        "b.py": "from app import prompts\n"
        + CALL.format(model="prompts.MODEL", system="prompts.SYSTEM"),
        "c.py": "import app.prompts\n"
        + CALL.format(model="app.prompts.MODEL", system="app.prompts.SYSTEM"),
    }
    found = calls(tmp_path, files)
    assert [(c.path, c.model, c.parts[0].template) for c in found] == [
        ("a.py", "gpt-4o-mini", "Be brief."),
        ("b.py", "gpt-4o-mini", "Be brief."),
        ("c.py", "gpt-4o-mini", "Be brief."),
    ]


def test_an_imported_template_uses_names_from_its_own_file(tmp_path: Path) -> None:
    files = {
        "app/labels.py": 'LABELS = "bug, feature"\n',
        "app/prompts.py": "from app.labels import LABELS\n"
        'SYSTEM = f"Pick one: {LABELS}."\n'
        'BASE = [{"role": "system", "content": SYSTEM}]\n',
        "app/chat.py": "from app.prompts import BASE\n"
        "def ask(q):\n"
        '    return client.chat.completions.create(model="m", messages=BASE + '
        '[{"role": "user", "content": f"Q: {q}"}])\n',
    }
    (call,) = calls(tmp_path, files)
    assert [(p.role, p.template) for p in call.parts] == [
        ("system", "Pick one: bug, feature."),
        ("user", "Q: {q}"),
    ]
    assert call.complete


def test_a_template_formatted_with_an_imported_value(tmp_path: Path) -> None:
    files = {
        "app/prompts.py": 'TEMPLATE = "Summarize in {n} words: {text}"\nWORDS = 50\n',
        "app/chat.py": "from app import prompts\n"
        "def ask(doc):\n"
        "    p = prompts.TEMPLATE.format(n=prompts.WORDS, text=doc)\n"
        '    return client.completions.create(model="m", prompt=p)\n',
    }
    (call,) = calls(tmp_path, files)
    assert call.parts[0].template == "Summarize in 50 words: {text}"


def test_unknown_ambiguous_and_missing_imports_stay_slots(tmp_path: Path) -> None:
    files = {
        "one/app/prompts.py": PROMPTS,
        "two/app/prompts.py": PROMPTS,
        "main.py": "from app.prompts import SYSTEM\n"
        "from openai_helpers import OTHER\n"
        "from .missing import NOPE\n"
        + CALL.format(model='"m"', system="SYSTEM")
        + CALL.format(model='"m"', system="OTHER")
        + CALL.format(model='"m"', system="NOPE"),
    }
    found = calls(tmp_path, files)
    assert [c.parts[0].template for c in found] == ["{SYSTEM}", "{OTHER}", "{NOPE}"]
    assert not any(c.complete for c in found)


def test_circular_imports_do_not_loop(tmp_path: Path) -> None:
    files = {
        "a.py": "from b import X\n" + CALL.format(model='"m"', system="X"),
        "b.py": "from a import X\n",
    }
    assert system_of(tmp_path, files) == ("m", "{X}")


def test_a_file_that_does_not_parse_is_not_followed(tmp_path: Path) -> None:
    files = {
        "prompts.py": 'print "python 2"\nSYSTEM = "x"\n',
        "main.py": "from prompts import SYSTEM\n" + CALL.format(model='"m"', system="SYSTEM"),
    }
    write(tmp_path, files)
    result = find_call_sites(tmp_path)
    assert [c.parts[0].template for c in result.calls] == ["{SYSTEM}"]
    assert result.unparsed == ("prompts.py",)


def test_excluded_files_are_still_followed_but_not_listed(tmp_path: Path) -> None:
    files = {
        "lib/prompts.py": PROMPTS + CALL.format(model='"x"', system='"In lib"'),
        "tests/test_chat.py": CALL.format(model='"t"', system='"In tests"'),
        "main.py": "from lib.prompts import SYSTEM\n" + CALL.format(model='"m"', system="SYSTEM"),
    }
    write(tmp_path, files)
    result = find_call_sites(tmp_path, exclude=["lib"], skip_tests=True)
    assert [(c.path, c.parts[0].template) for c in result.calls] == [("main.py", "Be brief.")]
    assert result.files_read == 1


def test_one_file_alone_does_not_follow_imports() -> None:
    source = "from app.prompts import SYSTEM\n" + CALL.format(model='"m"', system="SYSTEM")
    (call,) = extract_calls("main.py", source)
    assert call.parts[0].template == "{SYSTEM}"


# --- Class attributes --------------------------------------------------------------


def one(source: str) -> CallSite:
    (call,) = extract_calls("bot.py", source)
    return call


def test_self_attribute_set_in_init() -> None:
    source = (
        "class Bot:\n"
        "    def __init__(self, client):\n"
        '        self.model = "gpt-4o"\n'
        '        self.system = "Be kind."\n'
        "    def ask(self, q):\n"
        "        return client.chat.completions.create(model=self.model, messages=[\n"
        '            {"role": "system", "content": self.system},\n'
        '            {"role": "user", "content": q}])\n'
    )
    call = one(source)
    assert call.model == "gpt-4o"
    assert [p.template for p in call.parts] == ["Be kind.", "{q}"]


def test_class_body_attribute_and_module_constant() -> None:
    source = (
        'PROMPT = "Hi {name}"\n'
        "class Bot:\n"
        '    MODEL = "o3-mini"\n'
        "    TEMPLATE = PROMPT\n"
        "    def ask(self, n):\n"
        "        return client.completions.create(model=self.MODEL, "
        "prompt=self.TEMPLATE.format(name=n))\n"
    )
    call = one(source)
    assert (call.model, call.parts[0].template) == ("o3-mini", "Hi {name}")


def test_the_same_method_wins_over_init() -> None:
    source = (
        "class Bot:\n"
        "    def __init__(self):\n"
        '        self.system = "From init"\n'
        "    def ask(self):\n"
        '        self.system = "From ask"\n'
        '        return client.completions.create(model="m", prompt=self.system)\n'
    )
    assert one(source).parts[0].template == "From ask"


def test_an_attribute_set_only_in_one_other_method_counts() -> None:
    source = (
        "class Bot:\n"
        "    def setup(self):\n"
        '        self.system = "From setup"\n'
        "    def ask(self):\n"
        '        return client.completions.create(model="m", prompt=self.system)\n'
    )
    assert one(source).parts[0].template == "From setup"
    twice = source + "    def reset(self):\n" + '        self.system = "Other"\n'
    assert one(twice).parts[0].template == "{self.system}"


def test_an_attribute_from_a_parameter_stays_a_slot() -> None:
    source = (
        "class Bot:\n"
        "    def __init__(self, system_prompt):\n"
        "        self.system = system_prompt\n"
        "    def ask(self):\n"
        '        return client.completions.create(model="m", prompt=self.system)\n'
    )
    assert one(source).parts[0].template == "{self.system}"


def test_class_body_names_are_not_visible_in_methods() -> None:
    source = (
        'SYSTEM = "Module"\n'
        "class Bot:\n"
        '    SYSTEM = "Class"\n'
        "    def ask(self):\n"
        '        return client.completions.create(model="m", prompt=SYSTEM)\n'
    )
    assert one(source).parts[0].template == "Module"


def test_static_methods_and_other_objects_have_no_self() -> None:
    source = (
        "class Bot:\n"
        '    system = "Class"\n'
        "    @staticmethod\n"
        "    def ask(self):\n"
        '        return client.completions.create(model="m", prompt=self.system)\n'
        "    def other(self, peer):\n"
        '        return client.completions.create(model="m", prompt=peer.system)\n'
    )
    first, second = extract_calls("bot.py", source)
    assert first.parts[0].template == "{self.system}"
    assert second.parts[0].template == "{peer.system}"


def test_an_imported_constant_on_the_class(tmp_path: Path) -> None:
    files = {
        "prompts.py": PROMPTS,
        "bot.py": "from prompts import SYSTEM\n"
        "class Bot:\n"
        "    def __init__(self):\n"
        "        self.system = SYSTEM\n"
        "    def ask(self):\n"
        '        return client.completions.create(model="m", prompt=self.system)\n',
    }
    (call,) = calls(tmp_path, files)
    assert call.parts[0].template == "Be brief."


# --- Prompts returned by the app's own functions -----------------------------------


def prompt(source: str) -> str | None:
    return one(source).parts[-1].template


def test_a_function_that_returns_a_prompt() -> None:
    source = (
        "def build(question, n=3):\n"
        '    return f"Q: {question}\\nGive {n} answers."\n'
        "def ask(q):\n"
        '    return client.completions.create(model="m", prompt=build(q))\n'
    )
    assert prompt(source) == "Q: {q}\nGive 3 answers."


def test_arguments_by_keyword_override_defaults() -> None:
    source = (
        'TONE = "kind"\n'
        "def build(question, *, n=3, tone=TONE):\n"
        '    text = f"Q: {question} ({n} answers, {tone})"\n'
        "    return text.strip()\n"
        'client.completions.create(model="m", prompt=build("Why?", n=5))\n'
    )
    assert prompt(source) == "Q: Why? (5 answers, kind)"


def test_a_parameter_shadows_a_module_name() -> None:
    source = (
        'query = "module"\n'
        "def build(query):\n"
        '    return f"Q: {query}"\n'
        "def ask(q):\n"
        '    return client.completions.create(model="m", prompt=build(q))\n'
    )
    assert prompt(source) == "Q: {q}"


def test_functions_with_several_returns_or_star_args_are_not_read() -> None:
    source = (
        "def build(q):\n"
        "    if q:\n"
        '        return f"A {q}"\n'
        '    return "B"\n'
        "def other(q):\n"
        '    return f"C {q}"\n'
        'client.completions.create(model="m", prompt=build("x"))\n'
        'client.completions.create(model="m", prompt=other(*args))\n'
    )
    first, second = extract_calls("app.py", source)
    assert first.parts[0].template == "{build('x')}"
    assert second.parts[0].template == "{other(*args)}"


def test_a_nested_return_does_not_count() -> None:
    source = (
        "def build(q):\n"
        "    def inner():\n"
        '        return "inner"\n'
        '    return f"Outer {q}"\n'
        'client.completions.create(model="m", prompt=build("x"))\n'
    )
    assert prompt(source) == "Outer x"


def test_a_function_that_returns_messages() -> None:
    source = (
        "def messages_for(q):\n"
        '    return [{"role": "system", "content": "Sys"}, {"role": "user", "content": q}]\n'
        "def ask(question):\n"
        '    return client.chat.completions.create(model="m", messages=messages_for(question))\n'
    )
    assert [(p.role, p.template) for p in one(source).parts] == [
        ("system", "Sys"),
        ("user", "{question}"),
    ]


def test_an_imported_function_and_a_module_function(tmp_path: Path) -> None:
    files = {
        "app/prompts.py": "def summary(text, words=50):\n"
        '    return f"Summarize in {words}: {text}"\n',
        "a.py": "from app.prompts import summary\n"
        "def run(doc):\n"
        '    return client.completions.create(model="m", prompt=summary(doc))\n',
        "b.py": "from app import prompts\n"
        "def run(doc):\n"
        '    return client.completions.create(model="m", prompt=prompts.summary(doc, 9))\n',
    }
    found = calls(tmp_path, files)
    assert [c.parts[0].template for c in found] == [
        "Summarize in 50: {doc}",
        "Summarize in 9: {doc}",
    ]


def test_methods_through_self_the_class_and_a_typed_parameter(tmp_path: Path) -> None:
    files = {
        "app/prompts.py": "class Prompts:\n"
        "    @staticmethod\n"
        "    def intro(topic):\n"
        '        return f"Introduce {topic}."\n'
        "    @classmethod\n"
        "    def outro(cls, topic):\n"
        '        return f"Close {topic}."\n'
        "    def body(self, topic):\n"
        '        return f"Explain {topic}."\n',
        "app/write.py": "from app.prompts import Prompts\n"
        "def a(t):\n"
        '    return client.completions.create(model="m", prompt=Prompts.intro(t))\n'
        "def b(t, family: type[Prompts] | None = None):\n"
        '    return client.completions.create(model="m", prompt=family.outro(t))\n'
        "def c(t, family: 'Prompts'):\n"
        '    return client.completions.create(model="m", prompt=family.body(t))\n'
        "def d(t):\n"
        "    family = Prompts()\n"
        '    return client.completions.create(model="m", prompt=family.body(t))\n'
        "def e(t, family: Optional[Prompts]):\n"
        '    return client.completions.create(model="m", prompt=family.intro(t))\n',
    }
    found = calls(tmp_path, files)
    assert [c.parts[0].template for c in found] == [
        "Introduce {t}.",
        "Close {t}.",
        "Explain {t}.",
        "Explain {t}.",
        "Introduce {t}.",
    ]


def test_a_method_called_on_self() -> None:
    source = (
        "class Bot:\n"
        "    def system(self, name):\n"
        '        return f"You are {name}."\n'
        "    def ask(self):\n"
        '        return client.completions.create(model="m", prompt=self.system("Ada"))\n'
    )
    assert prompt(source) == "You are Ada."


def test_a_function_that_calls_itself_does_not_loop() -> None:
    source = (
        "def build(q):\n"
        "    return build(q)\n"
        'client.completions.create(model="m", prompt=build("x"))\n'
    )
    assert prompt(source) == "{build('x')}"


# --- Calls with **params and lists with unknown parts --------------------------------


def test_keywords_from_a_params_dict() -> None:
    source = (
        "def ask(q, history):\n"
        "    params = {\n"
        '        "model": "gpt-4o",\n'
        '        "messages": [{"role": "user", "content": q}],\n'
        "    }\n"
        '    return client.chat.completions.create(**params, model="o3-mini")\n'
        "def other(q):\n"
        '    return client.chat.completions.create(**{"model": "x", "messages": []})\n'
    )
    first, second = extract_calls("app.py", source)
    assert first.model == "o3-mini"
    assert [p.template for p in first.parts] == ["{q}"]
    assert second.model == "x"


def test_params_from_elsewhere_are_not_read() -> None:
    source = "def ask(params):\n    return client.chat.completions.create(**params)\n"
    call = one(source)
    assert (call.model_source, call.parts, call.complete) == (None, (), False)


def test_known_messages_are_kept_around_an_unknown_part() -> None:
    source = (
        "def ask(history, extra):\n"
        '    messages = [{"role": "system", "content": "Sys"}] + history\n'
        "    messages.extend(extra)\n"
        '    messages.append({"role": "user", "content": "Last"})\n'
        '    return client.chat.completions.create(model="m", messages=[*messages, *more])\n'
    )
    assert [(p.role, p.template) for p in one(source).parts] == [
        ("system", "Sys"),
        ("unknown", None),
        ("unknown", None),
        ("user", "Last"),
        ("unknown", None),
    ]


def test_count_tokens_is_not_an_llm_call() -> None:
    source = 'client.messages.count_tokens(model="m", messages=[])\n'
    assert extract_calls("app.py", source) == []
