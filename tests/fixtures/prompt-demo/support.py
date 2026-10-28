"""A tiny support app for testing `modelbump prompts` (tests/test_cli.py).

The clients are passed in, so this file needs no LLM packages to type-check.
"""

import os
import textwrap
from typing import Any

MODEL = os.getenv("SUPPORT_MODEL", "gpt-4o-mini")
LABELS = "bug, feature, question"

SYSTEM = textwrap.dedent(
    """\
    You sort support tickets.
    Answer with one label: {labels}.
    """
).format(labels=LABELS)


def classify(client: Any, ticket: str) -> Any:
    messages = [{"role": "system", "content": SYSTEM}]
    messages.append({"role": "user", "content": f"Ticket:\n{ticket}"})
    return client.chat.completions.create(model=MODEL, messages=messages, temperature=0)


def summarize(client: Any, thread: list[str], words: int) -> Any:
    prompt = "Summarize this support thread in at most %d words:\n" % words  # noqa: UP031
    prompt += "\n".join(thread)
    return client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=300,
        system="You write short, factual summaries.",
        messages=[{"role": "user", "content": prompt}],
    )


def reply(client: Any, history: list[dict[str, str]], settings: Any) -> Any:
    return client.chat.completions.create(model=settings.model, messages=history)
