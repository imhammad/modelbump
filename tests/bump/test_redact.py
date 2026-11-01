"""Tests for taking secrets and email addresses out of the evidence (ADR 0073).

Every fake secret is put together at run time, so the test file itself holds
nothing a secret scanner would stop at a push.
"""

import json
from collections import Counter

import pytest

from modelbump.bump import redact, redact_json
from modelbump.bump.redact import secrets_in, summary

OPENAI = "sk-" + "proj-" + "Ab3dE" * 10
ANTHROPIC = "sk-" + "ant-" + "api03-" + "x7Yz" * 10
GOOGLE = "AI" + "za" + "Sy" + "B1c2D3e4F5g6H7i8J9k0L1m2N3o4P5q6R7s"
GITHUB = "gh" + "p_" + "aB1" * 12
GITHUB_PAT = "github" + "_pat_" + "11AB" * 6
AWS = "AK" + "IA" + "ABCDEFGH23456789"
GROQ = "gs" + "k_" + "aB3" * 14
HF = "h" + "f_" + "aBcD" * 8
SLACK = "xo" + "xb-" + "1234-5678-abcdefgh"
JWT = (
    "ey"
    + "J"
    + "hbGciOiJIUzI1NiJ9"
    + ".ey"
    + "J"
    + "zdWIiOiIxMjM0NTY3ODkwIn0"
    + ".abcdEFGH1234ijkl"
)
KEY_BLOCK = (
    "-----BEGIN " + "RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA\n-----END " + "RSA PRIVATE KEY-----"
)


@pytest.mark.parametrize(
    ("secret", "kind"),
    [
        (OPENAI, "OpenAI key"),
        (ANTHROPIC, "Anthropic key"),
        (GOOGLE, "Google API key"),
        (GITHUB, "GitHub token"),
        (GITHUB_PAT, "GitHub token"),
        (AWS, "AWS access key"),
        (GROQ, "Groq key"),
        (HF, "Hugging Face token"),
        (SLACK, "Slack token"),
        (JWT, "JSON web token"),
        (KEY_BLOCK, "private key"),
        ("hammad.h@gmail.com", "email address"),
    ],
)
def test_each_kind_is_replaced(secret: str, kind: str) -> None:
    result = redact(f"before {secret} after")
    assert result.text == f"before [REDACTED:{kind}] after"
    assert result.found == Counter({kind: 1})


def test_bearer_token_keeps_the_word_bearer() -> None:
    result = redact("Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123")
    assert result.text == "Authorization: Bearer [REDACTED:bearer token]"


def test_a_key_in_an_error_url_is_replaced() -> None:
    error = f"400 Bad Request for url https://generativelanguage.googleapis.com/v1?key={GOOGLE}"
    assert redact(error).text.endswith("?key=[REDACTED:Google API key]")


@pytest.mark.parametrize(
    "text",
    [
        "Write to support@example.com or help@mail.example.org.",
        "pip install scikit-learn; sk-learn-is-not-a-key-but-a-long-word-here",
        "task-assessment-framework-for-everyone-2024 and risk-assessment-2025-plan-x",
        "Version 1.2.3 of claude-haiku-4-5-20251001 answered in 12 ms.",
        "AKIA is short",
    ],
)
def test_ordinary_text_is_left_alone(text: str) -> None:
    assert redact(text).text == text
    assert not redact(text).found


def test_json_escapes_stay_valid() -> None:
    data = {"answer": f"Line one\nname@mail.org\n{OPENAI}\tdone \\ {ANTHROPIC}"}
    text = json.dumps(data, indent=2)
    result = redact_json(text, "test.json")
    assert json.loads(result.text) == {
        "answer": "Line one\n[REDACTED:email address]\n[REDACTED:OpenAI key]\tdone \\ "
        "[REDACTED:Anthropic key]"
    }
    assert result.found == Counter({"email address": 1, "OpenAI key": 1, "Anthropic key": 1})


def test_json_without_secrets_is_unchanged() -> None:
    text = json.dumps({"answer": "Bug."}, indent=2) + "\n"
    assert redact_json(text, "test.json").text == text


def test_summary_and_secrets_in() -> None:
    assert summary(Counter({"email address": 2, "OpenAI key": 1})) == (
        "1 OpenAI key, 2 email addresses"
    )
    assert secrets_in(f"mail a@b.co with {GITHUB}") == ["GitHub token"]
    assert secrets_in("mail a@b.co") == []
