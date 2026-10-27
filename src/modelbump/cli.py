"""Command-line interface for ModelBump."""

import asyncio
import random
from datetime import date, datetime
from pathlib import Path
from typing import Annotated

import typer

from modelbump import __version__
from modelbump.registry import Status, load_registry
from modelbump.runner import (
    Budget,
    BudgetExceeded,
    ChatRequest,
    ChatResult,
    ResponseCache,
    Runner,
    RunnerError,
    list_local_models,
    pin_versions,
    resolve_model,
)
from modelbump.scanner import DEFAULT_SOON_DAYS, scan_path
from modelbump.scanner.report import (
    RENDERERS,
    OutputFormat,
    build_report,
    failure_line,
    summary_line,
)
from modelbump.stats import (
    DEFAULT_ALPHA,
    DEFAULT_MARGIN,
    DEFAULT_MAX_RUNS,
    Verdict,
    compare_counts,
    run_sequential,
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
    prompts: Annotated[
        list[str], typer.Argument(help="What to ask the model. Give several to ask them all.")
    ],
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
    budget_tokens: Annotated[
        int | None,
        typer.Option(min=1, help="Stop sending requests after this many tokens (in + out)."),
    ] = None,
    budget_requests: Annotated[
        int | None,
        typer.Option(min=1, help="Stop after this many requests to the model, retries included."),
    ] = None,
    think: Annotated[
        str | None,
        typer.Option(
            help="Reasoning effort for thinking models: none, low, medium or high. "
            "Leave it out for the model's default."
        ),
    ] = None,
) -> None:
    """Send prompts to a model and print the answers (to try the runner)."""
    requests = [
        ChatRequest.ask(
            model,
            prompt,
            system,
            temperature=temperature,
            max_tokens=max_tokens,
            seed=seed,
            sample=sample,
            reasoning_effort=think,
        )
        for prompt in prompts
    ]
    try:
        endpoint, _ = resolve_model(model)
        requests = pin_versions(requests)
    except ValueError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=1) from error
    except RunnerError as error:
        _print_error(error, model)
        raise typer.Exit(code=1) from error
    if not endpoint.local:
        typer.echo(
            f"Note: {endpoint.name} is a free cloud tier. Your prompts leave this machine "
            "and may be kept or read by the provider. Never send private data.",
            err=True,
        )
    cache = ResponseCache() if use_cache else None
    budget = Budget(max_tokens=budget_tokens, max_requests=budget_requests)
    runner = Runner(timeout=timeout, max_attempts=attempts, cache=cache, budget=budget)
    try:
        outcomes = asyncio.run(runner.run_each(requests))
    finally:
        if cache is not None:
            cache.close()
    failed = False
    for prompt, outcome in zip(prompts, outcomes, strict=True):
        if len(prompts) > 1:
            typer.echo(f"## {prompt}")
        if isinstance(outcome, RunnerError):
            failed = True
            _print_error(outcome, model)
            continue
        typer.echo(outcome.text)
        typer.echo(_result_line(outcome), err=True)
    if len(prompts) > 1 or budget_tokens is not None or budget_requests is not None:
        typer.echo(budget.summary(), err=True)
    if any(isinstance(o, BudgetExceeded) for o in outcomes):
        typer.echo(
            "Answers so far are cached: run the same command with a higher limit to continue.",
            err=True,
        )
    if failed:
        raise typer.Exit(code=1)


def _print_error(error: RunnerError, model: str) -> None:
    typer.echo(f"Error: {error}", err=True)
    if model.startswith("ollama/") and "could not reach" in str(error):
        typer.echo("Is Ollama running? Start it with: open -a Ollama", err=True)


@app.command()
def models() -> None:
    """List the models pulled into Ollama, with the digest that pins each one."""
    try:
        found = list_local_models()
    except RunnerError as error:
        _print_error(error, "ollama/")
        raise typer.Exit(code=1) from error
    if not found:
        typer.echo("No models yet. Pull one with: ollama pull qwen2.5:7b")
        return
    width = max(len(m.name) for m in found)
    typer.echo(f"{'MODEL':<{width + 7}}  PARAMS  QUANT    SIZE     DIGEST")
    for m in found:
        size = f"{m.size_bytes / 1e9:.1f} GB"
        typer.echo(
            f"{'ollama/' + m.name:<{width + 7}}  {m.parameter_size:<6}  {m.quantization:<7}  "
            f"{size:<7}  {m.digest[:12]}"
        )


def _result_line(result: ChatResult) -> str:
    if result.cached:
        how = "from cache"
    else:
        tries = "attempt" if result.attempts == 1 else "attempts"
        how = f"{result.attempts} {tries}, {result.seconds:.1f}s"
    return (
        f"[{result.model}: {result.input_tokens} tokens in, {result.output_tokens} out, "
        f"{how}, finish: {result.finish_reason}]"
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


stats_app = typer.Typer(
    help="Decide whether a new model is worse than the old one.", no_args_is_help=True
)
app.add_typer(stats_app, name="stats")

_VERDICT_MEANING = {
    Verdict.REGRESSED: "the new model is worse on this test case",
    Verdict.IMPROVED: "the new model is better on this test case",
    Verdict.EQUIVALENT: "the two models differ by less than the margin",
    Verdict.INCONCLUSIVE: "not enough answers to tell; run more samples",
}


def _parse_count(text: str, which: str) -> tuple[int, int]:
    passes, slash, runs = text.partition("/")
    if not slash or not passes.strip().isdigit() or not runs.strip().isdigit():
        raise typer.BadParameter(f"write {which} as PASSES/RUNS, for example 9/10; got {text!r}")
    return int(passes), int(runs)


@stats_app.command("item")
def stats_item(
    old: Annotated[
        str, typer.Argument(metavar="OLD", help="Old model's passes/runs, for example 9/10.")
    ],
    new: Annotated[
        str, typer.Argument(metavar="NEW", help="New model's passes/runs, for example 4/10.")
    ],
    margin: Annotated[
        float,
        typer.Option(
            help="Largest change in pass rate that still counts as the same (0.1 = 10 points)."
        ),
    ] = DEFAULT_MARGIN,
    alpha: Annotated[
        float, typer.Option(help="Chance of a wrong REGRESSED, IMPROVED or EQUIVALENT claim.")
    ] = DEFAULT_ALPHA,
) -> None:
    """Compare pass counts of the old and new model on one test case."""
    old_passes, old_runs = _parse_count(old, "OLD")
    new_passes, new_runs = _parse_count(new, "NEW")
    try:
        result = compare_counts(
            old_passes, old_runs, new_passes, new_runs, alpha=alpha, margin=margin
        )
    except ValueError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=2) from error
    typer.echo(f"Old model: {old_passes}/{old_runs} passed ({result.old_rate:.1%})")
    typer.echo(f"New model: {new_passes}/{new_runs} passed ({result.new_rate:.1%})")
    typer.echo(
        f"Difference (new - old): {result.difference * 100:+.1f} points, "
        f"{result.confidence:.0%} interval {result.interval.low * 100:+.1f} "
        f"to {result.interval.high * 100:+.1f}"
    )
    typer.echo(f"Verdict: {result.verdict} ({_VERDICT_MEANING[result.verdict]})")


def _check_rate(rate: float, which: str) -> float:
    if not 0 <= rate <= 1:
        raise typer.BadParameter(f"{which} must be between 0 and 1, got {rate}")
    return rate


@stats_app.command("simulate")
def stats_simulate(
    old_rate: Annotated[
        float, typer.Argument(metavar="OLD_RATE", help="Old model's true pass rate, e.g. 0.9.")
    ],
    new_rate: Annotated[
        float, typer.Argument(metavar="NEW_RATE", help="New model's true pass rate, e.g. 0.6.")
    ],
    seed: Annotated[int, typer.Option(help="Random seed, so a run can be repeated.")] = 1,
    max_runs: Annotated[
        int, typer.Option(help="Stop with INCONCLUSIVE after this many answers per model.")
    ] = DEFAULT_MAX_RUNS,
    margin: Annotated[
        float,
        typer.Option(
            help="Largest change in pass rate that still counts as the same (0.1 = 10 points)."
        ),
    ] = DEFAULT_MARGIN,
    alpha: Annotated[
        float, typer.Option(help="Chance of a wrong REGRESSED, IMPROVED or EQUIVALENT claim.")
    ] = DEFAULT_ALPHA,
) -> None:
    """Pretend two models answer one test case, and stop as soon as the verdict is clear."""
    _check_rate(old_rate, "OLD_RATE")
    _check_rate(new_rate, "NEW_RATE")
    rng = random.Random(seed)

    def next_round() -> tuple[bool, bool]:
        return rng.random() < old_rate, rng.random() < new_rate

    try:
        result = run_sequential(next_round, alpha=alpha, margin=margin, max_runs=max_runs)
    except ValueError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=2) from error
    typer.echo(
        f"Simulated test case: old model passes {old_rate:.0%}, new model {new_rate:.0%} "
        f"(seed {seed})"
    )
    how = "Stopped early" if result.stopped_early else "Reached --max-runs"
    typer.echo(
        f"{how} after {result.runs} answers per model "
        f"(old {result.old_passes}/{result.runs}, new {result.new_passes}/{result.runs})"
    )
    typer.echo(f"Verdict: {result.verdict} ({_VERDICT_MEANING[result.verdict]})")
    evidence = result.evidence
    typer.echo(
        f"Evidence (a claim is proven at {1 / alpha:g}): regressed {evidence.regressed:.1f}, "
        f"improved {evidence.improved:.1f}, equivalent {evidence.equivalent:.1f}"
    )
