"""Pull order details out of an email, with Gemini (fixture for `modelbump prompts`)."""

from typing import Any

INSTRUCTIONS = "Return JSON with the keys order_id, items and total."


def extract_order(client: Any, email: str) -> Any:
    return client.models.generate_content(
        model="gemini-2.0-flash",
        contents="Email:\n{}\n\nJSON:".format(email),  # noqa: UP032 (old style on purpose)
        config={"system_instruction": INSTRUCTIONS},
    )
