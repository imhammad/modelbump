"""RQ2 on real local models: the stats engine against real, random answers (ADR 0046).

Two local models answer the same made-up test cases many times (tasks.py
computes every right answer). From those answers we build three comparisons:

1. null: Qwen 2.5 against itself (two separate sets of answers). Nothing
   changed, so every REGRESSED is a false alarm.
2. injected: the same, but for every third test case each new answer is
   turned into a fail with chance 0.3 (and, separately, 0.6). We know exactly
   which cases got worse.
3. natural: Qwen 2.5 (old) against Qwen 3 (new), the real upgrade.

Each comparison is decided by a single-run diff, fixed k = 10 (no suite
control), fixed k = all answers + BH, sequential + e-BH, and sequential +
e-BH that stops cases that look fine. For null and injected, the answers are
reshuffled `--shuffles` times (seeded) to get rates instead of one count.

Answers come from Ollama on this machine, through the runner and its cache,
so a stopped run picks up where it left off, and a second run costs nothing.
Writes answers.jsonl, tasks.csv, results.json and two figures to
research/data/stats_real/ (results: ADR 0047).

Run from the repo root, with Ollama running and both models pulled:
    uv run python -m research.stats_real.run --quick   # 360 answers, about 2 minutes
    uv run python -m research.stats_real.run           # 9,000 answers, about 40 minutes
"""

import argparse
import asyncio
import csv
import json
import random
import sys
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean
from typing import Any

from modelbump.runner import (
    ChatRequest,
    ChatResult,
    ResponseCache,
    Runner,
    RunnerError,
    pin_versions,
)
from modelbump.stats import (
    Verdict,
    benjamini_hochberg,
    compare_counts,
    regression_p_value,
    run_suite,
)
from research.stats_real.figures import plot_methods, plot_upgrade
from research.stats_real.tasks import SYSTEM, Task, make_tasks, score

DEFAULT_OUT = Path("research/data/stats_real")
OLD_MODEL = "ollama/qwen2.5:7b"
NEW_MODEL = "ollama/qwen3:8b"
# Qwen 3 thinks by default; turn it off so both models answer straight away.
THINK = {OLD_MODEL: None, NEW_MODEL: "none"}
TEMPERATURE = 0.7
MAX_TOKENS = 48
CHUNK = 40
REPORT_EVERY = 200  # print progress after this many answers
INJECT_EVERY = 3  # every third test case gets the injected regression
FUTILITY = 0.1

Pools = dict[str, list[float]]  # task id -> scores, in sample order


@dataclass(frozen=True)
class Settings:
    per_family: int = 10
    answers: int = 50
    shuffles: int = 20
    inject_rates: tuple[float, ...] = (0.3, 0.6)
    q: float = 0.05
    small_k: int = 10

    @classmethod
    def quick(cls) -> "Settings":
        return cls(per_family=2, answers=10, shuffles=5, small_k=5)


# ---------------------------------------------------------------- collecting


def requests_for(tasks: Sequence[Task], model: str, samples: range) -> list[ChatRequest]:
    """One request per task and sample. The sample number is also the seed."""
    return [
        ChatRequest.ask(
            model,
            task.prompt,
            SYSTEM,
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            seed=sample,
            sample=sample,
            reasoning_effort=THINK.get(model),
        )
        for task in tasks
        for sample in samples
    ]


def collect(
    tasks: Sequence[Task],
    model: str,
    samples: range,
    runner: Runner,
    pin: Callable[[list[ChatRequest]], list[ChatRequest]] = pin_versions,
    report: Callable[[str], None] = print,
) -> tuple[Pools, list[dict[str, Any]]]:
    """Ask `model` every task once per sample. Returns scores and the raw answers."""
    requests = pin(requests_for(tasks, model, samples))
    owners = [task for task in tasks for _ in samples]  # same order as the requests
    pools: Pools = {task.id: [] for task in tasks}
    rows: list[dict[str, Any]] = []
    started = time.monotonic()
    cached = 0
    for start in range(0, len(requests), CHUNK):
        chunk = requests[start : start + CHUNK]
        outcomes = asyncio.run(runner.run_each(chunk))
        for task, request, outcome in zip(
            owners[start : start + CHUNK], chunk, outcomes, strict=True
        ):
            if isinstance(outcome, RunnerError):
                raise outcome
            cached += outcome.cached
            value = score(task, outcome.text)
            pools[task.id].append(value)
            rows.append(_row(task, request, outcome, value))
        done = start + len(chunk)
        if done % REPORT_EVERY and done != len(requests):
            continue
        minutes = (time.monotonic() - started) / 60
        report(
            f"{model}: {done:,}/{len(requests):,} answers "
            f"({cached:,} from the cache, {minutes:.1f} min)"
        )
    return pools, rows


def _row(task: Task, request: ChatRequest, result: ChatResult, value: float) -> dict[str, Any]:
    return {
        "task": task.id,
        "model": request.model,
        "sample": request.sample,
        "text": result.text,
        "score": value,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
    }


# ---------------------------------------------------------------- deciding


@dataclass
class Decision:
    flagged: list[str]
    answers: int
    verdicts: dict[str, Verdict] | None = None


def _iterate(old: Sequence[float], new: Sequence[float]) -> Callable[[], tuple[float, float]]:
    pairs: Iterator[tuple[float, float]] = zip(old, new, strict=True)
    return lambda: next(pairs)


def decide(old: Pools, new: Pools, settings: Settings) -> dict[str, Decision]:
    """Every method's REGRESSED cases and answers used per model."""
    names = list(old)
    k = len(old[names[0]])
    small = min(settings.small_k, k)
    decisions: dict[str, Decision] = {}
    decisions["single run"] = Decision(
        [n for n in names if old[n][0] == 1 and new[n][0] == 0], len(names)
    )
    flagged_small = []
    for n in names:
        result = compare_counts(
            round(sum(old[n][:small])), small, round(sum(new[n][:small])), small, margin=0.0
        )
        if result.verdict is Verdict.REGRESSED:
            flagged_small.append(n)
    decisions[f"fixed k={small}"] = Decision(flagged_small, small * len(names))
    p_values = [regression_p_value(round(sum(old[n])), k, round(sum(new[n])), k) for n in names]
    rejected = benjamini_hochberg(p_values, settings.q)
    decisions[f"fixed k={k} + BH"] = Decision(
        [n for n, r in zip(names, rejected, strict=True) if r], k * len(names)
    )
    for label, futility in (
        ("sequential + e-BH", None),
        ("sequential + e-BH, stop cases that look fine", FUTILITY),
    ):
        suite = run_suite(
            {n: _iterate(old[n], new[n]) for n in names},
            q=settings.q,
            max_runs=k,
            futility=futility,
        )
        decisions[label] = Decision(
            suite.named(Verdict.REGRESSED),
            suite.total_runs,
            {item.name: item.verdict for item in suite.items},
        )
    return decisions


def split(pool: Pools, answers: int, shuffle: int) -> tuple[Pools, Pools]:
    """Two disjoint sets of `answers` per task; shuffle 0 keeps the sample order."""
    old: Pools = {}
    new: Pools = {}
    for name, scores in pool.items():
        values = list(scores)
        if shuffle:
            random.Random(f"shuffle-{shuffle}-{name}").shuffle(values)
        old[name], new[name] = values[:answers], values[answers : 2 * answers]
    return old, new


def inject(new: Pools, injected: set[str], rate: float, shuffle: int) -> Pools:
    """Turn each answer of the injected cases into a fail with chance `rate`."""
    out: Pools = {}
    for name, scores in new.items():
        if name in injected:
            rng = random.Random(f"inject-{shuffle}-{name}")
            out[name] = [0.0 if rng.random() < rate else s for s in scores]
        else:
            out[name] = list(scores)
    return out


def _tally(
    decisions_per_shuffle: Sequence[Mapping[str, Decision]],
    worse: set[str],
    detectable: set[str],
) -> list[dict[str, Any]]:
    rows = []
    for method in decisions_per_shuffle[0]:
        flagged = [d[method].flagged for d in decisions_per_shuffle]
        false = [sum(n not in worse for n in f) for f in flagged]
        found = [sum(n in detectable for n in f) for f in flagged]
        rows.append(
            {
                "method": method,
                "false_alarms": mean(false),
                "max_false_alarms": max(false),
                "found": mean(found),
                "of": len(detectable),
                "answers_per_model": mean(d[method].answers for d in decisions_per_shuffle),
            }
        )
    return rows


def null_and_injected(
    tasks: Sequence[Task], pool: Pools, settings: Settings
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    injected = {t.id for i, t in enumerate(tasks) if i % INJECT_EVERY == 0}
    rates = {name: mean(scores) for name, scores in pool.items()}
    splits = [split(pool, settings.answers, shuffle) for shuffle in range(settings.shuffles)]
    null_rows = _tally([decide(old, new, settings) for old, new in splits], set(), set())
    injected_rows: list[dict[str, Any]] = []
    for rate in settings.inject_rates:
        # A case can only get visibly worse if it passes often enough to lose 10 points.
        detectable = {n for n in injected if rates[n] * rate >= 0.1}
        runs = [
            decide(old, inject(new, injected, rate, shuffle), settings)
            for shuffle, (old, new) in enumerate(splits)
        ]
        injected_rows.extend(
            {"inject_rate": rate} | row for row in _tally(runs, injected, detectable)
        )
    return null_rows, injected_rows


def natural(old: Pools, new: Pools, settings: Settings) -> dict[str, Any]:
    decisions = decide(old, new, settings)
    sequential = decisions["sequential + e-BH"].verdicts or {}
    return {
        "flagged": {m: len(d.flagged) for m, d in decisions.items()},
        "answers_per_model": {m: d.answers for m, d in decisions.items()},
        "sequential_verdicts": {v.value: sum(x is v for x in sequential.values()) for v in Verdict},
        "per_task": {n: v.value for n, v in sequential.items()},
        "regressed": decisions["sequential + e-BH"].flagged,
    }


def tokens_per_answer(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    """Mean prompt + reply tokens of one answer, per model."""
    per_model: dict[str, list[int]] = {}
    for row in rows:
        per_model.setdefault(row["model"], []).append(row["input_tokens"] + row["output_tokens"])
    return {model: mean(values) for model, values in per_model.items()}


def family_rates(tasks: Sequence[Task], pool: Pools) -> dict[str, float]:
    families: dict[str, list[float]] = {}
    for task in tasks:
        families.setdefault(task.family, []).extend(pool[task.id])
    return {family: mean(values) for family, values in families.items()}


# ---------------------------------------------------------------- outputs


def analyse(
    tasks: Sequence[Task], old_pool: Pools, new_pool: Pools, settings: Settings
) -> dict[str, Any]:
    """Everything in results.json, from the scores alone (no models needed)."""
    null_rows, injected_rows = null_and_injected(tasks, old_pool, settings)
    old_first = {n: s[: settings.answers] for n, s in old_pool.items()}
    return {
        "settings": asdict(settings),
        "models": {"old": OLD_MODEL, "new": NEW_MODEL},
        "pass_rates": {
            OLD_MODEL: family_rates(tasks, old_pool),
            NEW_MODEL: family_rates(tasks, new_pool),
        },
        "null": null_rows,
        "injected": injected_rows,
        "natural": natural(old_first, new_pool, settings),
    }


def summary(results: Mapping[str, Any]) -> list[str]:
    lines = ["Pass rate by family (old / new):"]
    old_rates = results["pass_rates"][OLD_MODEL]
    new_rates = results["pass_rates"][NEW_MODEL]
    for family in old_rates:
        lines.append(f"  {family}: {old_rates[family]:.0%} / {new_rates[family]:.0%}")
    lines.append("Null (Qwen 2.5 against itself), false alarms per run:")
    for row in results["null"]:
        lines.append(
            f"  {row['method']}: {row['false_alarms']:.2f} (max {row['max_false_alarms']}), "
            f"answers {row['answers_per_model']:,.0f}"
        )
    lines.append("Injected (every third case made worse), found / false alarms:")
    for row in results["injected"]:
        lines.append(
            f"  fails added {row['inject_rate']:.0%}, {row['method']}: "
            f"{row['found']:.1f} of {row['of']} / "
            f"{row['false_alarms']:.2f}, answers {row['answers_per_model']:,.0f}"
        )
    nat = results["natural"]
    lines.append("Natural (Qwen 2.5 -> Qwen 3), REGRESSED cases:")
    for method, count in nat["flagged"].items():
        lines.append(f"  {method}: {count}, answers {nat['answers_per_model'][method]:,}")
    verdicts = ", ".join(f"{k} {v}" for k, v in nat["sequential_verdicts"].items())
    lines.append(f"  sequential + e-BH verdicts: {verdicts}")
    lines.append(f"  REGRESSED under sequential + e-BH: {', '.join(nat['regressed']) or 'none'}")
    tokens = results.get("tokens_per_answer")
    if tokens:
        both = tokens[OLD_MODEL] + tokens[NEW_MODEL]
        lines.append(
            "Tokens per answer (prompt + reply): "
            + ", ".join(f"{model} {value:.1f}" for model, value in tokens.items())
        )
        lines.append("Tokens for the natural comparison, both models (from the mean per answer):")
        for method, answers in nat["answers_per_model"].items():
            lines.append(f"  {method}: {answers * both:,.0f}")
    return lines


def write_outputs(
    out: Path,
    tasks: Sequence[Task],
    rows: Sequence[Mapping[str, Any]],
    results: Mapping[str, Any],
    old_pool: Pools,
    new_pool: Pools,
) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with (out / "answers.jsonl").open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    with (out / "tasks.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["task", "family", "answer", "old_pass_rate", "new_pass_rate", "verdict"])
        for task in tasks:
            writer.writerow(
                [
                    task.id,
                    task.family,
                    task.answer,
                    f"{mean(old_pool[task.id]):.3f}",
                    f"{mean(new_pool[task.id]):.3f}",
                    results["natural"]["per_task"][task.id],
                ]
            )
    (out / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    figures = out / "figures"
    figures.mkdir(exist_ok=True)
    plot_methods(results, figures)
    # The upgrade was decided on Qwen 2.5's first answers, as many as Qwen 3 gave.
    plot_upgrade(
        {n: mean(s[: len(new_pool[n])]) for n, s in old_pool.items()},
        {n: mean(s) for n, s in new_pool.items()},
        results["natural"]["per_task"],
        figures,
    )


def main(
    argv: Sequence[str] | None = None,
    runner: Runner | None = None,
    pin: Callable[[list[ChatRequest]], list[ChatRequest]] = pin_versions,
) -> int:
    assert __doc__ is not None
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output folder.")
    parser.add_argument("--quick", action="store_true", help="12 test cases, 10 answers each.")
    args = parser.parse_args(argv)
    settings = Settings.quick() if args.quick else Settings()
    tasks = make_tasks(settings.per_family)
    total = len(tasks) * settings.answers * 3
    print(
        f"{len(tasks)} test cases, {settings.answers} answers per model per comparison: "
        f"{total:,} answers in all (cached ones are free)."
    )
    cache = ResponseCache()
    runner = runner or Runner(cache=cache)
    try:
        old_pool, old_rows = collect(tasks, OLD_MODEL, range(2 * settings.answers), runner, pin)
        new_pool, new_rows = collect(tasks, NEW_MODEL, range(settings.answers), runner, pin)
    except RunnerError as error:
        print(f"Error: {error}", file=sys.stderr)
        print("Is Ollama running? Start it with: open -a Ollama", file=sys.stderr)
        return 1
    finally:
        cache.close()
    results = analyse(tasks, old_pool, new_pool, settings)
    results["tokens_per_answer"] = tokens_per_answer(old_rows + new_rows)
    write_outputs(args.out, tasks, old_rows + new_rows, results, old_pool, new_pool)
    for line in summary(results):
        print(line)
    print(f"Wrote {args.out}/answers.jsonl, tasks.csv, results.json and figures/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
