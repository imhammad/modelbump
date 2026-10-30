"""Command-line interface for ModelBump."""

import asyncio
import json
import random
from collections import Counter
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from typing import Annotated

import typer

from modelbump import __version__
from modelbump.oracles import OutputKind
from modelbump.oracles.calibrate import DEFAULT_SEED as DEFAULT_SHEET_SEED
from modelbump.oracles.calibrate import DEFAULT_SIZE as DEFAULT_SHEET_SIZE
from modelbump.oracles.calibrate import agreement, agreement_lines, make_sheet
from modelbump.oracles.judge import DEFAULT_JUDGE
from modelbump.oracles.probes import (
    DEFAULT_BREAKER,
    DEFAULT_PER_KIND,
    check_probes,
    make_probes,
    probe_lines,
    write_probes,
)
from modelbump.oracles.probes import DEFAULT_SEED as DEFAULT_PROBE_SEED
from modelbump.oracles.report import oracles_summary, render_oracles_json, render_oracles_text
from modelbump.registry import Status, load_registry
from modelbump.repair import (
    DEFAULT_CANDIDATES,
    DEFAULT_PROPOSER,
    apply_patches,
    call_of,
    patch_diff,
    patches_to_json,
    propose,
    read_patches,
    write_proposals,
)
from modelbump.repair.loop import (
    DEFAULT_CONFIRM_RUNS,
    DEFAULT_CONFIRM_TOP,
    DEFAULT_MAX_GAP,
    DEFAULT_SCREEN_RUNS,
    LoopSettings,
    read_candidates,
    repair_suite,
)
from modelbump.repair.optimize import DEFAULT_PER_ROUND, DEFAULT_ROUNDS, optimize
from modelbump.repair.propose import Strategy
from modelbump.repair.report import render_repair_json, render_repair_text
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
    DEFAULT_FDR,
    DEFAULT_MARGIN,
    DEFAULT_MAX_RUNS,
    Verdict,
    compare_counts,
    draw_score,
    run_sequential,
    run_suite,
    simulated_suite,
)
from modelbump.suite import Method, Settings, Suite, build_suite, read_suite, suite_to_json
from modelbump.suite.report import render_run_json, render_run_text, run_summary
from modelbump.suite.run import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_REFERENCE,
    DEFAULT_RUNS,
    DEFAULT_TEMPERATURE,
    run_suite_on_models,
)
from modelbump.synth import CallSiteResult, find_call_sites
from modelbump.synth.cases import CaseResult, SiteCases, find_cases
from modelbump.synth.generate import DEFAULT_GENERATOR, add_generated
from modelbump.synth.report import CASE_RENDERERS, PromptFormat, cases_summary
from modelbump.synth.report import RENDERERS as PROMPT_RENDERERS
from modelbump.synth.report import summary_line as prompts_summary

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
def prompts(
    path: Annotated[
        Path,
        typer.Argument(help="Folder or Python file to read.", exists=True, resolve_path=True),
    ] = Path("."),
    model: Annotated[
        str | None,
        typer.Option(help="Only list the calls to this model ID, e.g. gpt-4o-mini."),
    ] = None,
    output_format: Annotated[
        PromptFormat,
        typer.Option("--format", help="Report format: text or json."),
    ] = PromptFormat.TEXT,
    exclude: Annotated[
        list[str] | None,
        typer.Option(help="Skip paths matching this pattern, e.g. 'scripts'. Repeat for more."),
    ] = None,
    skip_tests: Annotated[
        bool,
        typer.Option(help="Leave out test files and test folders."),
    ] = False,
    output: Annotated[
        Path | None,
        typer.Option(help="Write the report to this file instead of the screen.", dir_okay=False),
    ] = None,
) -> None:
    """List the LLM calls in Python code, with each call's model and prompt template."""
    result = find_call_sites(path, exclude or (), skip_tests)
    if model is not None:
        kept = tuple(call for call in result.calls if call.model == model)
        result = CallSiteResult(kept, result.files_read, result.unparsed)
    rendered = PROMPT_RENDERERS[output_format](result)
    if output is None:
        typer.echo(rendered, nl=False)
    else:
        output.write_text(rendered, encoding="utf-8")
        typer.echo(f"Wrote {output_format.value} report to {output}.")
        typer.echo(prompts_summary(result))


@app.command()
def cases(
    path: Annotated[
        Path,
        typer.Argument(help="Folder or Python file to read.", exists=True, resolve_path=True),
    ] = Path("."),
    model: Annotated[
        str | None,
        typer.Option(help="Only list the calls to this model ID, e.g. gpt-4o-mini."),
    ] = None,
    output_format: Annotated[
        PromptFormat,
        typer.Option("--format", help="Report format: text or json."),
    ] = PromptFormat.TEXT,
    exclude: Annotated[
        list[str] | None,
        typer.Option(help="Do not list calls in paths matching this pattern. Repeat for more."),
    ] = None,
    skip_tests: Annotated[
        bool,
        typer.Option(help="Do not list calls made in test files (their inputs are still read)."),
    ] = False,
    output: Annotated[
        Path | None,
        typer.Option(help="Write the report to this file instead of the screen.", dir_okay=False),
    ] = None,
    generate: Annotated[
        int,
        typer.Option(
            min=0,
            help="Have a model write inputs until each call with slots has this many cases.",
        ),
    ] = 0,
    generator: Annotated[
        str,
        typer.Option(help="The model that writes inputs, as endpoint/model."),
    ] = DEFAULT_GENERATOR,
    budget_requests: Annotated[
        int | None,
        typer.Option(min=1, help="Stop after this many requests to the writer model."),
    ] = None,
) -> None:
    """Find test inputs for each LLM call: from the app's own tests and code, then generated.

    With --generate N, a model (local Qwen 2.5 by default) writes inputs for the
    calls that have fewer than N cases. Generated cases say which model wrote them.
    """
    result = find_cases(path, exclude or (), skip_tests)
    if model is not None:
        kept: tuple[SiteCases, ...] = tuple(s for s in result.sites if s.site.model == model)
        result = CaseResult(kept, result.files_read, result.unparsed)
    if generate > 0:
        result = _generate_cases(result, generate, generator, budget_requests)
    rendered = CASE_RENDERERS[output_format](result)
    if output is None:
        typer.echo(rendered, nl=False)
    else:
        output.write_text(rendered, encoding="utf-8")
        typer.echo(f"Wrote {output_format.value} report to {output}.")
        typer.echo(cases_summary(result))


def _generate_cases(
    result: CaseResult, count: int, generator: str, budget_requests: int | None
) -> CaseResult:
    """Run the writer model for `cases --generate`, with the cache and a budget."""
    try:
        endpoint, _ = resolve_model(generator)
        probe = pin_versions([ChatRequest.ask(generator, "version")])[0]
    except ValueError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=1) from error
    except RunnerError as error:
        _print_error(error, generator)
        raise typer.Exit(code=1) from error
    if not endpoint.local:
        typer.echo(
            f"Note: {endpoint.name} is a free cloud tier. The app's prompts leave this machine "
            "and may be kept or read by the provider. Never send private code.",
            err=True,
        )
    cache = ResponseCache()
    budget = Budget(max_requests=budget_requests)
    runner = Runner(cache=cache, budget=budget)
    try:
        done = asyncio.run(add_generated(result, runner, count, generator, probe.model_version))
    finally:
        cache.close()
    typer.echo(
        f"Asked {generator} for inputs for {done.asked} {'call' if done.asked == 1 else 'calls'}: "
        f"{done.added} generated {'case' if done.added == 1 else 'cases'}. {budget.summary()}",
        err=True,
    )
    for site, reason in done.skipped:
        typer.echo(f"  {site.path}:{site.line}: {reason}", err=True)
    return done.result


@app.command()
def suite(
    path: Annotated[
        Path,
        typer.Argument(help="Folder or Python file to read.", exists=True, resolve_path=True),
    ] = Path("."),
    output: Annotated[
        Path,
        typer.Option(help="Where to write the suite file.", dir_okay=False),
    ] = Path("modelbump-suite.json"),
    model: Annotated[
        str | None,
        typer.Option(help="Only the calls to this model ID, e.g. gpt-4o-mini."),
    ] = None,
    exclude: Annotated[
        list[str] | None,
        typer.Option(help="Leave out calls in paths matching this pattern. Repeat for more."),
    ] = None,
    skip_tests: Annotated[
        bool,
        typer.Option(help="Leave out calls made in test files (their inputs are still read)."),
    ] = False,
    generate: Annotated[
        int,
        typer.Option(
            min=0,
            help="Have a model write inputs until each call with slots has this many cases.",
        ),
    ] = 0,
    generator: Annotated[
        str,
        typer.Option(help="The model that writes inputs, as endpoint/model."),
    ] = DEFAULT_GENERATOR,
    budget_requests: Annotated[
        int | None,
        typer.Option(min=1, help="Stop after this many requests to the writer model."),
    ] = None,
) -> None:
    """Write a suite file: every complete test case, with its messages and its oracle."""
    result = find_cases(path, exclude or (), skip_tests)
    if model is not None:
        kept: tuple[SiteCases, ...] = tuple(s for s in result.sites if s.site.model == model)
        result = CaseResult(kept, result.files_read, result.unparsed)
    if generate > 0:
        result = _generate_cases(result, generate, generator, budget_requests)
    built = build_suite(result)
    output.write_text(suite_to_json(built), encoding="utf-8")
    calls = len({(c.path, c.line) for c in built.cases})
    typer.echo(
        f"Wrote {len(built.cases)} test {'case' if len(built.cases) == 1 else 'cases'} "
        f"for {calls} LLM {'call' if calls == 1 else 'calls'} to {output}."
    )
    for where, reason in built.left_out:
        typer.echo(f"  left out {where}: {reason}")


def _pinned(settings: Settings, cases: Suite, judge: str, no_judge: bool) -> Settings:
    """The settings with the judge chosen and each model pinned to its version.

    The judge is used only when the suite has free-text cases. Prints the
    privacy note when a model is on a free cloud tier.
    """
    has_text = any(c.oracle.kind is OutputKind.TEXT for c in cases.cases)
    judge_model = None if no_judge or not has_text else judge
    names = [settings.old, settings.new] + ([judge_model] if judge_model is not None else [])
    endpoints = [resolve_model(model_name)[0] for model_name in names]
    probes = pin_versions([ChatRequest.ask(name, "version") for name in names])
    if not all(endpoint.local for endpoint in endpoints):
        typer.echo(
            "Note: a free cloud tier is in use. The app's prompts leave this machine "
            "and may be kept or read by the provider. Never send private code.",
            err=True,
        )
    return replace(
        settings,
        old_version=probes[0].model_version,
        new_version=probes[1].model_version,
        judge=judge_model,
        judge_version=probes[2].model_version if judge_model is not None else "",
    )


@app.command("test")
def test_models(
    suite_file: Annotated[
        Path,
        typer.Argument(help="The suite file from `modelbump suite`.", exists=True, dir_okay=False),
    ],
    old: Annotated[
        str, typer.Option("--from", help="The model the app uses now, as endpoint/model.")
    ],
    new: Annotated[str, typer.Option("--to", help="The model to move to, as endpoint/model.")],
    runs: Annotated[
        int, typer.Option(min=1, help="Answers per model per case (the most, for sequential).")
    ] = DEFAULT_RUNS,
    reference: Annotated[
        int,
        typer.Option(min=1, help="Old-model answers per case that set the reference (not scored)."),
    ] = DEFAULT_REFERENCE,
    method: Annotated[
        Method,
        typer.Option(help="fixed (k + BH), sequential (+ e-BH), or auto (by --runs, ADR 0047)."),
    ] = Method.AUTO,
    from_think: Annotated[
        str | None,
        typer.Option(help="Reasoning effort for the --from model: none, low, medium or high."),
    ] = None,
    to_think: Annotated[
        str | None,
        typer.Option(help="Reasoning effort for the --to model, e.g. none for Qwen 3."),
    ] = None,
    temperature: Annotated[
        float, typer.Option(min=0.0, help="Sampling temperature for both models.")
    ] = DEFAULT_TEMPERATURE,
    max_tokens: Annotated[
        int, typer.Option(min=1, help="Longest answer, in tokens.")
    ] = DEFAULT_MAX_TOKENS,
    judge: Annotated[
        str,
        typer.Option(help="The model that judges free-text answers, as endpoint/model."),
    ] = DEFAULT_JUDGE,
    no_judge: Annotated[
        bool,
        typer.Option("--no-judge", help="Check free text with property checks only."),
    ] = False,
    budget_requests: Annotated[
        int | None,
        typer.Option(min=1, help="Stop after this many requests (cached answers are free)."),
    ] = None,
    output_format: Annotated[
        PromptFormat,
        typer.Option("--format", help="Report format: text or json (every answer and score)."),
    ] = PromptFormat.TEXT,
    output: Annotated[
        Path | None,
        typer.Option(help="Write the report to this file instead of the screen.", dir_okay=False),
    ] = None,
    patch: Annotated[
        Path | None,
        typer.Option(
            help="A patch file: the new model gets the patched prompts (ADR 0062).",
            exists=True,
            dir_okay=False,
        ),
    ] = None,
) -> None:
    """Run a suite on the old and the new model and decide each test case.

    Exits with 1 when a case REGRESSED or could not be run, so CI can fail on it.
    """
    try:
        cases_to_run = read_suite(suite_file)
        patched = None if patch is None else apply_patches(cases_to_run, read_patches(patch))
        settings = Settings(
            old=old,
            new=new,
            runs=runs,
            reference=reference,
            method=method,
            temperature=temperature,
            max_tokens=max_tokens,
            old_think=from_think,
            new_think=to_think,
        )
        settings = _pinned(settings, cases_to_run, judge, no_judge)
    except (ValueError, RunnerError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=2) from error
    if not cases_to_run.cases:
        typer.echo("Error: the suite has no test cases.", err=True)
        raise typer.Exit(code=2)
    cache = ResponseCache()
    budget = Budget(max_requests=budget_requests)
    runner = Runner(cache=cache, budget=budget)
    try:
        result = asyncio.run(run_suite_on_models(cases_to_run, runner, settings, patched))
    finally:
        cache.close()
    render = render_run_json if output_format is PromptFormat.JSON else render_run_text
    rendered = render(result)
    if output is None:
        typer.echo(rendered, nl=False)
    else:
        output.write_text(rendered, encoding="utf-8")
        typer.echo(f"Wrote {output_format.value} report to {output}.")
        typer.echo(run_summary(result))
    typer.echo(budget.summary(), err=True)
    if result.errors and budget_requests is not None:
        typer.echo(
            "Answers so far are cached: run the same command with a higher limit to continue.",
            err=True,
        )
    if result.regressed or result.errors:
        raise typer.Exit(code=1)


@app.command()
def oracles(
    path: Annotated[
        Path,
        typer.Argument(help="Folder or Python file to read.", exists=True, resolve_path=True),
    ] = Path("."),
    model: Annotated[
        str | None,
        typer.Option(help="Only list the calls to this model ID, e.g. gpt-4o-mini."),
    ] = None,
    output_format: Annotated[
        PromptFormat,
        typer.Option("--format", help="Report format: text or json."),
    ] = PromptFormat.TEXT,
    exclude: Annotated[
        list[str] | None,
        typer.Option(help="Skip paths matching this pattern, e.g. 'scripts'. Repeat for more."),
    ] = None,
    skip_tests: Annotated[
        bool,
        typer.Option(help="Leave out test files and test folders."),
    ] = False,
    output: Annotated[
        Path | None,
        typer.Option(help="Write the report to this file instead of the screen.", dir_okay=False),
    ] = None,
) -> None:
    """Show how each LLM call's answers will be checked: JSON, label or free text."""
    result = find_call_sites(path, exclude or (), skip_tests)
    if model is not None:
        kept = tuple(call for call in result.calls if call.model == model)
        result = CallSiteResult(kept, result.files_read, result.unparsed)
    render = render_oracles_json if output_format is PromptFormat.JSON else render_oracles_text
    rendered = render(result)
    if output is None:
        typer.echo(rendered, nl=False)
    else:
        output.write_text(rendered, encoding="utf-8")
        typer.echo(f"Wrote {output_format.value} report to {output}.")
        typer.echo(oracles_summary(result))


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


repair_app = typer.Typer(
    help="Patch an app's prompts so the new model does the job again.", no_args_is_help=True
)
app.add_typer(repair_app, name="repair")


def _patched(suite_file: Path, patch_file: Path) -> tuple[Suite, Suite]:
    try:
        before = read_suite(suite_file)
        return before, apply_patches(before, read_patches(patch_file))
    except ValueError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=2) from error


@repair_app.command("show")
def repair_show(
    suite_file: Annotated[
        Path,
        typer.Argument(help="The suite file from `modelbump suite`.", exists=True, dir_okay=False),
    ],
    patch_file: Annotated[
        Path,
        typer.Argument(help="The patch file to check.", exists=True, dir_okay=False),
    ],
) -> None:
    """Show what a patch changes in each test case, without asking any model.

    Exits with 2 when the patch does not fit the suite.
    """
    before, after = _patched(suite_file, patch_file)
    changed = 0
    calls: set[str] = set()
    single: set[str] = set()
    per_call = Counter(call_of(case) for case in before.cases)
    for old, new in zip(before.cases, after.cases, strict=True):
        if old.messages == new.messages:
            continue
        changed += 1
        calls.add(call_of(old))
        if per_call[call_of(old)] == 1:
            single.add(call_of(old))
        typer.echo(patch_diff(old, new))
        typer.echo("")
    typer.echo(
        f"The patch changes {changed} test {'case' if changed == 1 else 'cases'} "
        f"in {len(calls)} LLM {'call' if len(calls) == 1 else 'calls'}."
    )
    for call in sorted(single):
        typer.echo(
            f"  {call} has one test case, so an edit there could touch its inputs: check the diff."
        )


def _report_settings(
    report: dict[str, object], from_think: str | None, to_think: str | None
) -> Settings:
    """The test's settings, read back from its JSON report, to repeat its answers."""
    try:
        return Settings(
            old=str(report["old"]),
            new=str(report["new"]),
            reference=int(str(report["reference"])),
            temperature=float(str(report["temperature"])),
            max_tokens=int(str(report["max_tokens"])),
            old_think=from_think if from_think is not None else _optional(report.get("old_think")),
            new_think=to_think if to_think is not None else _optional(report.get("new_think")),
        )
    except KeyError as error:
        raise ValueError(
            f"the report has no {error} setting: use `modelbump test --format json`"
        ) from error


def _optional(value: object) -> str | None:
    return None if value is None else str(value)


@repair_app.command("propose")
def repair_propose(
    suite_file: Annotated[
        Path,
        typer.Argument(help="The suite file from `modelbump suite`.", exists=True, dir_okay=False),
    ],
    report_file: Annotated[
        Path,
        typer.Argument(
            help="A `modelbump test --format json` report of that suite, run without a patch.",
            exists=True,
            dir_okay=False,
        ),
    ],
    model: Annotated[
        str, typer.Option(help="The model that writes candidate patches, as endpoint/model.")
    ] = DEFAULT_PROPOSER,
    candidates: Annotated[
        int, typer.Option(min=1, help="Answers asked per call; each can give one candidate.")
    ] = DEFAULT_CANDIDATES,
    output_dir: Annotated[
        Path,
        typer.Option(
            help="Folder for the candidate patch files and proposals.json.", file_okay=False
        ),
    ] = Path("modelbump-proposals"),
    strategy: Annotated[
        Strategy,
        typer.Option(
            help="evidence (from the failing answers), or the baselines naive and iterative."
        ),
    ] = Strategy.EVIDENCE,
    rounds: Annotated[
        int, typer.Option(min=1, help="iterative: rounds of proposals.")
    ] = DEFAULT_ROUNDS,
    per_round: Annotated[
        int, typer.Option(min=1, help="iterative: proposals per round.")
    ] = DEFAULT_PER_ROUND,
    screen_runs: Annotated[
        int, typer.Option(min=1, help="iterative: answers per case to score each candidate.")
    ] = DEFAULT_SCREEN_RUNS,
    from_think: Annotated[
        str | None,
        typer.Option(help="iterative: reasoning effort for the old model, if the report has none."),
    ] = None,
    to_think: Annotated[
        str | None,
        typer.Option(help="iterative: reasoning effort for the new model, e.g. none for Qwen 3."),
    ] = None,
) -> None:
    """Ask a model for candidate patches for every call with a REGRESSED case (ADR 0063).

    Each candidate is a patch file you can check with `repair show` and test with
    `modelbump test --patch`. Nothing here says a candidate works. The naive and
    iterative strategies are the baselines of ADR 0065; iterative also asks the
    old and new models from the report, to score its candidates.
    """
    settings = None
    try:
        suite_data = read_suite(suite_file)
        report = json.loads(report_file.read_text(encoding="utf-8"))
        endpoint, _ = resolve_model(model)
        version = pin_versions([ChatRequest.ask(model, "version")])[0].model_version
        if strategy is Strategy.ITERATIVE:
            settings = _pinned(
                _report_settings(report, from_think, to_think),
                suite_data,
                str(report.get("judge") or DEFAULT_JUDGE),
                no_judge=not report.get("judge"),
            )
    except (ValueError, RunnerError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=2) from error
    if not endpoint.local:
        typer.echo(
            "Note: a free cloud tier is in use. The app's prompts leave this machine "
            "and may be kept or read by the provider. Never send private code.",
            err=True,
        )
    cache = ResponseCache()
    budget = Budget()
    runner = Runner(cache=cache, budget=budget)
    try:
        if settings is not None:
            results = asyncio.run(
                optimize(
                    suite_data,
                    report,
                    runner,
                    settings,
                    model=model,
                    rounds=rounds,
                    per_round=per_round,
                    screen_runs=screen_runs,
                    model_version=version,
                )
            )
        else:
            results = asyncio.run(
                propose(
                    suite_data,
                    report,
                    runner,
                    model=model,
                    count=candidates,
                    model_version=version,
                    strategy=strategy,
                )
            )
    except ValueError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=2) from error
    finally:
        cache.close()
    if not results:
        typer.echo("No case REGRESSED in the report: nothing to repair.")
        return
    write_proposals(results, output_dir, model, version, strategy)
    total = 0
    for result in results:
        found = len(result.candidates)
        total += found
        only = "" if result.evidence.edits_allowed else " (one test case: add_system only)"
        typer.echo(
            f"{result.evidence.call}: {found} {'candidate' if found == 1 else 'candidates'}, "
            f"{len(result.refused)} refused{only}"
        )
        for sample, reason in result.refused:
            typer.echo(f"  sample {sample} refused: {reason}")
    typer.echo(
        f"Wrote {total} candidate {'patch' if total == 1 else 'patches'} for "
        f"{len(results)} {'call' if len(results) == 1 else 'calls'} to {output_dir}."
    )
    typer.echo(budget.summary(), err=True)


@repair_app.command("run")
def repair_run(
    suite_file: Annotated[
        Path,
        typer.Argument(help="The suite file from `modelbump suite`.", exists=True, dir_okay=False),
    ],
    proposals: Annotated[
        Path,
        typer.Argument(
            help="The folder `modelbump repair propose` wrote.", exists=True, file_okay=False
        ),
    ],
    old: Annotated[
        str, typer.Option("--from", help="The model the app uses now, as endpoint/model.")
    ],
    new: Annotated[str, typer.Option("--to", help="The model to move to, as endpoint/model.")],
    screen_runs: Annotated[
        int, typer.Option(min=1, help="Answers per case for each candidate when screening.")
    ] = DEFAULT_SCREEN_RUNS,
    confirm_runs: Annotated[
        int, typer.Option(min=1, help="Fresh answers per model per case when confirming.")
    ] = DEFAULT_CONFIRM_RUNS,
    confirm_top: Annotated[
        int,
        typer.Option(
            min=1, help="Best candidates to confirm per call (alpha is split among them)."
        ),
    ] = DEFAULT_CONFIRM_TOP,
    alpha: Annotated[
        float, typer.Option(help="Chance per call of accepting a patch that breaks a case.")
    ] = DEFAULT_ALPHA,
    margin: Annotated[
        float, typer.Option(help="How much worse than the old model still counts as fine.")
    ] = DEFAULT_MARGIN,
    max_gap: Annotated[
        float,
        typer.Option(help="Do not confirm a candidate that screens this far below the old model."),
    ] = DEFAULT_MAX_GAP,
    reference: Annotated[
        int,
        typer.Option(min=1, help="Old-model answers per case that set the reference (not scored)."),
    ] = DEFAULT_REFERENCE,
    from_think: Annotated[
        str | None,
        typer.Option(help="Reasoning effort for the --from model: none, low, medium or high."),
    ] = None,
    to_think: Annotated[
        str | None,
        typer.Option(help="Reasoning effort for the --to model, e.g. none for Qwen 3."),
    ] = None,
    temperature: Annotated[
        float, typer.Option(min=0.0, help="Sampling temperature for both models.")
    ] = DEFAULT_TEMPERATURE,
    max_tokens: Annotated[
        int, typer.Option(min=1, help="Longest answer, in tokens.")
    ] = DEFAULT_MAX_TOKENS,
    judge: Annotated[
        str,
        typer.Option(help="The model that judges free-text answers, as endpoint/model."),
    ] = DEFAULT_JUDGE,
    no_judge: Annotated[
        bool,
        typer.Option("--no-judge", help="Check free text with property checks only."),
    ] = False,
    budget_requests: Annotated[
        int | None,
        typer.Option(min=1, help="Stop after this many requests (cached answers are free)."),
    ] = None,
    output: Annotated[
        Path,
        typer.Option(help="Patch file for the accepted patches.", dir_okay=False),
    ] = Path("modelbump-repair.json"),
    report: Annotated[
        Path | None,
        typer.Option(help="Also write the full JSON report to this file.", dir_okay=False),
    ] = None,
) -> None:
    """Screen the candidate patches, confirm the best on fresh answers, keep only safe ones.

    A patch is accepted only if, on every test case of its call, the patched new
    model is shown to be no more than --margin worse than the old model (ADR 0064).
    Exits with 1 when a call could not be repaired.
    """
    try:
        cases_to_run = read_suite(suite_file)
        calls = read_candidates(proposals, cases_to_run)
        loop = LoopSettings(screen_runs, confirm_runs, confirm_top, alpha, margin, max_gap)
        settings = Settings(
            old=old,
            new=new,
            reference=reference,
            temperature=temperature,
            max_tokens=max_tokens,
            old_think=from_think,
            new_think=to_think,
        )
        settings = _pinned(settings, cases_to_run, judge, no_judge)
    except (ValueError, RunnerError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=2) from error
    if not calls:
        typer.echo("No calls to repair in the proposals.")
        return
    cache = ResponseCache()
    budget = Budget(max_requests=budget_requests)
    runner = Runner(cache=cache, budget=budget)
    try:
        results = asyncio.run(repair_suite(cases_to_run, calls, runner, settings, loop))
    finally:
        cache.close()
    typer.echo(render_repair_text(results, settings, loop), nl=False)
    accepted = tuple(r.patch for r in results if r.patch is not None)
    if accepted:
        output.write_text(patches_to_json(accepted), encoding="utf-8")
        typer.echo(f"Wrote the accepted patches to {output}.")
    if report is not None:
        report.write_text(render_repair_json(results, settings, loop), encoding="utf-8")
        typer.echo(f"Wrote json report to {report}.")
    typer.echo(budget.summary(), err=True)
    if len(accepted) < len(results):
        raise typer.Exit(code=1)


judge_app = typer.Typer(
    help="Check the free-text judge against your own labels.", no_args_is_help=True
)
app.add_typer(judge_app, name="judge")


@judge_app.command("sheet")
def judge_sheet(
    report: Annotated[
        Path,
        typer.Argument(
            help="A `modelbump test --format json` report.", exists=True, dir_okay=False
        ),
    ],
    output: Annotated[
        Path, typer.Option(help="The blind sheet to label (CSV).", dir_okay=False)
    ] = Path("judge-sheet.csv"),
    key: Annotated[
        Path,
        typer.Option(help="What the sheet hides: models and judge verdicts.", dir_okay=False),
    ] = Path("judge-key.json"),
    size: Annotated[
        int, typer.Option(min=2, help="Answers to draw, half judged PASS, half FAIL.")
    ] = DEFAULT_SHEET_SIZE,
    seed: Annotated[int, typer.Option(help="Seed for drawing and shuffling.")] = DEFAULT_SHEET_SEED,
    exclude_key: Annotated[
        list[Path] | None,
        typer.Option(
            help="Leave out the answers of an earlier sheet's key. Repeat for more.",
            exists=True,
            dir_okay=False,
        ),
    ] = None,
) -> None:
    """Write a blind sheet of judged answers for you to label PASS or FAIL."""
    try:
        made = make_sheet(report, output, key, size, seed, exclude_key or ())
    except (ValueError, KeyError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=2) from error
    typer.echo(
        f"Wrote {made.rows} rows ({made.answers} answers: {made.drawn['PASS']} judged PASS, "
        f"{made.drawn['FAIL']} FAIL) to {output}, and the key to {key}."
    )
    if made.excluded:
        typer.echo(f"Left out {made.excluded} answers that earlier sheets hold.")
    typer.echo(
        f"The report had {made.available['PASS']} PASS and {made.available['FAIL']} FAIL. "
        "Fill in your_label with PASS or FAIL, without looking at the key."
    )


@judge_app.command("agreement")
def judge_agreement(
    sheet: Annotated[
        Path, typer.Argument(help="The labelled sheet (CSV).", exists=True, dir_okay=False)
    ],
    key: Annotated[
        Path,
        typer.Argument(help="The key from `modelbump judge sheet`.", exists=True, dir_okay=False),
    ],
    report: Annotated[
        Path | None,
        typer.Option(
            help="Compare with this report's verdicts instead (the same run, judged again).",
            exists=True,
            dir_okay=False,
        ),
    ] = None,
) -> None:
    """How often the judge agrees with your labels, and pass rates corrected for it."""
    try:
        result = agreement(sheet, key, report)
    except (ValueError, KeyError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=2) from error
    for line in agreement_lines(result):
        typer.echo(line)


@judge_app.command("probes")
def judge_probes(
    report: Annotated[
        Path,
        typer.Argument(
            help="A `modelbump test --format json` report.", exists=True, dir_okay=False
        ),
    ],
    output: Annotated[
        Path, typer.Option(help="The blind probe sheet to label (CSV).", dir_okay=False)
    ] = Path("probe-sheet.csv"),
    key: Annotated[
        Path,
        typer.Option(help="What the sheet hides: each probe's kind and verdict.", dir_okay=False),
    ] = Path("probe-key.json"),
    breaker: Annotated[
        str, typer.Option(help="The model that writes the probes, as endpoint/model.")
    ] = DEFAULT_BREAKER,
    judge: Annotated[
        str, typer.Option(help="The judge to test, as endpoint/model.")
    ] = DEFAULT_JUDGE,
    per_kind: Annotated[
        int, typer.Option(min=1, help="Probes of each kind per free-text case.")
    ] = DEFAULT_PER_KIND,
    seed: Annotated[int, typer.Option(help="Seed for shuffling the sheet.")] = DEFAULT_PROBE_SEED,
    budget_requests: Annotated[
        int | None,
        typer.Option(min=1, help="Stop after this many requests (cached answers are free)."),
    ] = None,
) -> None:
    """Break reference answers on purpose, judge them, and write a blind sheet to check."""
    try:
        data = json.loads(report.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1 or "cases" not in data:
            raise ValueError(f"{report} is not a `modelbump test --format json` report")
        if any("reference_answer" not in case for case in data["cases"]):
            raise ValueError(f"{report} is from an older ModelBump; run `modelbump test` again")
        endpoints = [resolve_model(name)[0] for name in (breaker, judge)]
        pinned = pin_versions([ChatRequest.ask(name, "version") for name in (breaker, judge)])
    except (ValueError, RunnerError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=2) from error
    if not all(endpoint.local for endpoint in endpoints):
        typer.echo(
            "Note: a free cloud tier is in use. The app's prompts leave this machine "
            "and may be kept or read by the provider. Never send private code.",
            err=True,
        )
    cache = ResponseCache()
    budget = Budget(max_requests=budget_requests)
    runner = Runner(cache=cache, budget=budget)
    try:
        run = asyncio.run(
            make_probes(
                data,
                runner,
                breaker=breaker,
                judge=judge,
                judge_version=pinned[1].model_version,
                per_kind=per_kind,
            )
        )
    except RunnerError as error:
        typer.echo(f"Error: {error}", err=True)
        typer.echo("Answers so far are cached: run the same command again to continue.", err=True)
        raise typer.Exit(code=1) from error
    finally:
        cache.close()
    if not run.probes:
        typer.echo("Error: the report has no free-text cases with a reference answer.", err=True)
        raise typer.Exit(code=2)
    write_probes(
        run,
        data,
        report,
        output,
        key,
        breaker=breaker,
        judge=judge,
        judge_version=pinned[1].model_version,
        per_kind=per_kind,
        seed=seed,
    )
    verdicts = Counter(probe.judge for probe in run.probes)
    typer.echo(
        f"Wrote {len(run.probes)} probes for {run.cases} free-text cases to {output}, "
        f"and the key to {key}."
    )
    if run.missing:
        typer.echo(f"The breaker could not write: {dict(run.missing)}.")
    typer.echo(
        f"The judge said PASS {verdicts['PASS']}, FAIL {verdicts['FAIL']}"
        + (f", unclear {verdicts['unclear']}." if verdicts["unclear"] else ".")
    )
    typer.echo("Fill in your_label with PASS or FAIL, without looking at the key.")
    typer.echo(budget.summary(), err=True)


@judge_app.command("probe-check")
def judge_probe_check(
    sheet: Annotated[
        Path, typer.Argument(help="The labelled probe sheet (CSV).", exists=True, dir_okay=False)
    ],
    key: Annotated[
        Path,
        typer.Argument(help="The key from `modelbump judge probes`.", exists=True, dir_okay=False),
    ],
) -> None:
    """Which kinds of broken answer the judge catches, checked against your labels."""
    try:
        result = check_probes(sheet, key)
    except (ValueError, KeyError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=2) from error
    for line in probe_lines(result):
        typer.echo(line)


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
    scores: Annotated[
        bool,
        typer.Option(
            "--scores",
            help="Answers get a score between 0 and 1 with these means, not pass/fail.",
        ),
    ] = False,
) -> None:
    """Pretend two models answer one test case, and stop as soon as the verdict is clear."""
    _check_rate(old_rate, "OLD_RATE")
    _check_rate(new_rate, "NEW_RATE")
    rng = random.Random(seed)

    def next_round() -> tuple[float, float]:
        return draw_score(rng, old_rate, scores), draw_score(rng, new_rate, scores)

    try:
        result = run_sequential(next_round, alpha=alpha, margin=margin, max_runs=max_runs)
    except ValueError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=2) from error
    if scores:
        typer.echo(
            f"Simulated test case: old model scores {old_rate:.2f} on average, "
            f"new model {new_rate:.2f} (seed {seed})"
        )
        seen = (
            f"old mean {result.old_passes / result.runs:.2f}, "
            f"new mean {result.new_passes / result.runs:.2f}"
        )
    else:
        typer.echo(
            f"Simulated test case: old model passes {old_rate:.0%}, new model {new_rate:.0%} "
            f"(seed {seed})"
        )
        seen = f"old {result.old_passes:g}/{result.runs}, new {result.new_passes:g}/{result.runs}"
    how = "Stopped early" if result.stopped_early else "Reached --max-runs"
    typer.echo(f"{how} after {result.runs} answers per model ({seen})")
    typer.echo(f"Verdict: {result.verdict} ({_VERDICT_MEANING[result.verdict]})")
    evidence = result.evidence
    typer.echo(
        f"Evidence (a claim is proven at {1 / alpha:g}): regressed {evidence.regressed:.1f}, "
        f"improved {evidence.improved:.1f}, equivalent {evidence.equivalent:.1f}"
    )


@stats_app.command("simulate-suite")
def stats_simulate_suite(
    size: Annotated[int, typer.Option("--items", help="Test cases in the suite.")] = 300,
    regressed: Annotated[
        int, typer.Option(help="How many test cases the new model is really worse on.")
    ] = 30,
    drop: Annotated[
        float, typer.Option(help="How much pass rate those test cases lose (0.3 = 30 points).")
    ] = 0.3,
    seed: Annotated[int, typer.Option(help="Random seed, so a run can be repeated.")] = 1,
    q: Annotated[
        float,
        typer.Option("--fdr", help="Largest expected share of false alarms among REGRESSED."),
    ] = DEFAULT_FDR,
    max_runs: Annotated[
        int, typer.Option(help="Stop a test case with INCONCLUSIVE after this many answers.")
    ] = DEFAULT_MAX_RUNS,
    margin: Annotated[
        float,
        typer.Option(
            help="Largest change in pass rate that still counts as the same (0.1 = 10 points)."
        ),
    ] = DEFAULT_MARGIN,
    futility: Annotated[
        float | None,
        typer.Option(
            help="Stop a test case that looks fine once its REGRESSED evidence falls below "
            "this (e.g. 0.1), after 20 answers."
        ),
    ] = None,
) -> None:
    """Pretend two models answer a whole suite, and control false alarms across it."""
    try:
        suite = simulated_suite(size, regressed, drop, seed)
        result = run_suite(suite.items, q=q, margin=margin, max_runs=max_runs, futility=futility)
        uncorrected = [
            name
            for name, next_round in simulated_suite(size, regressed, drop, seed).items.items()
            if run_sequential(next_round, alpha=q, margin=margin, max_runs=max_runs).verdict
            is Verdict.REGRESSED
            and not suite.really_worse(name)
        ]
    except ValueError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=2) from error
    typer.echo(
        f"Simulated suite: {size} test cases, {regressed} made worse by "
        f"{drop * 100:.0f} points (seed {seed})"
    )
    found = result.named(Verdict.REGRESSED)
    false_alarms = [name for name in found if not suite.really_worse(name)]
    counts = result.counts
    typer.echo(
        f"REGRESSED: {len(found)} ({len(found) - len(false_alarms)} really worse, "
        f"{len(false_alarms)} false alarms)"
    )
    for verdict in (Verdict.IMPROVED, Verdict.EQUIVALENT, Verdict.INCONCLUSIVE):
        typer.echo(f"{verdict}: {counts[verdict]}")
    typer.echo(
        f"Answers per model: {result.total_runs:,} ({result.total_runs / size:.0f} per test case)"
    )
    if futility is not None:
        fine = sum(item.looks_fine for item in result.items)
        typer.echo(f"Stopped early because they looked fine: {fine}")
    typer.echo(f"Without suite control: {len(uncorrected)} false alarms")
