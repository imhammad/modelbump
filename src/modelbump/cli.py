"""Command-line interface for ModelBump."""

from typing import Annotated

import typer

from modelbump import __version__

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
