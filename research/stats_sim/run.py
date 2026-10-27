"""Simulation study of the stats engine: error rates, power and cost (ADR 0044).

Made-up models with known true pass rates answer made-up test cases, so we know
the right verdict and can count every wrong one. Four experiments:

1. item: one test case. P(REGRESSED), P(EQUIVALENT) and answers per model for
   a single-run diff, fixed-k tests (ADR 0041) and the sequential test
   (ADR 0042), over a grid of true pass rates. Fixed-k numbers are exact
   (summed over every pair of counts); the others are simulated.
2. peeking: the fixed-k interval checked after every answer.
3. suite: 300-case suites with and without suite control (BH for fixed-k,
   e-BH for sequential, ADR 0043).
4. stopping: variants of the suite stopping rule (lower bar, higher cap,
   stopping cases that look fine), to see what limits power on small drops.

Every random draw comes from a seed written in the code, so the outputs are
the same on every machine. Writes CSV files, results.json and figures to
research/data/stats_sim/ (or --out). Nothing else changes.

Run from the repo root (about 3 minutes; --quick takes seconds):
    uv run python -m research.stats_sim.run
"""

import argparse
import csv
import json
import random
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from math import comb
from pathlib import Path
from statistics import mean
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

from modelbump.stats import (
    DEFAULT_ALPHA,
    DEFAULT_MARGIN,
    DEFAULT_MAX_RUNS,
    SequentialTest,
    SimulatedSuite,
    Verdict,
    benjamini_hochberg,
    compare_counts,
    decide_suite,
    regression_p_value,
    run_sequential,
    simulated_suite,
)

DEFAULT_OUT = Path("research/data/stats_sim")
OLD_RATES = (0.6, 0.9, 1.0)
DROPS = (0.0, 0.05, 0.1, 0.15, 0.2, 0.3, 0.5)
FIXED_KS = (10, 30, 100)
SUITE_FIXED_K = 30
# About the answers per test case that sequential + e-BH spends, for a same-budget baseline.
SUITE_BUDGET_K = 170
SUITE_SCENARIOS = ((0, 0.3), (30, 0.3), (30, 0.15), (150, 0.15))
STOPPING_SCENARIO = (30, 0.15)
FUTILITY_FLOOR = 0.1
# A fixed-k suite with about the budget of the "stop cases that look fine" rule.
STOPPING_FIXED_K = 300
FUTILITY_MIN_RUNS = 20
# Categorical slots 1 to 4 of the reference palette, in fixed order, with
# markers and line styles so the figures still read in black and white.
METHOD_STYLE = {
    "single run": ("#2a78d6", "o", ":"),
    "fixed k=10": ("#eb6834", "s", "--"),
    "fixed k=30": ("#eb6834", "^", "-."),
    "fixed k=100": ("#eb6834", "D", "-"),
    "sequential": ("#1baf7a", "v", "-"),
}
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#d9d8d4"


@dataclass(frozen=True)
class Settings:
    reps: int = 1000
    seeds: int = 20
    stopping_seeds: int = 5
    suite_size: int = 300
    alpha: float = DEFAULT_ALPHA
    margin: float = DEFAULT_MARGIN
    max_runs: int = DEFAULT_MAX_RUNS

    @classmethod
    def quick(cls) -> "Settings":
        return cls(reps=30, seeds=1, stopping_seeds=1, suite_size=30, max_runs=60)

    def scaled(self, regressed: int) -> int:
        """Scale a 300-case scenario's regressed count to this suite size."""
        return regressed * self.suite_size // 300


# ---------------------------------------------------------------- experiment 1


def _pmf(runs: int, rate: float) -> list[float]:
    return [comb(runs, k) * rate**k * (1 - rate) ** (runs - k) for k in range(runs + 1)]


def verdict_table(runs: int, alpha: float, margin: float) -> list[list[Verdict]]:
    """Verdict for every pair of pass counts at a fixed k (old count, new count)."""
    return [
        [
            compare_counts(a, runs, b, runs, alpha=alpha, margin=margin).verdict
            for b in range(runs + 1)
        ]
        for a in range(runs + 1)
    ]


def fixed_k_chances(
    table: list[list[Verdict]], old_rate: float, new_rate: float
) -> dict[Verdict, float]:
    """Exact chance of each verdict for a fixed-k test."""
    runs = len(table) - 1
    old_pmf, new_pmf = _pmf(runs, old_rate), _pmf(runs, new_rate)
    chances = dict.fromkeys(Verdict, 0.0)
    for a in range(runs + 1):
        for b in range(runs + 1):
            chances[table[a][b]] += old_pmf[a] * new_pmf[b]
    return chances


def _answers(
    rng: random.Random, old_rate: float, new_rate: float
) -> Callable[[], tuple[bool, bool]]:
    def next_round() -> tuple[bool, bool]:
        return rng.random() < old_rate, rng.random() < new_rate

    return next_round


def sequential_cell(
    old_rate: float, new_rate: float, settings: Settings
) -> tuple[dict[Verdict, float], float]:
    """Simulated chance of each verdict and mean answers for the sequential test."""
    counts = dict.fromkeys(Verdict, 0)
    runs = []
    for rep in range(settings.reps):
        rng = random.Random(f"item-{old_rate}-{new_rate}-{rep}")
        result = run_sequential(
            _answers(rng, old_rate, new_rate),
            alpha=settings.alpha,
            margin=settings.margin,
            max_runs=settings.max_runs,
        )
        counts[result.verdict] += 1
        runs.append(result.runs)
    return {v: n / settings.reps for v, n in counts.items()}, mean(runs)


def item_experiment(settings: Settings) -> list[dict[str, Any]]:
    tables = {k: verdict_table(k, settings.alpha, settings.margin) for k in FIXED_KS}
    rows: list[dict[str, Any]] = []
    for old_rate in OLD_RATES:
        for drop in DROPS:
            new_rate = round(old_rate - drop, 10)
            if new_rate < 0:
                continue
            cell = {"old_rate": old_rate, "new_rate": new_rate, "drop": drop}
            rows.append(
                cell
                | {
                    "method": "single run",
                    "p_regressed": old_rate * (1 - new_rate),
                    "p_equivalent": None,
                    "mean_answers": 1.0,
                }
            )
            for k, table in tables.items():
                chances = fixed_k_chances(table, old_rate, new_rate)
                rows.append(
                    cell
                    | {
                        "method": f"fixed k={k}",
                        "p_regressed": chances[Verdict.REGRESSED],
                        "p_equivalent": chances[Verdict.EQUIVALENT],
                        "mean_answers": float(k),
                    }
                )
            chances, answers = sequential_cell(old_rate, new_rate, settings)
            rows.append(
                cell
                | {
                    "method": "sequential",
                    "p_regressed": chances[Verdict.REGRESSED],
                    "p_equivalent": chances[Verdict.EQUIVALENT],
                    "mean_answers": answers,
                }
            )
    return rows


# ---------------------------------------------------------------- experiment 2


def peeking_experiment(settings: Settings) -> list[dict[str, Any]]:
    """False REGRESSED when the fixed-k interval is checked after every answer."""
    rows = []
    for rate in (0.6, 0.9):
        alarms = 0
        for rep in range(settings.reps):
            rng = random.Random(f"peek-{rate}-{rep}")
            old = new = 0
            for runs in range(1, settings.max_runs + 1):
                old += rng.random() < rate
                new += rng.random() < rate
                verdict = compare_counts(
                    old, runs, new, runs, alpha=settings.alpha, margin=settings.margin
                ).verdict
                if verdict is Verdict.REGRESSED:
                    alarms += 1
                    break
        rows.append(
            {
                "rate": rate,
                "max_answers": settings.max_runs,
                "false_regressed": alarms / settings.reps,
            }
        )
    return rows


# ---------------------------------------------------------------- experiment 3


def _flagged_single_run(suite: SimulatedSuite) -> tuple[list[str], int]:
    flagged = []
    for name, next_round in suite.items.items():
        old_pass, new_pass = next_round()
        if old_pass and not new_pass:
            flagged.append(name)
    return flagged, len(suite.items)


def _fixed_k_counts(suite: SimulatedSuite, k: int) -> dict[str, tuple[int, int]]:
    counts = {}
    for name, next_round in suite.items.items():
        answers = [next_round() for _ in range(k)]
        counts[name] = (sum(a for a, _ in answers), sum(b for _, b in answers))
    return counts


def _flagged_fixed_k(
    suite: SimulatedSuite, k: int, settings: Settings, control: bool
) -> tuple[list[str], int]:
    counts = _fixed_k_counts(suite, k)
    names = list(counts)
    if control:
        p_values = [regression_p_value(old, k, new, k) for old, new in counts.values()]
        rejected = benjamini_hochberg(p_values, settings.alpha)
        return [n for n, r in zip(names, rejected, strict=True) if r], k * len(names)
    flagged = [
        name
        for name, (old, new) in counts.items()
        if compare_counts(old, k, new, k, alpha=settings.alpha, margin=0.0).verdict
        is Verdict.REGRESSED
    ]
    return flagged, k * len(names)


@dataclass
class StopRule:
    """How each test case of a sequential suite stops."""

    bar: float  # wealth that stops a case (the per-case alpha is 1/bar)
    max_runs: int
    futility: float | None = None


def run_sequential_suite(
    suite: SimulatedSuite, rule: StopRule, settings: Settings, control: bool
) -> tuple[list[str], int, int]:
    """Flagged names, answers per model, and EQUIVALENT count."""
    tests = []
    for next_round in suite.items.values():
        test = SequentialTest(alpha=1 / rule.bar, margin=settings.margin, max_runs=rule.max_runs)
        while not test.done:
            test.add(*next_round())
            if (
                rule.futility is not None
                and test.runs >= FUTILITY_MIN_RUNS
                and test.evidence.regressed < rule.futility
                and not test.done
            ):
                break
        tests.append(test)
    names = list(suite.items)
    if control:
        verdicts = decide_suite([t.evidence for t in tests], settings.alpha)
    else:
        verdicts = [t.verdict for t in tests]
    flagged = [n for n, v in zip(names, verdicts, strict=True) if v is Verdict.REGRESSED]
    equivalent = sum(v is Verdict.EQUIVALENT for v in verdicts)
    return flagged, sum(t.runs for t in tests), equivalent


def _score(suite: SimulatedSuite, flagged: Sequence[str]) -> tuple[int, int]:
    true = sum(suite.really_worse(name) for name in flagged)
    return true, len(flagged) - true


SUITE_METHODS = (
    "single run",
    f"fixed k={SUITE_FIXED_K}",
    f"fixed k={SUITE_FIXED_K} + BH",
    f"fixed k={SUITE_BUDGET_K} + BH",
    "sequential",
    "sequential + e-BH",
)


def suite_experiment(settings: Settings) -> list[dict[str, Any]]:
    m = settings.suite_size
    rows = []
    for regressed_300, drop in SUITE_SCENARIOS:
        regressed = settings.scaled(regressed_300)
        for method in SUITE_METHODS:
            found, false, answers, fdp = [], [], [], []
            for seed in range(1, settings.seeds + 1):
                suite = simulated_suite(m, regressed, drop, seed)
                if method == "single run":
                    flagged, used = _flagged_single_run(suite)
                elif method.startswith("fixed"):
                    k = int(method.split()[1].removeprefix("k="))
                    flagged, used = _flagged_fixed_k(
                        suite, k, settings, control=method.endswith("BH")
                    )
                else:
                    control = method.endswith("e-BH")
                    bar = m / settings.alpha if control else 1 / settings.alpha
                    flagged, used, _ = run_sequential_suite(
                        suite, StopRule(bar, settings.max_runs), settings, control
                    )
                true, wrong = _score(suite, flagged)
                found.append(true)
                false.append(wrong)
                answers.append(used)
                fdp.append(wrong / max(1, len(flagged)))
            rows.append(
                {
                    "regressed": regressed,
                    "drop": drop,
                    "method": method,
                    "true_found": mean(found),
                    "false_alarms": mean(false),
                    "max_false_alarms": max(false),
                    "fdr": mean(fdp),
                    "answers_per_model": mean(answers),
                }
            )
    return rows


# ---------------------------------------------------------------- experiment 4


def stopping_rules(settings: Settings) -> dict[str, StopRule]:
    m = settings.suite_size
    bar = m / settings.alpha
    longer = settings.max_runs * 5 // 2
    return {
        f"bar m/q, cap {settings.max_runs} (default)": StopRule(bar, settings.max_runs),
        f"bar m/(10q), cap {settings.max_runs}": StopRule(bar / 10, settings.max_runs),
        f"bar m/q, cap {longer}": StopRule(bar, longer),
        f"bar m/q, cap {longer}, stop cases that look fine": StopRule(bar, longer, FUTILITY_FLOOR),
    }


def stopping_experiment(settings: Settings) -> list[dict[str, Any]]:
    regressed_300, drop = STOPPING_SCENARIO
    regressed = settings.scaled(regressed_300)
    rows = []
    for label, rule in stopping_rules(settings).items():
        found, false, answers, equivalent = [], [], [], []
        for seed in range(1, settings.stopping_seeds + 1):
            suite = simulated_suite(settings.suite_size, regressed, drop, seed)
            flagged, used, eq = run_sequential_suite(suite, rule, settings, control=True)
            true, wrong = _score(suite, flagged)
            found.append(true)
            false.append(wrong)
            answers.append(used)
            equivalent.append(eq)
        rows.append(
            {
                "rule": label,
                "regressed": regressed,
                "drop": drop,
                "true_found": mean(found),
                "false_alarms": mean(false),
                "equivalent": mean(equivalent),
                "answers_per_model": mean(answers),
            }
        )
    found, false = [], []
    for seed in range(1, settings.stopping_seeds + 1):
        suite = simulated_suite(settings.suite_size, regressed, drop, seed)
        flagged, used = _flagged_fixed_k(suite, STOPPING_FIXED_K, settings, control=True)
        true, wrong = _score(suite, flagged)
        found.append(true)
        false.append(wrong)
    rows.append(
        {
            "rule": f"fixed k={STOPPING_FIXED_K} + BH, for comparison",
            "regressed": regressed,
            "drop": drop,
            "true_found": mean(found),
            "false_alarms": mean(false),
            "equivalent": None,
            "answers_per_model": float(used),
        }
    )
    return rows


# ---------------------------------------------------------------- outputs


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _style(ax: Any) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(MUTED)
    ax.tick_params(colors=MUTED, labelcolor=INK, labelsize=8)
    ax.grid(axis="y", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def plot_item(rows: Sequence[Mapping[str, Any]], old_rate: float, out: Path) -> list[str]:
    """Power curve and cost curve at one old pass rate."""
    names = []
    for column, ylabel, name in (
        ("p_regressed", "Chance of REGRESSED", "power.png"),
        ("mean_answers", "Answers per model", "answers.png"),
    ):
        figure, ax = plt.subplots(figsize=(6.6, 2.8), layout="constrained")
        _style(ax)
        for method, (color, marker, linestyle) in METHOD_STYLE.items():
            points = [r for r in rows if r["method"] == method and r["old_rate"] == old_rate]
            ax.plot(
                [100 * r["drop"] for r in points],
                [r[column] for r in points],
                color=color,
                marker=marker,
                linestyle=linestyle,
                linewidth=2,
                markersize=6,
                label=method,
            )
        if column == "p_regressed":
            ax.axhline(DEFAULT_ALPHA, color=MUTED, linewidth=0.8, linestyle="--")
            ax.set_ylim(0, 1.02)
        else:
            ax.set_yscale("log")
            ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:g}"))
        ax.set_xlabel(f"True drop in pass rate (points), old model at {old_rate:.0%}", color=INK)
        ax.set_ylabel(ylabel, color=INK)
        ax.legend(fontsize=7, frameon=False, loc="center left", bbox_to_anchor=(1.01, 0.5))
        figure.savefig(out / name, dpi=200, metadata={"Software": None})
        plt.close(figure)
        names.append(name)
    return names


def run(settings: Settings, out: Path) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    (out / "figures").mkdir(exist_ok=True)
    results: dict[str, Any] = {
        "settings": settings.__dict__,
        "item": item_experiment(settings),
        "peeking": peeking_experiment(settings),
        "suite": suite_experiment(settings),
        "stopping": stopping_experiment(settings),
    }
    for name in ("item", "peeking", "suite", "stopping"):
        write_csv(out / f"{name}.csv", results[name])
    (out / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    plot_item(results["item"], 0.9, out / "figures")
    return results


def summary(results: Mapping[str, Any]) -> list[str]:
    lines = []
    worst_false = max(
        r["p_regressed"] for r in results["item"] if r["drop"] == 0 and r["method"] != "single run"
    )
    single = max(
        r["p_regressed"] for r in results["item"] if r["drop"] == 0 and r["method"] == "single run"
    )
    lines.append(
        f"Item, nothing changed: worst false REGRESSED {worst_false:.1%} "
        f"(fixed k and sequential), single run {single:.1%}"
    )
    for row in results["peeking"]:
        lines.append(
            f"Peeking at fixed k after every answer, both at {row['rate']:.0%}: "
            f"false REGRESSED {row['false_regressed']:.1%}"
        )
    for row in results["suite"]:
        if row["method"] in ("sequential", "sequential + e-BH", f"fixed k={SUITE_BUDGET_K} + BH"):
            lines.append(
                f"Suite, {row['regressed']} worse by {row['drop'] * 100:.0f} points, "
                f"{row['method']}: found {row['true_found']:.1f}, "
                f"false alarms {row['false_alarms']:.1f}, answers {row['answers_per_model']:,.0f}"
            )
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    assert __doc__ is not None
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output folder.")
    parser.add_argument("--quick", action="store_true", help="Tiny settings, for a smoke test.")
    args = parser.parse_args(argv)
    settings = Settings.quick() if args.quick else Settings()
    results = run(settings, args.out)
    for line in summary(results):
        print(line)
    print(f"Wrote {args.out}/item.csv, peeking.csv, suite.csv, stopping.csv, results.json")
    print(f"Wrote {args.out}/figures/power.png and answers.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
