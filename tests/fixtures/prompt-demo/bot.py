"""A FAQ bot whose prompt lives in prompts.py (fixture for `modelbump prompts`)."""

from typing import Any

from prompts import BOT_MODEL, FAQ_SYSTEM, faq_question


class FaqBot:
    def __init__(self, client: Any) -> None:
        self.client = client
        self.system = FAQ_SYSTEM

    def answer(self, question: str) -> Any:
        return self.client.chat.completions.create(
            model=BOT_MODEL,
            messages=[
                {"role": "system", "content": self.system},
                {"role": "user", "content": faq_question(question)},
            ],
        )
