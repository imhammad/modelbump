"""Command-line interface for ModelBump."""

from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Annotated

import typer

from modelbump import __version__
from modelbump.registry import Status, load_registry
from modelbump.scanner import DEFAULT_SOON_DAYS, Assessment, Severity, assess, scan_path

app = typer.Typer(
    name="modelbump",
    help="Dependabot for LLM models.",
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"modelbump {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            "-V",
            help="Show the version and exit.",
            callback=_version_callback,
            is_eager=True,
        ),
    ] = False,
) -> None:
    """Dependabot for LLM models."""


@app.command()
def scan(
    path: Annotated[
        Path,
        typer.Argument(help="Folder or file to scan.", exists=True, resolve_path=True),
    ] = Path("."),
    soon_days: Annotated[
        int,
        typer.Option(
            min=0, help="Mark a model RETIRING_SOON when it shuts down within this many days."
        ),
    ] = DEFAULT_SOON_DAYS,
    fail_within: Annotated[
        int | None,
        typer.Option(
            min=0,
            help="Exit with code 1 if a model is retired or shuts down within this many days.",
        ),
    ] = None,
    today: Annotated[
        datetime | None,
        typer.Option(
            formats=["%Y-%m-%d"],
            help="Check as if today were this day (YYYY-MM-DD), to replay the past.",
        ),
    ] = None,
) -> None:
    """Find the LLM model IDs in a repository's code and config, and how urgent each is."""
    registry = load_registry()
    result = scan_path(path, registry)
    day = today.date() if today is not None else date.today()
    counts: Counter[Severity] = Counter()
    failing = 0
    for finding in result.findings:
        assessment = assess(finding.registry_id, registry, day, soon_days)
        counts[assessment.severity] += 1
        days_left = assessment.days_left
        if fail_within is not None and days_left is not None and days_left <= fail_within:
            failing += 1
        written = finding.model_id
        if finding.registry_id is not None and finding.registry_id != written:
            written += f" (= {finding.registry_id})"
        typer.echo(
            f"{finding.path}:{finding.line}:{finding.column}  {written}  "
            f"{assessment.severity.name}  {_describe(assessment)}"
        )
    files = f"scanned {_plural(result.files_scanned, 'file')}"
    if result.files_skipped:
        files += f", skipped {result.files_skipped} too big or binary"
    if not result.findings:
        typer.echo(f"No model IDs found ({files}).")
        return
    ids = _plural(len(result.findings), "model ID")
    in_files = _plural(len({finding.path for finding in result.findings}), "file")
    levels = ", ".join(f"{counts[s]} {s.name}" for s in Severity if counts[s])
    typer.echo(f"Found {ids} in {in_files} ({files}): {levels}.")
    if failing:
        verb = "is" if failing == 1 else "are"
        typer.echo(
            f"Failed: {_plural(failing, 'model ID')} {verb} retired "
            f"or shut down within {_plural(fail_within or 0, 'day')}."
        )
        raise typer.Exit(code=1)


def _describe(assessment: Assessment) -> str:
    if assessment.shutdown is None or assessment.days_left is None:
        return "no retirement announced"
    days = assessment.days_left
    if days <= 0:
        text = f"shut down on {assessment.shutdown}"
        if assessment.shutdown_is_earliest:
            text = f"shut down no earlier than {assessment.shutdown}"
    else:
        when = "no earlier than" if assessment.shutdown_is_earliest else "on"
        text = f"shuts down {when} {assessment.shutdown} (in {_plural(days, 'day')})"
    if assessment.replacement:
        text += f"; suggested replacement {assessment.replacement}"
    return text


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


@app.command()
def check(
    model_id: Annotated[str, typer.Argument(help="Model ID, e.g. claude-3-haiku-20240307.")],
) -> None:
    """Look up one model ID in the retirement registry."""
    found = load_registry().get(model_id)
    if found is None:
        typer.echo(f"{model_id}: no retirement announced (not in the registry).")
        return
    provider, model = found
    status = model.status_on(date.today())
    if status is Status.RETIRED:
        line = f"RETIRED since {model.shutdown}"
        if model.shutdown_is_earliest:
            line += " (the earliest possible date the provider gave)"
    elif model.shutdown_is_earliest:
        line = f"{status.value.upper()}, shuts down no earlier than {model.shutdown}"
    else:
        line = f"{status.value.upper()}, shuts down on {model.shutdown}"
    typer.echo(f"{model_id} ({provider.value}): {line}.")
    if model.superseded:
        typer.echo(f"Rescheduled: {len(model.superseded)} earlier plan(s) were replaced.")
    if model.replacement:
        typer.echo(f"Suggested replacement: {model.replacement}")
