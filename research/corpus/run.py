"""Run ModelBump end to end on every corpus app (ADR 0059).

For each app in ``research/data/corpus/apps.jsonl`` (research.corpus.build):

1. find its LLM calls and pick up to ``--calls`` of them at random (seeded):
   calls that do not pass tools and whose messages can all be read;
2. give each picked call one complete test case: its own fixed prompt, an input
   from the app's code, or one written by the generator model;
3. write the suite file and run ``modelbump test``'s engine on it: Qwen 2.5 7B
   to Qwen 3 8B (thinking off), fixed k + BH, free text judged by Gemma 3 12B;
4. write the full JSON report.

All reports are merged into ``report-all.json`` (case ids get an ``app-NN/``
prefix), which ``modelbump judge sheet`` reads to draw the paper's hand labels
across every app. Every model answer is cached, so a stopped run continues
where it stopped.

Run from the repo root (Ollama running, the three models pulled):
    uv run python -m research.corpus.run --apps 1     # a quick trial
    uv run python -m research.corpus.run              # every app (hours)

``--new`` and ``--new-think`` change the new model (Phase 6 adds Qwen 3 4B Instruct,
ADRs 0066 and 0067). The old model, the picked calls and the generated inputs stay the
same, so only the new model's answers and their judging are new.

``--out`` writes a run to another folder, so a later run (a new judge, say)
keeps the earlier one. ``--drop-case`` leaves out a case by its merged id
(``app-14/src/agenthatch/skill/reflection.py:202#1``), for prompts found broken
by hand; dropped cases are counted.
"""

import argparse
import asyncio
import json
import random
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from modelbump.oracles import OutputKind, choose_oracle
from modelbump.oracles.judge import DEFAULT_JUDGE
from modelbump.runner import Budget, ChatRequest, ResponseCache, Runner, RunnerError, pin_versions
from modelbump.stats import Verdict
from modelbump.suite import (
    Method,
    Settings,
    Suite,
    SuiteRun,
    build_suite,
    run_suite_on_models,
    suite_to_json,
)
from modelbump.suite.report import render_run_json
from modelbump.synth.cases import CaseResult, SiteCases, find_cases
from modelbump.synth.generate import DEFAULT_GENERATOR, add_generated
from research.filtering.filter import read_jsonl, write_jsonl

OLD = "ollama/qwen2.5:7b"
NEW = "ollama/qwen3:8b"
NEW_THINK = "none"
CALLS_PER_APP = 3
RUNS = 10
SEED = 2033


def can_test(entry: SiteCases) -> bool:
    """A call that can get a complete case: no tools, every message read, some written text."""
    site = entry.site
    return (
        choose_oracle(site).kind is not OutputKind.TOOLS
        and bool(site.parts)
        and all(part.template is not None for part in site.parts)
        and any(part.has_text for part in site.parts)
    )


def pick_calls(result: CaseResult, count: int, rng: random.Random) -> CaseResult:
    """Up to ``count`` testable calls, drawn at random, in file order."""
    candidates = [entry for entry in result.sites if can_test(entry)]
    chosen = candidates if len(candidates) <= count else rng.sample(candidates, count)
    chosen.sort(key=lambda entry: (entry.site.path, entry.site.line))
    return CaseResult(tuple(chosen), result.files_read, result.unparsed)


def one_case_per_call(suite: Suite) -> Suite:
    """The first case of each call: every call weighs the same in the corpus."""
    seen: set[tuple[str, int]] = set()
    kept = []
    for case in suite.cases:
        if (case.path, case.line) not in seen:
            seen.add((case.path, case.line))
            kept.append(case)
    return Suite(tuple(kept), suite.left_out)


def merge_reports(reports: Sequence[tuple[str, Mapping[str, Any]]]) -> dict[str, Any]:
    """One report with every app's cases, ids prefixed with the app, for `judge sheet`."""
    if not reports:
        raise ValueError("no reports to merge")
    judged = [report for _, report in reports if report.get("judge")]
    first = dict(judged[0] if judged else reports[0][1])
    counts: Counter[str] = Counter()
    cases: list[dict[str, Any]] = []
    for app, report in reports:
        counts.update(report["counts"])
        cases.extend({**case, "id": f"{app}/{case['id']}"} for case in report["cases"])
    return {**first, "counts": dict(counts), "apps": [app for app, _ in reports], "cases": cases}


def _app_name(number: int) -> str:
    return f"app-{number:02d}"


async def run_app(
    app: Mapping[str, Any],
    runner: Runner,
    settings: Settings,
    *,
    calls: int,
    seed: int,
    generator: str,
    generator_version: str,
    name: str = "",
    drop: frozenset[str] = frozenset(),
) -> tuple[Suite, SuiteRun | None, dict[str, Any]]:
    """Build one app's suite and run it. The run is None when no case could be made.

    Cases whose merged id (``name/case-id``) is in ``drop`` are left out.
    """
    result = find_cases(Path(str(app["folder"])), skip_tests=True)
    picked = pick_calls(result, calls, random.Random(f"{seed}-{app['repo']}"))
    generated = await add_generated(picked, runner, 1, generator, generator_version)
    built = one_case_per_call(build_suite(generated.result))
    kept = tuple(case for case in built.cases if f"{name}/{case.id}" not in drop)
    suite = Suite(kept, built.left_out)
    row: dict[str, Any] = {
        "app": app["app"],
        "repo": app["repo"],
        "testable_calls": sum(can_test(entry) for entry in result.sites),
        "picked_calls": len(picked.sites),
        "generated_for": generated.asked,
        "generated": generated.added,
        "cases": len(suite.cases),
        "dropped": len(built.cases) - len(kept),
        "cases_by_oracle": dict(Counter(case.oracle.kind.value for case in suite.cases)),
        "generated_cases": sum(case.generated_by is not None for case in suite.cases),
    }
    if not suite.cases:
        return suite, None, {**row, "verdicts": {}, "not_run": 0}
    has_text = any(case.oracle.kind is OutputKind.TEXT for case in suite.cases)
    run_settings = settings if has_text else replace(settings, judge=None, judge_version="")
    run = await run_suite_on_models(suite, runner, run_settings)
    verdicts = {v.value: n for v, n in run.counts.items()}
    return suite, run, {**row, "verdicts": verdicts, "not_run": run.errors}


async def run_corpus(
    apps: Sequence[Mapping[str, Any]],
    runner: Runner,
    settings: Settings,
    out_dir: Path,
    *,
    calls: int = CALLS_PER_APP,
    seed: int = SEED,
    generator: str = DEFAULT_GENERATOR,
    generator_version: str = "",
    progress: Callable[[str], None] = lambda line: None,
    drop: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Run every app, write each suite and report, the merged report and the totals."""
    runs_dir = out_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    reports: list[tuple[str, dict[str, Any]]] = []
    for app in apps:
        name = _app_name(int(app["app"]))
        suite, run, row = await run_app(
            app,
            runner,
            settings,
            calls=calls,
            seed=seed,
            generator=generator,
            generator_version=generator_version,
            name=name,
            drop=drop,
        )
        (runs_dir / f"{name}.suite.json").write_text(suite_to_json(suite), encoding="utf-8")
        if run is not None:
            report = render_run_json(run)
            (runs_dir / f"{name}.report.json").write_text(report, encoding="utf-8")
            reports.append((name, json.loads(report)))
        rows.append(row)
        progress(
            f"{name} {app['repo']}: {row['cases']} cases, verdicts {row['verdicts'] or 'none'}"
            + (f", {row['not_run']} not run" if row["not_run"] else "")
        )
    write_jsonl(rows, out_dir / "runs.jsonl")
    if reports:
        merged = merge_reports(reports)
        (out_dir / "report-all.json").write_text(
            json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    stats = run_stats(rows, settings, calls, seed)
    (out_dir / "run.stats.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    return stats


def run_stats(
    rows: Sequence[Mapping[str, Any]], settings: Settings, calls: int, seed: int
) -> dict[str, Any]:
    """The numbers for the paper."""
    verdicts: Counter[str] = Counter()
    oracles: Counter[str] = Counter()
    for row in rows:
        verdicts.update(row["verdicts"])
        oracles.update(row["cases_by_oracle"])
    return {
        "old": settings.old,
        "new": settings.new,
        "judge": settings.judge,
        "runs": settings.runs,
        "method": settings.chosen.value,
        "calls_per_app": calls,
        "seed": seed,
        "apps": len(rows),
        "apps_with_cases": sum(1 for row in rows if row["cases"]),
        "testable_calls": sum(int(row["testable_calls"]) for row in rows),
        "picked_calls": sum(int(row["picked_calls"]) for row in rows),
        "cases": sum(int(row["cases"]) for row in rows),
        "dropped": sum(int(row.get("dropped", 0)) for row in rows),
        "generated_cases": sum(int(row["generated_cases"]) for row in rows),
        "cases_by_oracle": dict(oracles.most_common()),
        "verdicts": {v.value: verdicts[v.value] for v in Verdict},
        "not_run": sum(int(row["not_run"]) for row in rows),
        "apps_with_a_regression": sum(1 for row in rows if row["verdicts"].get("REGRESSED")),
    }


def summary(stats: Mapping[str, Any]) -> str:
    """What to print at the end of a run."""
    return "\n".join(
        [
            f"Ran {stats['apps']} apps ({stats['apps_with_cases']} with test cases): "
            f"{stats['old']} -> {stats['new']}, {stats['method']} k={stats['runs']}, "
            f"judge {stats['judge']}",
            f"Calls: {stats['testable_calls']} testable, {stats['picked_calls']} picked; "
            f"{stats['cases']} cases ({stats['generated_cases']} with generated inputs)"
            + (f", {stats['dropped']} dropped by hand" if stats["dropped"] else ""),
            f"Cases by oracle: {stats['cases_by_oracle']}",
            f"Verdicts: {stats['verdicts']}"
            + (f"; {stats['not_run']} not run" if stats["not_run"] else ""),
            f"Apps with at least one REGRESSED case: {stats['apps_with_a_regression']}",
        ]
    )


def main(argv: Sequence[str] | None = None, runner: Runner | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--corpus", type=Path, default=Path("research/data/corpus"))
    parser.add_argument(
        "--out", type=Path, default=None, help="Write the run here (default: the corpus folder)."
    )
    parser.add_argument(
        "--drop-case", action="append", default=[], help="Leave out this case id. Repeatable."
    )
    parser.add_argument("--apps", type=int, default=None, help="Only the first N apps.")
    parser.add_argument(
        "--calls", type=int, default=CALLS_PER_APP, help=f"Calls per app ({CALLS_PER_APP})."
    )
    parser.add_argument("--runs", type=int, default=RUNS, help=f"Answers per model ({RUNS}).")
    parser.add_argument("--seed", type=int, default=SEED, help=f"Seed for picking calls ({SEED}).")
    parser.add_argument("--new", default=NEW, help=f"The new model ({NEW}).")
    parser.add_argument(
        "--new-think", default=NEW_THINK, help=f"Reasoning effort for the new model ({NEW_THINK})."
    )
    args = parser.parse_args(argv)
    apps_file = args.corpus / "apps.jsonl"
    if not apps_file.exists():
        print(f"{apps_file} not found. Run research.corpus.build first.", file=sys.stderr)
        return 1
    apps = list(read_jsonl(apps_file))[: args.apps]
    settings = Settings(
        old=OLD,
        new=args.new,
        runs=args.runs,
        method=Method.FIXED,
        new_think=args.new_think,
        judge=DEFAULT_JUDGE,
    )
    cache: ResponseCache | None = None
    budget = Budget()
    generator_version = ""
    if runner is None:
        names = [OLD, args.new, DEFAULT_JUDGE, DEFAULT_GENERATOR]
        try:
            pinned = pin_versions([ChatRequest.ask(name, "version") for name in names])
        except RunnerError as error:
            print(f"Error: {error}", file=sys.stderr)
            return 2
        settings = replace(
            settings,
            old_version=pinned[0].model_version,
            new_version=pinned[1].model_version,
            judge_version=pinned[2].model_version,
        )
        generator_version = pinned[3].model_version
        cache = ResponseCache()
        runner = Runner(cache=cache, budget=budget)
    try:
        stats = asyncio.run(
            run_corpus(
                apps,
                runner,
                settings,
                args.out or args.corpus,
                calls=args.calls,
                seed=args.seed,
                generator_version=generator_version,
                progress=lambda line: print(line, file=sys.stderr),
                drop=frozenset(args.drop_case),
            )
        )
    finally:
        if cache is not None:
            cache.close()
    print(summary(stats))
    print(budget.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
