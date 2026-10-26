"""Command-line interface for ModelBump."""

import asyncio
from datetime import date, datetime
from pathlib import Path
from typing import Annotated

import typer

from modelbump import __version__
from modelbump.registry import Status, load_registry
from modelbump.runner import ChatRequest, ResponseCache, Runner, RunnerError
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
    exclude: Annotated[
        list[str] | None,
        typer.Option(
            help="Skip paths matching this pattern, e.g. 'tests' or '*.ipynb'. Repeat for more.",
        ),
    ] = None,
    skip_comments: Annotated[
        bool,
        typer.Option(
            help="Leave out IDs that only describe a model: comments, docstrings, "
            "sentences and price tables.",
        ),
    ] = False,
    skip_tests: Annotated[
        bool,
        typer.Option(help="Leave out test files and test folders."),
    ] = False,
    output: Annotated[
        Path | None,
        typer.Option(help="Write the report to this file instead of the screen.", dir_okay=False),
    ] = None,
) -> None:
    """Find the LLM model IDs in a repository's code and config, and how urgent each is."""
    registry = load_registry()
    day = today.date() if today is not None else date.today()
    result = scan_path(path, registry, exclude or (), skip_comments, skip_tests)
    report = build_report(result, registry, day, soon_days, fail_within, _root_uri(path))
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


def _root_uri(path: Path) -> str:
    """The scan root relative to the working directory, for SARIF paths."""
    base = path.parent if path.is_file() else path
    try:
        relative = base.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return ""
    return "" if relative == "." else relative + "/"


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


@app.command()
def ask(
    prompt: Annotated[str, typer.Argument(help="What to ask the model.")],
    model: Annotated[
        str,
        typer.Option("--model", "-m", help="endpoint/model, e.g. ollama/qwen2.5:7b."),
    ] = "ollama/qwen2.5:7b",
    system: Annotated[str | None, typer.Option(help="A system message.")] = None,
    temperature: Annotated[float, typer.Option(min=0.0, help="Sampling temperature.")] = 0.0,
    max_tokens: Annotated[
        int | None, typer.Option(min=1, help="Longest answer, in tokens.")
    ] = None,
    seed: Annotated[
        int | None, typer.Option(help="Sampling seed, if the model supports it.")
    ] = None,
    sample: Annotated[
        int, typer.Option(min=0, help="Which repeated draw this is (0, 1, 2, ...).")
    ] = 0,
    timeout: Annotated[float, typer.Option(min=1.0, help="Seconds each attempt may take.")] = 120.0,
    attempts: Annotated[int, typer.Option(min=1, help="Tries before giving up.")] = 4,
    use_cache: Annotated[
        bool,
        typer.Option("--cache/--no-cache", help="Reuse a stored answer to the same request."),
    ] = True,
) -> None:
    """Send one prompt to a model and print the answer (to try the runner)."""
    request = ChatRequest.ask(
        model,
        prompt,
        system,
        temperature=temperature,
        max_tokens=max_tokens,
        seed=seed,
        sample=sample,
    )
    cache = ResponseCache() if use_cache else None
    runner = Runner(timeout=timeout, max_attempts=attempts, cache=cache)
    try:
        result = asyncio.run(runner.run(request))
    except (RunnerError, ValueError) as error:
        typer.echo(f"Error: {error}", err=True)
        if model.startswith("ollama/") and "could not reach" in str(error):
            typer.echo("Is Ollama running? Start it with: open -a Ollama", err=True)
        raise typer.Exit(code=1) from error
    finally:
        if cache is not None:
            cache.close()
    typer.echo(result.text)
    if result.cached:
        how = "from cache"
    else:
        tries = "attempt" if result.attempts == 1 else "attempts"
        how = f"{result.attempts} {tries}, {result.seconds:.1f}s"
    typer.echo(
        f"[{result.model}: {result.input_tokens} tokens in, {result.output_tokens} out, "
        f"{how}, finish: {result.finish_reason}]",
        err=True,
    )


cache_app = typer.Typer(help="Look at or empty the cache of model answers.", no_args_is_help=True)
app.add_typer(cache_app, name="cache")


@cache_app.command("info")
def cache_info() -> None:
    """Show where the cache is and how much it holds."""
    cache = ResponseCache()
    try:
        stats = cache.stats()
    finally:
        cache.close()
    typer.echo(f"Cache: {stats.path}")
    typer.echo(f"Answers stored: {stats.entries} ({stats.output_tokens} output tokens)")
    typer.echo(f"Size on disk: {stats.size_bytes / 1024:.1f} KiB")


@cache_app.command("clear")
def cache_clear(
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask for confirmation.")] = False,
) -> None:
    """Delete every stored answer."""
    cache = ResponseCache()
    try:
        if not yes:
            typer.confirm(f"Delete every answer stored in {cache.path}?", abort=True)
        deleted = cache.clear()
    finally:
        cache.close()
    typer.echo(f"Deleted {deleted} stored answers.")
