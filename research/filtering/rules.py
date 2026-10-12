"""The rules that label one candidate commit. Each rule is a small pure function.

The rules follow Kim (2026, Section 3): a migration commit uses a migration
word, moves away from the retired model (not into it), is not made more than
30 days before the deprecation notice, and is not written by a dependency bot
or an AI tool. We record every rule as a flag instead of deleting commits, so
each count in the paper can be recomputed with or without any rule (ADR 0012).
"""

import re
from collections.abc import Mapping, Sequence
from datetime import date
from functools import cache
from typing import Literal

Direction = Literal["away", "into", "unclear"]

# Kim's migration words, with their common forms. Explicit forms instead of a
# prefix like "drop*", which would also match "dropdown".
MIGRATION_WORD = re.compile(
    r"\b(migrat(e|ed|es|ing|ion|ions)"
    r"|replac(e|ed|es|ing|ement|ements)"
    r"|switch(|ed|es|ing)"
    r"|upgrad(e|ed|es|ing)"
    r"|updat(e|ed|es|ing)"
    r"|remov(e|ed|es|ing|al)"
    r"|drop(|s|ped|ping)"
    r"|swap(|s|ped|ping)"
    r"|retir(e|ed|es|ing|ement)"
    r"|deprecat(e|ed|es|ing|ion)"
    r"|sunset(|s|ting)"
    r"|shut(|s|ting) ?down)\b",
    re.IGNORECASE,
)

# A trailer an AI coding tool adds to the commits it writes or co-writes.
AI_TRAILER = re.compile(
    r"^(co-authored-by:.*\b(claude|copilot|cursor|codex|devin|aider|gemini|openai|chatgpt)\b"
    r"|.*generated (with|by) .*\b(claude|copilot|cursor|codex|aider|gemini|chatgpt)\b)",
    re.IGNORECASE | re.MULTILINE,
)

# A first line that reads like a chat assistant talking, not a commit message.
AI_STYLE = re.compile(
    r"^\s*(I'll|I will|I've|I have|Here's|Here is|Sure|Certainly|Great|Let me)\b",
    re.IGNORECASE,
)

# Dependency bots: Dependabot, Renovate and their "Bump x from 1 to 2" titles.
BOT = re.compile(r"\b(dependabot|renovate)\b|^bump [\w./@-]+ from \S+ to \S+", re.I | re.M)

QUOTE = r"[`'\"(\[]?"
END_QUOTE = r"[`'\")\]]?"
# What follows "X to": something that looks like a model ID (has a digit or a
# hyphen), so "set model to gpt-4 to save cost" is not read as gpt-4 -> "save".
NEXT_MODEL = r"[`'\"]?[a-z][\w.]*(-[\w.]+|\d)"
ADJECTIVES = (
    r"(?:(?:the|old|older|legacy|deprecated|retired|outdated|discontinued|unavailable|dead"
    r"|stale|invalid|broken|non-existent|model|id)\s+)*"
)
# A word that says the model itself is gone or going: "X was retired", "X, which
# is no longer served", "X returns 404". Rules v2 (ADR 0014).
GONE = (
    r"(deprecat\w*|retir\w*|discontinu\w*|sunset\w*|removed|shut ?down|no longer\b"
    r"|not available|unavailable|404)"
)
# Removal verbs as whole words, so "dropdown" is not "drop".
REMOVE = r"(remove[sd]?|removing|drop(s|ped|ping)?|purge[sd]?|purging|deactivate[sd]?|deactivating)"
# Words that may sit between "to" and the ID: "switch embeddings to Gemini text-embedding-004".
FILLERS = (
    r"(?:(?:the|a|new|newer|latest|model|models|openai|anthropic|google|gemini|claude|azure"
    r"|vertex|ai)\s+){0,3}"
)


def _id(model_id: str) -> str:
    """The ID as a whole word, as in research.mining.miner.mentions."""
    return rf"(?<![\w.-]){re.escape(model_id)}(?![\w-]|\.\w)"


def has_migration_word(message: str) -> bool:
    """True if the message uses one of Kim's migration words, in any common form."""
    return MIGRATION_WORD.search(message) is not None


def direction(message: str, model_id: str) -> Direction:
    """Whether the commit moves away from ``model_id``, into it, or neither is clear.

    "away" wins when both match: in "from gpt-4 to gpt-4-turbo" the commit moves
    away from gpt-4 even though gpt-4-turbo (also retired) is the target.
    """
    away, into = _direction_patterns(model_id)
    if away.search(message):
        return "away"
    if into.search(message):
        return "into"
    return "unclear"


@cache
def _direction_patterns(model_id: str) -> tuple[re.Pattern[str], re.Pattern[str]]:
    """The "away" and "into" patterns for one ID, compiled once."""
    mid = _id(model_id)
    away = [
        rf"\bfrom\s+{ADJECTIVES}{QUOTE}{mid}",
        rf"{mid}{END_QUOTE}\s*(->|=>|→|➡|\bto\b)\s*{NEXT_MODEL}",
        rf"\b(replac|swap|switch|migrat|mov|upgrad)\w*\s+{ADJECTIVES}{QUOTE}{mid}{END_QUOTE}"
        rf"\s+(with|to|for|by)\b",
        rf"\b(remov|drop|deprecat|retir|sunset)\w*\s+(support\s+for\s+)?{ADJECTIVES}"
        rf"{QUOTE}{mid}",
        rf"\bdeprecated\s+(model\s+)?{QUOTE}{mid}",
        rf"{mid}{END_QUOTE}\s+(is|was|has been|will be|being|got)\s+"
        rf"(deprecated|retired|removed|shut ?down|sunset)",
        # Rules v2 (ADR 0014), from the validation sample's misses.
        rf"{mid}{END_QUOTE}\s+model\s+(->|=>|→|➡|\bto\b)\s*{NEXT_MODEL}",
        rf"{mid}{END_QUOTE}[^.\n;]{{0,40}}?\b{GONE}",
        rf"\b{REMOVE}\b[^\n]{{0,60}}?{QUOTE}{mid}",
        rf"\b(replaces|supersedes)\s+{ADJECTIVES}{QUOTE}{mid}",
    ]
    into = [
        rf"\b(to|use|uses|using|default(s|ed)?\s+to|revert(s|ed|ing)?\s+to|back\s+to)\s+"
        rf"{FILLERS}{QUOTE}{mid}",
        rf"(->|=>|→|➡)\s*{QUOTE}{mid}",
        rf"\breplac\w*\b.{{0,60}}?\bwith\s+{QUOTE}{mid}",
    ]
    return (
        re.compile("|".join(f"(?:{p})" for p in away), re.IGNORECASE),
        re.compile("|".join(f"(?:{p})" for p in into), re.IGNORECASE),
    )


def commit_direction(message: str, model_ids: Sequence[str]) -> Direction:
    """Away if the commit moves away from any of its IDs; into if only into."""
    found = [direction(message, model_id) for model_id in model_ids]
    if "away" in found:
        return "away"
    if "into" in found:
        return "into"
    return "unclear"


def after_notice_start(
    committed: date, model_ids: Sequence[str], starts: Mapping[str, date]
) -> bool | None:
    """Whether the commit is on or after notice minus 30 days; None if no date is known."""
    known = [starts[model_id] for model_id in model_ids if model_id in starts]
    if not known:
        return None
    return committed >= min(known)


def has_ai_trailer(message: str) -> bool:
    return AI_TRAILER.search(message) is not None


def has_ai_style(message: str) -> bool:
    return AI_STYLE.match(message) is not None


def is_bot(message: str) -> bool:
    return BOT.search(message) is not None
