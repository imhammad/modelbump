"""Command-line interface for ModelBump."""

from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from modelbump import __version__
from modelbump.registry import Status, load_registry
from modelbump.scanner import scan_path

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
) -> None:
    """Find the LLM model IDs in a repository's code and config."""
    registry = load_registry()
    result = scan_path(path, registry)
    today = date.today()
    for finding in result.findings:
        found = registry.get(finding.model_id)
        status = found[1].status_on(today).value if found else "not in registry"
        typer.echo(f"{finding.path}:{finding.line}:{finding.column}  {finding.model_id}  {status}")
    files = f"scanned {_plural(result.files_scanned, 'file')}"
    if result.files_skipped:
        files += f", skipped {result.files_skipped} too big or binary"
    if not result.findings:
        typer.echo(f"No model IDs found ({files}).")
        return
    ids = _plural(len(result.findings), "model ID")
    in_files = _plural(len({finding.path for finding in result.findings}), "file")
    typer.echo(f"Found {ids} in {in_files} ({files}).")


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
