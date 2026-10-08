"""Command-line interface for ModelBump."""

from datetime import date
from typing import Annotated

import typer

from modelbump import __version__
from modelbump.registry import Status, load_registry

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
def scan(path: Annotated[str, typer.Argument(help="Repository to scan.")] = ".") -> None:
    """Find LLM model dependencies in a repository (coming in Phase 2)."""
    typer.echo(f"Scanning {path} ... not implemented yet.")


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
