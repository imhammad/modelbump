"""The demo app's own tests: `modelbump cases` reads the inputs they pass in.

ModelBump's test run skips this folder (tests/conftest.py), since it is data.
"""

from unittest.mock import MagicMock

import pytest
from bot import FaqBot
from support import classify, summarize


@pytest.mark.parametrize(
    "ticket",
    [
        "The app crashes when I log in.",
        "Could you add a dark mode?",
        "How do I export my data?",
    ],
)
def test_classify_sends_the_ticket(ticket: str) -> None:
    client = MagicMock()
    classify(client, ticket)
    assert client.chat.completions.create.called


def test_summarize_a_short_thread() -> None:
    client = MagicMock()
    thread = ["Customer: my order is late.", "Agent: it ships tomorrow."]
    summarize(client, thread, 30)
    assert client.messages.create.called


def test_faq_bot_answers() -> None:
    bot = FaqBot(MagicMock())
    bot.answer("How do I reset my password?")
