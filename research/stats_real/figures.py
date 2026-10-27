"""Figures for the real-model experiment (ADR 0047), drawn from the results alone.

methods.png: false alarms on the null pair and the share of injected drops
found, for every method. upgrade.png: each test case's pass rate under Qwen 2.5
and Qwen 3, marked by the sequential verdict.
"""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

INK, MUTED, GRID = "#0b0b0b", "#52514e", "#d9d8d4"
BAR = "#2a78d6"
# Colour and shape both carry the verdict, so it does not depend on colour alone.
VERDICT_STYLE = {
    "REGRESSED": ("#d03b3b", "v"),
    "IMPROVED": ("#0ca30c", "^"),
    "EQUIVALENT": ("#2a78d6", "o"),
    "INCONCLUSIVE": ("#a3a29c", "s"),
}
SHORT = {"sequential + e-BH, stop cases that look fine": "sequential + e-BH,\nstop looks-fine"}


def _style(ax: Any) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(MUTED)
    ax.tick_params(colors=MUTED, labelcolor=INK, labelsize=8)
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def _bars(ax: Any, labels: Sequence[str], values: Sequence[float], fmt: str) -> None:
    positions = range(len(labels))
    ax.barh(positions, values, color=BAR, height=0.6)
    top = max(values, default=0) or 1
    for y, value in zip(positions, values, strict=True):
        ax.text(value + top * 0.02, y, fmt.format(value), va="center", fontsize=7, color=INK)
    ax.set_xlim(0, top * 1.3)
    ax.set_yticks(list(positions), labels)
    ax.invert_yaxis()


def plot_methods(results: Mapping[str, Any], out: Path) -> str:
    """Null false alarms and injected drops found, one row per method."""
    null = results["null"]
    labels = [SHORT.get(row["method"], row["method"]) for row in null]
    rates = sorted({row["inject_rate"] for row in results["injected"]})
    figure, axes = plt.subplots(
        1, 1 + len(rates), figsize=(7.6, 2.6), sharey=True, layout="constrained"
    )
    _style(axes[0])
    _bars(axes[0], labels, [row["false_alarms"] for row in null], "{:.2f}")
    axes[0].set_title("Nothing changed:\nfalse alarms per run", fontsize=8, color=INK)
    for ax, rate in zip(axes[1:], rates, strict=True):
        rows = [row for row in results["injected"] if row["inject_rate"] == rate]
        found = [row["found"] / row["of"] if row["of"] else 0.0 for row in rows]
        _style(ax)
        _bars(ax, labels, [100 * f for f in found], "{:.0f}%")
        ax.set_xlim(0, 130)
        ax.set_title(
            f"{rate:.0%} of answers made fails:\nreal drops found (of {rows[0]['of']})",
            fontsize=8,
            color=INK,
        )
    name = "methods.png"
    figure.savefig(out / name, dpi=200, metadata={"Software": None})
    plt.close(figure)
    return name


def plot_upgrade(
    old_rates: Mapping[str, float],
    new_rates: Mapping[str, float],
    verdicts: Mapping[str, str],
    out: Path,
) -> str:
    """Each case's pass rate before and after the upgrade, marked by verdict."""
    figure, ax = plt.subplots(figsize=(5.2, 4.0), layout="constrained")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.tick_params(colors=MUTED, labelcolor=INK, labelsize=8)
    ax.grid(color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    ax.plot([0, 1], [0, 1], color=MUTED, linewidth=0.8, linestyle="--")
    for verdict, (color, marker) in VERDICT_STYLE.items():
        names = [n for n, v in verdicts.items() if v == verdict]
        if not names:
            continue
        ax.scatter(
            [old_rates[n] for n in names],
            [new_rates[n] for n in names],
            color=color,
            marker=marker,
            s=42,
            edgecolors="white",
            linewidths=1,
            label=f"{verdict} ({len(names)})",
            zorder=3,
        )
    ax.set_xlim(-0.03, 1.03)
    ax.set_ylim(-0.03, 1.03)
    ax.set_xlabel("Pass rate, Qwen 2.5 (old)", color=INK)
    ax.set_ylabel("Pass rate, Qwen 3 (new)", color=INK)
    ax.legend(fontsize=7, frameon=False, loc="center left", bbox_to_anchor=(1.01, 0.5))
    name = "upgrade.png"
    figure.savefig(out / name, dpi=200, metadata={"Software": None})
    plt.close(figure)
    return name
