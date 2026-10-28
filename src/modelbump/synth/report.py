"""Reports for ``modelbump prompts``: a short text listing or full JSON."""

import json
from enum import StrEnum

from modelbump.synth.callsites import CallSite, CallSiteResult, PromptPart

JSON_VERSION = 1
_PREVIEW = 100


class PromptFormat(StrEnum):
    """Report formats for ``modelbump prompts --format``."""

    TEXT = "text"
    JSON = "json"


def summary_line(result: CallSiteResult) -> str:
    """One line: how many calls, how many complete, files read and unparsed."""
    calls = len(result.calls)
    files = len({call.path for call in result.calls})
    complete = sum(call.complete for call in result.calls)
    line = (
        f"Found {calls} LLM {_plural(calls, 'call')} in {files} {_plural(files, 'file')} "
        f"(read {result.files_read} Python {_plural(result.files_read, 'file')}): "
        f"{complete} with all prompt text, {calls - complete} partial."
    )
    if result.unparsed:
        line += f" {len(result.unparsed)} {_plural(len(result.unparsed), 'file')} did not parse."
    return line


def render_text(result: CallSiteResult) -> str:
    """A readable listing: each call, its model, and a preview of each message."""
    lines: list[str] = []
    for call in result.calls:
        status = "" if call.complete else "  (partial)"
        lines.append(f"{call.path}:{call.line}  {call.api.value}  {call.call}{status}")
        lines.append(f"  model: {_model(call)}")
        lines.extend(f"  {part.role}: {_preview(part)}" for part in call.parts)
        if not call.parts:
            lines.append("  (no prompt argument)")
        if call.slots:
            lines.append(f"  slots: {', '.join(call.slots)}")
    lines.extend(f"Could not parse {path}" for path in result.unparsed)
    lines.append(summary_line(result))
    return "\n".join(lines) + "\n"


def render_json(result: CallSiteResult) -> str:
    """Every call with its full templates, for the next synthesizer steps."""
    data = {
        "version": JSON_VERSION,
        "files_read": result.files_read,
        "unparsed": list(result.unparsed),
        "calls": [_call_json(call) for call in result.calls],
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


RENDERERS = {PromptFormat.TEXT: render_text, PromptFormat.JSON: render_json}


def _call_json(call: CallSite) -> dict[str, object]:
    return {
        "path": call.path,
        "line": call.line,
        "api": call.api.value,
        "call": call.call,
        "model": call.model,
        "model_source": call.model_source,
        "complete": call.complete,
        "slots": list(call.slots),
        "parts": [
            {
                "role": part.role,
                "template": part.template,
                "slots": list(part.slots),
                "line": part.line,
                "source": part.source,
            }
            for part in call.parts
        ],
    }


def _model(call: CallSite) -> str:
    if call.model is not None:
        return call.model
    if call.model_source is not None:
        return f"{call.model_source} (value not in this file)"
    return "(not given in the call)"


def _preview(part: PromptPart) -> str:
    if part.template is None:
        return f"(could not read: {part.source})"
    text = json.dumps(part.template, ensure_ascii=False)[1:-1]
    if len(text) > _PREVIEW:
        text = text[: _PREVIEW - 3] + "..."
    return f'"{text}"'


def _plural(count: int, word: str) -> str:
    return word if count == 1 else word + "s"
