"""RQ3: how often does each repair strategy fix a real regression, safely? (ADR 0066)

Input: corpus runs (research.corpus.run), one folder per migration, each with
``runs/app-NN.suite.json`` and ``runs/app-NN.report.json``. For every call
with a REGRESSED case:

1. **Widen** the call to ``1 + --extra`` test cases: its corpus case plus new
   inputs from the generator model (seeded, cached). Calls with no slots keep
   their one case. More cases make the loop's guarantee cover more inputs,
   and let candidates edit the prompt text (ADR 0062).
2. **Test** the widened call on both models (fixed k = ``--runs``, as the
   corpus run). Calls with no REGRESSED case left are counted and skipped.
3. For each **strategy** (evidence, naive, iterative; ADRs 0063 and 0065),
   write candidates with the same proposer, then run the same repair loop
   (ADR 0064, with the screen gap of ADR 0066).

Every request is counted per strategy and per role (proposer, old, new,
judge), cached or not, because cached answers were paid for once.

Writes to ``--out`` (default research/data/repair_eval/):
``results.jsonl`` (one row per call and strategy), ``summary.json``, and
for each call and strategy the candidates and the loop's JSON report.

Run from the repo root, Ollama running with the models pulled:
    uv run python -m research.repair_eval.run --calls 1        # a quick trial
    uv run python -m research.repair_eval.run                  # every regression (hours)
"""

import argparse
import asyncio
import json
import sys
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from math import sqrt
from pathlib import Path
from statistics import NormalDist
from typing import Any

from modelbump.oracles.judge import DEFAULT_JUDGE
from modelbump.repair.loop import CallCandidates, CallRepair, LoopSettings, repair_call
from modelbump.repair.optimize import optimize_call
from modelbump.repair.patch import call_of
from modelbump.repair.propose import (
    DEFAULT_CANDIDATES,
    DEFAULT_PROPOSER,
    Proposals,
    Strategy,
    propose,
    slug,
    write_proposals,
)
from modelbump.repair.propose import regressed_calls as evidence_of
from modelbump.repair.report import render_repair_json
from modelbump.runner import (
    Budget,
    ChatRequest,
    ChatResult,
    ResponseCache,
    Runner,
    RunnerError,
    pin_versions,
)
from modelbump.suite import Method, Settings, Suite, SuiteCase, read_suite, run_suite_on_models
from modelbump.suite.file import build_suite
from modelbump.suite.report import render_run_json
from modelbump.synth.cases import CaseResult, SiteCases, TestCase, find_cases
from modelbump.synth.generate import DEFAULT_GENERATOR, fill, generation_request, parse_values
from research.filtering.filter import read_jsonl, write_jsonl

RUNS = [Path("research/data/corpus/run-v3"), Path("research/data/corpus/run-qwen3-4b-instruct")]
"""The second migration uses Qwen 3 4B Instruct: the ``qwen3:4b`` tag only thinks (ADR 0067)."""
EXTRA_CASES = 2
WIDEN_SAMPLE = 100
"""Sample number of the generation request that widens a call: not one the corpus used."""
NEW_THINK = "none"
STRATEGIES = (Strategy.EVIDENCE, Strategy.NAIVE, Strategy.ITERATIVE)


@dataclass(slots=True)
class Tally:
    """Requests and output tokens by role, cached or not."""

    requests: Counter[str] = field(default_factory=Counter)
    fresh: Counter[str] = field(default_factory=Counter)
    tokens: Counter[str] = field(default_factory=Counter)


def counted(runner: Runner, tally: Tally, roles: Mapping[str, str]) -> Callable[[], None]:
    """Count every request ``runner`` sends, by the role of its model. Returns an undo."""
    original = runner.run_each

    async def run_each(requests: Sequence[ChatRequest]) -> list[ChatResult | RunnerError]:
        outcomes = await original(requests)
        for request, outcome in zip(requests, outcomes, strict=True):
            role = roles.get(request.model, "other")
            tally.requests[role] += 1
            if isinstance(outcome, ChatResult):
                tally.tokens[role] += outcome.output_tokens
                if not outcome.cached:
                    tally.fresh[role] += 1
        return outcomes

    setattr(runner, "run_each", run_each)  # noqa: B010 - research code: count without a subclass
    return lambda: setattr(runner, "run_each", original)


def regressed_calls(report: Mapping[str, Any], suite: Suite) -> list[SuiteCase]:
    """The first REGRESSED case of each call, in report order."""
    by_id = {case.id: case for case in suite.cases}
    found: dict[str, SuiteCase] = {}
    for item in report.get("cases", []):
        if item.get("verdict") == "REGRESSED" and item["id"] in by_id:
            case = by_id[item["id"]]
            found.setdefault(call_of(case), case)
    return list(found.values())


async def widen(
    case: SuiteCase,
    folder: Path,
    runner: Runner,
    extra: int,
    generator: str,
    generator_version: str = "",
) -> Suite:
    """The call's corpus case plus up to ``extra`` cases with generated inputs."""
    if extra < 1:
        return Suite((case,))
    entry = next(
        (
            e
            for e in find_cases(folder, skip_tests=True).sites
            if (e.site.path, e.site.line) == (case.path, case.line)
        ),
        None,
    )
    if entry is None or not entry.site.slots:
        return Suite((case,))
    request = replace(
        generation_request(entry.site, extra, generator, WIDEN_SAMPLE),
        model_version=generator_version,
    )
    (outcome,) = await runner.run_each([request])
    if isinstance(outcome, RunnerError):
        return Suite((case,))
    tests = [
        TestCase(
            fill(entry.site, values),
            f"generated by {generator}, sample {WIDEN_SAMPLE}",
            tuple((slot, values[slot]) for slot in entry.site.slots),
            generated_by=generator,
        )
        for values in parse_values(outcome.text, entry.site.slots)[:extra]
    ]
    built = build_suite(CaseResult((SiteCases(entry.site, tuple(tests)),), 1))
    new_cases = [
        replace(other, id=f"{call_of(case)}#{number}")
        for number, other in enumerate(
            (c for c in built.cases if c.messages != case.messages), start=2
        )
    ]
    return Suite((case, *new_cases))


@dataclass(frozen=True, slots=True)
class Row:
    """One call and one strategy."""

    migration: str
    app: str
    call: str
    kind: str
    cases: int
    regressed_cases: int
    strategy: str
    candidates: int
    best_screen: float | None
    old_mean: float | None
    unpatched_mean: float | None
    status: str
    blocked_for_collateral: bool
    """Rejected although every REGRESSED case passed: another case of the call broke."""
    requests: dict[str, int]
    fresh: dict[str, int]
    tokens: dict[str, int]


def _status(result: CallRepair) -> str:
    if result.patch is not None:
        return "REPAIRED"
    if not result.screened:
        return "NO CANDIDATES"
    if result.confirmations:
        return "REJECTED"
    if result.skipped:
        return "SKIPPED"
    return "NOT RUN"


def blocked_for_collateral(result: CallRepair) -> bool:
    regressed = set(result.regressed)
    for confirmation in result.confirmations:
        if confirmation.accepted or not confirmation.checks:
            continue
        fixed = all(c.ok for c in confirmation.checks if c.case_id in regressed)
        broke = any(not c.ok for c in confirmation.checks if c.case_id not in regressed)
        if fixed and broke:
            return True
    return False


async def repair_one(
    migration: str,
    app: str,
    suite: Suite,
    report: Mapping[str, Any],
    runner: Runner,
    settings: Settings,
    loop: LoopSettings,
    strategy: Strategy,
    *,
    proposer: str,
    proposer_version: str,
    candidates: int,
    out: Path,
) -> Row:
    """Write candidates with one strategy and run the loop on them."""
    tally = Tally()
    roles = {
        proposer: "proposer",
        settings.old: "old",
        settings.new: "new",
        **({settings.judge: "judge"} if settings.judge else {}),
    }
    undo = counted(runner, tally, roles)
    try:
        found: list[Proposals]
        if strategy is Strategy.ITERATIVE:
            found = [
                await optimize_call(
                    suite,
                    evidence,
                    runner,
                    settings,
                    model=proposer,
                    screen_runs=loop.screen_runs,
                    model_version=proposer_version,
                )
                for evidence in evidence_of(suite, report)
            ]
        else:
            found = await propose(
                suite,
                report,
                runner,
                model=proposer,
                count=candidates,
                model_version=proposer_version,
                strategy=strategy,
            )
        (proposals,) = found
        folder = out / migration / app / slug(proposals.evidence.call) / strategy.value
        write_proposals(found, folder, proposer, proposer_version, strategy)
        entry = CallCandidates(
            proposals.evidence.call,
            proposals.evidence.regressed,
            tuple(
                (f"{slug(proposals.evidence.call)}.{c.sample:02d}.json", c.patch)
                for c in proposals.candidates
            ),
        )
        result = await repair_call(suite, entry, runner, settings, loop)
    finally:
        undo()
    (folder / "repair-report.json").write_text(
        render_repair_json([result], settings, loop), encoding="utf-8"
    )
    screens = [s.new_mean for s in result.screened if s.error is None]
    return Row(
        migration=migration,
        app=app,
        call=result.call,
        kind=suite.cases[0].oracle.kind.value,
        cases=result.cases,
        regressed_cases=len(result.regressed),
        strategy=strategy.value,
        candidates=len(result.screened),
        best_screen=max(screens) if screens else None,
        old_mean=result.old_mean,
        unpatched_mean=result.unpatched_mean,
        status=_status(result),
        blocked_for_collateral=blocked_for_collateral(result),
        requests=dict(tally.requests),
        fresh=dict(tally.fresh),
        tokens=dict(tally.tokens),
    )


def _report_settings(report: Mapping[str, Any], runs: int) -> Settings:
    return Settings(
        old=str(report["old"]),
        new=str(report["new"]),
        runs=runs,
        reference=int(report["reference"]),
        method=Method.FIXED,
        temperature=float(report["temperature"]),
        max_tokens=int(report["max_tokens"]),
        new_think=report.get("new_think") or NEW_THINK,
        old_version=str(report.get("old_version") or ""),
        new_version=str(report.get("new_version") or ""),
        judge=report.get("judge"),
        judge_version=str(report.get("judge_version") or ""),
    )


Progress = Callable[[str], None]


async def run_migration(
    run_dir: Path,
    apps: Mapping[str, Path],
    runner: Runner,
    loop: LoopSettings,
    out: Path,
    *,
    strategies: Sequence[Strategy] = STRATEGIES,
    proposer: str = DEFAULT_PROPOSER,
    proposer_version: str = "",
    generator: str = DEFAULT_GENERATOR,
    generator_version: str = "",
    candidates: int = DEFAULT_CANDIDATES,
    extra: int = EXTRA_CASES,
    runs: int = 10,
    max_calls: int | None = None,
    drop: frozenset[str] = frozenset(),
    judge: str = DEFAULT_JUDGE,
    progress: Progress = lambda line: None,
) -> tuple[list[Row], list[dict[str, Any]]]:
    """Every regressed call of one corpus run, widened, tested and repaired.

    Returns the rows and one note per call that was not repaired by any
    strategy because it stopped regressing or was dropped.
    """
    migration = run_dir.name
    rows: list[Row] = []
    notes: list[dict[str, Any]] = []
    done = 0
    for report_file in sorted((run_dir / "runs").glob("app-*.report.json")):
        app = report_file.name.removesuffix(".report.json")
        report = json.loads(report_file.read_text(encoding="utf-8"))
        suite = read_suite(run_dir / "runs" / f"{app}.suite.json")
        settings = _report_settings(report, runs)
        for case in regressed_calls(report, suite):
            if max_calls is not None and done >= max_calls:
                return rows, notes
            name = f"{app}/{call_of(case)}"
            if name in drop:
                notes.append({"migration": migration, "call": name, "note": "dropped by hand"})
                continue
            done += 1
            widened = await widen(case, apps[app], runner, extra, generator, generator_version)
            has_text = any(c.oracle.kind.value == "text" for c in widened.cases)
            call_settings = replace(
                settings,
                judge=(settings.judge or judge) if has_text else None,
            )
            tested = await run_suite_on_models(widened, runner, call_settings)
            call_report = json.loads(render_run_json(tested))
            folder = out / migration / app / slug(call_of(case))
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "suite-report.json").write_text(render_run_json(tested), encoding="utf-8")
            if not tested.regressed:
                notes.append(
                    {"migration": migration, "call": name, "note": "no REGRESSED case when widened"}
                )
                progress(f"{migration} {name}: no longer REGRESSED with {len(widened.cases)} cases")
                continue
            for strategy in strategies:
                row = await repair_one(
                    migration,
                    app,
                    widened,
                    call_report,
                    runner,
                    call_settings,
                    loop,
                    strategy,
                    proposer=proposer,
                    proposer_version=proposer_version,
                    candidates=candidates,
                    out=out,
                )
                rows.append(row)
                progress(
                    f"{migration} {name} [{strategy.value}]: {row.status} "
                    f"({row.cases} cases, best screen {row.best_screen}, old {row.old_mean})"
                )
    return rows, notes


def wilson(successes: int, total: int, confidence: float = 0.95) -> tuple[float, float]:
    """Wilson score interval for a proportion."""
    if total == 0:
        return (0.0, 1.0)
    z = NormalDist().inv_cdf(0.5 + confidence / 2)
    p = successes / total
    centre = (p + z * z / (2 * total)) / (1 + z * z / total)
    half = z * sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / (1 + z * z / total)
    return (max(0.0, centre - half), min(1.0, centre + half))


def summarize(rows: Sequence[Row], notes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Fix rate with a 95% CI, outcomes and mean requests per call, by strategy."""
    strategies: dict[str, Any] = {}
    for name in dict.fromkeys(row.strategy for row in rows):
        mine = [row for row in rows if row.strategy == name]
        repaired = sum(row.status == "REPAIRED" for row in mine)
        low, high = wilson(repaired, len(mine))
        requests: Counter[str] = Counter()
        fresh: Counter[str] = Counter()
        for row in mine:
            requests.update(row.requests)
            fresh.update(row.fresh)
        strategies[name] = {
            "calls": len(mine),
            "repaired": repaired,
            "fix_rate": round(repaired / len(mine), 4) if mine else 0.0,
            "ci95": [round(low, 4), round(high, 4)],
            "outcomes": dict(Counter(row.status for row in mine)),
            "blocked_for_collateral": sum(row.blocked_for_collateral for row in mine),
            "mean_requests": {k: round(v / len(mine), 1) for k, v in sorted(requests.items())},
            "mean_fresh_requests": {k: round(v / len(mine), 1) for k, v in sorted(fresh.items())},
        }
    calls = {(row.migration, row.app, row.call) for row in rows}
    by_migration = Counter(migration for migration, _, _ in calls)
    return {
        "calls_repaired_by_any": len(
            {(r.migration, r.app, r.call) for r in rows if r.status == "REPAIRED"}
        ),
        "calls": len(calls),
        "calls_by_migration": dict(by_migration),
        "notes": list(notes),
        "strategies": strategies,
    }


def summary_lines(summary: Mapping[str, Any]) -> list[str]:
    lines = [
        f"Regressed calls repaired: {summary['calls']} calls, "
        f"{summary['calls_repaired_by_any']} repaired by at least one strategy"
    ]
    for name, stats in summary["strategies"].items():
        low, high = stats["ci95"]
        lines.append(
            f"  {name:<10} {stats['repaired']}/{stats['calls']} repaired "
            f"({stats['fix_rate']:.0%}, 95% CI {low:.0%}-{high:.0%}); "
            f"outcomes {stats['outcomes']}; blocked for collateral "
            f"{stats['blocked_for_collateral']}; mean requests {stats['mean_requests']}"
        )
    for note in summary["notes"]:
        lines.append(f"  not run: {note['migration']} {note['call']}: {note['note']}")
    return lines


async def run_all(
    run_dirs: Sequence[Path],
    work: Callable[[Path], Awaitable[tuple[list[Row], list[dict[str, Any]]]]],
) -> tuple[list[Row], list[dict[str, Any]]]:
    rows: list[Row] = []
    notes: list[dict[str, Any]] = []
    for run_dir in run_dirs:
        more_rows, more_notes = await work(run_dir)
        rows += more_rows
        notes += more_notes
    return rows, notes


def main(argv: Sequence[str] | None = None, runner: Runner | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--corpus", type=Path, default=Path("research/data/corpus"))
    parser.add_argument(
        "--run", type=Path, action="append", default=None, help="A corpus run folder. Repeatable."
    )
    parser.add_argument("--out", type=Path, default=Path("research/data/repair_eval"))
    parser.add_argument(
        "--calls", type=int, default=None, help="Only the first N regressed calls of each run."
    )
    parser.add_argument("--extra", type=int, default=EXTRA_CASES, help="Generated cases to add.")
    parser.add_argument(
        "--strategy", action="append", default=None, choices=[s.value for s in STRATEGIES]
    )
    parser.add_argument(
        "--drop-call", action="append", default=[], help="Leave out app-NN/path:line. Repeatable."
    )
    args = parser.parse_args(argv)
    apps_file = args.corpus / "apps.jsonl"
    if not apps_file.exists():
        print(f"{apps_file} not found. Run research.corpus.build first.", file=sys.stderr)
        return 1
    run_dirs = args.run or RUNS
    missing = [str(d) for d in run_dirs if not (d / "runs").is_dir()]
    if missing:
        print(
            f"No corpus run in {', '.join(missing)}. Run research.corpus.run first.",
            file=sys.stderr,
        )
        return 1
    apps = {f"app-{int(a['app']):02d}": Path(str(a["folder"])) for a in read_jsonl(apps_file)}
    strategies = [Strategy(s) for s in args.strategy] if args.strategy else list(STRATEGIES)
    loop = LoopSettings()
    cache: ResponseCache | None = None
    budget = Budget()
    proposer_version = generator_version = ""
    if runner is None:
        try:
            pinned = pin_versions(
                [ChatRequest.ask(name, "version") for name in (DEFAULT_PROPOSER, DEFAULT_GENERATOR)]
            )
        except RunnerError as error:
            print(f"Error: {error}", file=sys.stderr)
            return 2
        proposer_version, generator_version = (p.model_version for p in pinned)
        cache = ResponseCache()
        runner = Runner(cache=cache, budget=budget)
    used = runner

    def work(run_dir: Path) -> Awaitable[tuple[list[Row], list[dict[str, Any]]]]:
        return run_migration(
            run_dir,
            apps,
            used,
            loop,
            args.out,
            strategies=strategies,
            proposer_version=proposer_version,
            generator_version=generator_version,
            extra=args.extra,
            max_calls=args.calls,
            drop=frozenset(args.drop_call),
            progress=lambda line: print(line, file=sys.stderr),
        )

    try:
        rows, notes = asyncio.run(run_all(run_dirs, work))
    finally:
        if cache is not None:
            cache.close()
    write_jsonl([_row_dict(row) for row in rows], args.out / "results.jsonl")
    summary = summarize(rows, notes)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print("\n".join(summary_lines(summary)))
    print(budget.summary())
    return 0


def _row_dict(row: Row) -> dict[str, Any]:
    return {name: getattr(row, name) for name in Row.__slots__}


if __name__ == "__main__":
    raise SystemExit(main())
