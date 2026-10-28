"""Prompts kept in their own file, as many apps do (fixture for `modelbump prompts`)."""

BOT_MODEL = "gpt-4o-mini"
FAQ_SYSTEM = "Answer questions about our product from the FAQ. If unsure, say you don't know."


def faq_question(question: str, sentences: int = 2) -> str:
    return f"Question: {question}\nAnswer in at most {sentences} sentences."
