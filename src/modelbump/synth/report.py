"""Reports for ``modelbump prompts``: a short text listing or full JSON."""

import json
from enum import StrEnum

from modelbump.synth.callsites import CallSite, CallSiteResult, PromptPart
from modelbump.synth.cases import CaseResult, SiteCases, TestCase

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


def cases_summary(result: CaseResult) -> str:
    """One line: how many cases, for how many calls, and which calls still need inputs."""
    calls = len(result.sites)
    with_cases = sum(bool(s.cases) for s in result.sites)
    cases = result.cases
    complete = sum(c.complete for c in cases)
    line = (
        f"Found {len(cases)} test {_plural(len(cases), 'case')} ({complete} complete) "
        f"for {with_cases} of {calls} LLM {_plural(calls, 'call')}."
    )
    fixed = sum(_is_fixed(s.site) for s in result.sites)
    if fixed:
        line += f" {fixed} with a fixed prompt need no inputs."
    waiting = [s.site for s in result.sites if not s.cases and s.site.slots]
    if waiting:
        where = ", ".join(f"{site.path}:{site.line}" for site in waiting[:3])
        more = ", ..." if len(waiting) > 3 else ""
        line += f" No case yet for {len(waiting)} with slots ({where}{more})."
    if result.unparsed:
        line += f" {len(result.unparsed)} {_plural(len(result.unparsed), 'file')} did not parse."
    return line


def render_cases_text(result: CaseResult) -> str:
    """Each call with its cases: where the values come from, and the values."""
    lines: list[str] = []
    for entry in result.sites:
        site = entry.site
        lines.append(
            f"{site.path}:{site.line}  {site.api.value}  {site.call}  model: {_model(site)}"
        )
        if _is_fixed(site):
            lines.append("  fixed prompt: no slots to fill")
        elif not entry.cases:
            reason = f"slots: {', '.join(site.slots)}" if site.slots else "partial, no slots"
            lines.append(f"  no cases ({reason})")
        for case in entry.cases:
            values = ", ".join(f"{name}={_quote(value)}" for name, value in case.values)
            status = "" if case.complete else f"  (open slots: {', '.join(case.site.slots)})"
            lines.append(f"  {case.source}  {values}{status}")
    lines.extend(f"Could not parse {path}" for path in result.unparsed)
    lines.append(cases_summary(result))
    return "\n".join(lines) + "\n"


def render_cases_json(result: CaseResult) -> str:
    """Every call with its cases; complete cases carry their final messages."""
    data = {
        "version": JSON_VERSION,
        "files_read": result.files_read,
        "unparsed": list(result.unparsed),
        "calls": [_site_cases_json(entry) for entry in result.sites],
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


CASE_RENDERERS = {PromptFormat.TEXT: render_cases_text, PromptFormat.JSON: render_cases_json}


def _site_cases_json(entry: SiteCases) -> dict[str, object]:
    data = _call_json(entry.site)
    data["cases"] = [_case_json(case) for case in entry.cases]
    return data


def _case_json(case: TestCase) -> dict[str, object]:
    data: dict[str, object] = {
        "source": case.source,
        "values": dict(case.values),
        "complete": case.complete,
    }
    if case.complete:
        data["messages"] = [{"role": r, "content": text} for r, text in case.messages]
    else:
        data["parts"] = _call_json(case.site)["parts"]
        data["open_slots"] = list(case.site.slots)
    return data


def _is_fixed(site: CallSite) -> bool:
    return site.complete and not site.slots


def _quote(value: str) -> str:
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= 60 else text[:56] + '..."'


def _model(call: CallSite) -> str:
    if call.model is not None:
        return call.model
    if call.model_source is not None:
        return f"{call.model_source} (value not found in the code)"
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
