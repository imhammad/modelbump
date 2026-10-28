"""Pick an oracle for each LLM call from what the call asks for (ADR 0052).

The order is fixed, and the first rule that fits wins:

1. The call passes ``tools=`` or ``functions=``: a tool call (not scored yet).
2. The call's settings ask for JSON (``response_format`` and the like): JSON.
3. The prompt says "JSON": JSON.
4. The prompt lists the allowed answers ("one label: bug, feature, question",
   "one of: a, b", "yes or no"): a label.
5. Anything else: free text.
"""

import re
import string
from dataclasses import dataclass
from enum import StrEnum

from modelbump.synth.callsites import CallSite

MIN_LABELS = 2
MAX_LABELS = 20
MAX_LABEL_WORDS = 3


class OutputKind(StrEnum):
    """What kind of answer a call expects, which decides how answers are checked."""

    JSON = "json"
    LABEL = "label"
    TEXT = "text"
    TOOLS = "tools"


@dataclass(frozen=True, slots=True)
class OracleChoice:
    """The oracle picked for one call, and why."""

    kind: OutputKind
    reason: str
    """Short and for people: ``prompt lists labels: bug, feature, question``."""
    labels: tuple[str, ...] = ()
    """The allowed answers, for :attr:`OutputKind.LABEL`, normalized."""


_JSON_WORD = re.compile(r"\bjson\b", re.IGNORECASE)
# "Answer with one label: a, b, c." / "Reply with one of: a, b or c" / "one word from: ..."
_LIST_INTRO = re.compile(
    r"\b(?:one|a single|exactly one)\s+(?:of\s+(?:these|the following)\s+)?"
    r"(?:labels?|words?|categor(?:y|ies)|class(?:es)?|options?|values?|of)\b"
    r"[^:\n]{0,40}?(?:from|:)\s*(?P<items>[^\n]+)",
    re.IGNORECASE,
)
_YES_NO = re.compile(r"\b(?:answer|reply|respond)\b[^\n]{0,40}\byes\s+or\s+no\b", re.IGNORECASE)
_SPLIT = re.compile(r"\s*(?:,|\||/|;|\bor\b)\s*", re.IGNORECASE)


def normalize_label(text: str) -> str:
    """Lowercase, trimmed, without quotes, brackets or a full stop at the end."""
    return text.strip(" \t\n\"'`*[](){}<>.!").lower()


def _labels_in(text: str) -> tuple[str, ...]:
    """The allowed answers listed in a prompt, or () when it lists none."""
    if _YES_NO.search(text):
        return ("yes", "no")
    for match in _LIST_INTRO.finditer(text):
        items = match.group("items")
        if "{" in items:
            continue  # The list is filled in at run time: unknown here.
        # Stop at the first sentence end that is not inside the list.
        items = re.split(r"\.\s|\.$", items, maxsplit=1)[0]
        labels = [normalize_label(item) for item in _SPLIT.split(items)]
        labels = [label for label in labels if label]
        if (
            MIN_LABELS <= len(labels) <= MAX_LABELS
            and all(len(label.split()) <= MAX_LABEL_WORDS for label in labels)
            and len(set(labels)) == len(labels)
        ):
            return tuple(labels)
    return ()


def _written(template: str) -> str:
    """The template's written text, with each slot as ``{}``: a slot named
    ``json.dumps(x)`` is code, not an ask for JSON."""
    return "".join(
        literal + ("{}" if name is not None else "")
        for literal, name, _, _ in string.Formatter().parse(template)
    )


def choose_oracle(site: CallSite) -> OracleChoice:
    """The oracle for one call site, by the rules at the top of this module."""
    if site.output == "tools":
        return OracleChoice(
            OutputKind.TOOLS, "the call passes tools (tool calls are not scored yet)"
        )
    if site.output == "json":
        return OracleChoice(OutputKind.JSON, "the call's settings ask for JSON")
    texts = [_written(part.template) for part in site.parts if part.template is not None]
    if any(_JSON_WORD.search(text) for text in texts):
        return OracleChoice(OutputKind.JSON, 'the prompt says "JSON"')
    for text in texts:
        labels = _labels_in(text)
        if labels:
            return OracleChoice(
                OutputKind.LABEL, f"the prompt lists labels: {', '.join(labels)}", labels
            )
    if not texts:
        return OracleChoice(OutputKind.TEXT, "no prompt text was read, so free text")
    return OracleChoice(OutputKind.TEXT, "free text (no JSON or label list in the prompt)")
