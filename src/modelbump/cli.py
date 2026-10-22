"""Command-line interface for ModelBump."""

from datetime import date, datetime
from pathlib import Path
from typing import Annotated

import typer

from modelbump import __version__
from modelbump.registry import Status, load_registry
from modelbump.scanner import DEFAULT_SOON_DAYS, scan_path
from modelbump.scanner.report import (
    RENDERERS,
    OutputFormat,
    build_report,
    failure_line,
    summary_line,
)

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
    output_format: Annotated[
        OutputFormat,
        typer.Option("--format", help="Report format: text, json or sarif."),
    ] = OutputFormat.TEXT,
    output: Annotated[
        Path | None,
        typer.Option(help="Write the report to this file instead of the screen.", dir_okay=False),
    ] = None,
) -> None:
    """Find the LLM model IDs in a repository's code and config, and how urgent each is."""
    registry = load_registry()
    day = today.date() if today is not None else date.today()
    report = build_report(scan_path(path, registry), registry, day, soon_days, fail_within)
    rendered = RENDERERS[output_format](report)
    if output is None:
        typer.echo(rendered, nl=False)
    else:
        output.write_text(rendered, encoding="utf-8")
        typer.echo(f"Wrote {output_format.value} report to {output}.")
        typer.echo(summary_line(report))
    failure = failure_line(report)
    if failure is not None:
        if output is not None or output_format is not OutputFormat.TEXT:
            # Keep the screen output a valid JSON or SARIF document.
            typer.echo(failure, err=True)
        raise typer.Exit(code=1)


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
