"""Take secrets and email addresses out of the evidence before it is committed (ADR 0073).

The evidence in ``.modelbump/`` holds every prompt, every answer and every
error message of the test run. A prompt can quote a document with an email
address in it, an answer can repeat it, and an error message can carry a key:
Google's API puts the key in the request URL. The bump commits these files,
so each one is scanned first and each match is replaced with
``[REDACTED:kind]``.

The patterns find keys in the formats providers publish, private key blocks,
bearer tokens and JSON web tokens, and email addresses (except the reserved
``example.com``, ``example.org`` and ``example.net`` ones that tests use).
Names, street addresses and phone numbers cannot be told apart from ordinary
text by a pattern, so they are not looked for: the pull request asks the
reviewer to read the evidence before merging.

The files are JSON, so a match never takes a backslash in front of it (that
would split an escape such as ``\\n``), and the redacted text is parsed again
to be sure it is still valid.
"""

import json
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

REDACTED = "[REDACTED:{kind}]"

# Order matters: the more specific pattern comes first (Anthropic before OpenAI).
_SECRETS: tuple[tuple[str, str], ...] = (
    (
        "private key",
        r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----.*?-----END (?:[A-Z0-9]+ )*PRIVATE KEY-----",
    ),
    ("Anthropic key", r"sk-ant-[A-Za-z0-9_-]{20,}"),
    # Real keys are long and random; the digit keeps out words like "sk-learn-...".
    ("OpenAI key", r"sk-(?:proj-|svcacct-|admin-)?(?=[A-Za-z_-]*[0-9])[A-Za-z0-9_-]{32,}"),
    ("Google API key", r"AIza[0-9A-Za-z_-]{35,}"),
    ("GitHub token", r"gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,}"),
    ("AWS access key", r"(?:AKIA|ASIA)[0-9A-Z]{16}(?![0-9A-Za-z])"),
    ("Groq key", r"gsk_[A-Za-z0-9]{40,}"),
    ("Hugging Face token", r"hf_[A-Za-z0-9]{30,}"),
    ("Slack token", r"xox[abprs]-[A-Za-z0-9-]{10,}"),
    ("JSON web token", r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    ("bearer token", r"(?<=[Bb]earer )[A-Za-z0-9._~+/-]{20,}=*"),
)
_EMAIL = (
    "email address",
    r"[A-Za-z0-9._%+-]+@(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}",
)
_EXAMPLE_EMAIL = re.compile(r"@(?:[A-Za-z0-9-]+\.)*example\.(?:com|org|net)$", re.IGNORECASE)

# One pattern with a named group per kind. A match never starts right after a
# backslash, so it cannot split a JSON escape. A secret also never starts inside
# a word ("task-..."), but may follow an escape such as \n.
_SECRET_START = r"(?:(?<![A-Za-z0-9_\\])|(?<=\\[nrtbf]))"
_EMAIL_START = r"(?<!\\)"
_KINDS = [kind for kind, _ in (*_SECRETS, _EMAIL)]
_PATTERN = re.compile(
    "|".join(
        rf"(?P<k{i}>{_EMAIL_START if kind == _EMAIL[0] else _SECRET_START}{pattern})"
        for i, (kind, pattern) in enumerate((*_SECRETS, _EMAIL))
    ),
    re.DOTALL,
)


@dataclass(frozen=True, slots=True)
class Redacted:
    """A text with its secrets replaced, and what was replaced."""

    text: str
    found: Counter[str]
    """How many of each kind, e.g. ``{"OpenAI key": 1, "email address": 2}``."""


def redact(text: str) -> Redacted:
    """Replace every secret and email address in ``text`` with ``[REDACTED:kind]``."""
    found: Counter[str] = Counter()

    def replace(match: re.Match[str]) -> str:
        kind = _KINDS[int(str(match.lastgroup)[1:])]
        if kind == _EMAIL[0] and _EXAMPLE_EMAIL.search(match.group()):
            return match.group()
        found[kind] += 1
        return REDACTED.format(kind=kind)

    return Redacted(_PATTERN.sub(replace, text), found)


def redact_json(text: str, name: str) -> Redacted:
    """Redact a JSON file's text, keeping its layout; raise ValueError if it breaks."""
    result = redact(text)
    if result.found:
        try:
            json.loads(result.text)
        except json.JSONDecodeError as error:  # pragma: no cover - guarded by the patterns
            raise ValueError(f"redacting {name} would break its JSON: {error}") from error
    return result


def secrets_in(text: str) -> list[str]:
    """The kinds of secret in ``text`` (email addresses not counted), for patch checks."""
    found = redact(text).found
    return sorted(kind for kind in found if kind != _EMAIL[0])


def summary(found: Counter[str]) -> str:
    """``1 OpenAI key, 2 email addresses``."""
    return ", ".join(f"{count} {_plural(kind, count)}" for kind, count in sorted(found.items()))


def total(counts: Iterable[Counter[str]]) -> Counter[str]:
    """Add up the counts of several files."""
    out: Counter[str] = Counter()
    for count in counts:
        out.update(count)
    return out


def _plural(kind: str, count: int) -> str:
    if count == 1:
        return kind
    return kind + ("es" if kind.endswith("s") else "s")
