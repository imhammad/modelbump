"""Every number, table and figure in Paper 1, built from the data files (ADR 0019).

Reads the outputs of the earlier steps in research/data and writes:

- ``numbers.tex``: one LaTeX command per number the paper cites, such as
  ``\\MigrationsAway`` for 40,876, so no number is ever typed by hand;
- ``numbers.json``: the same numbers, unrounded, for checking;
- ``tables/*.tex``: the body of each table (a ``tabular``, using booktabs);
- ``figures/*.pdf``: the figures.

Kim's numbers are copied from the paper (arXiv:2609.31288) with the section
they come from. The few numbers this script cannot rebuild, because the code
that made them has since changed, are in ``RECORDED`` with their source.

Run from the repo root, after every earlier step:
    uv run python -m research.analysis.paper
"""

import argparse
import csv
import json
import math
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.figure import Figure

from research.analysis.lag import WINDOWS
from research.filtering.filter import read_jsonl
from research.validation import files_check
from research.validation import score as filter_score
from research.validation.score import cohen_kappa, wilson

# What each input is, and the command that makes it.
INPUTS: dict[str, str] = {
    "candidates.stats.json": "research.mining.miner",
    "labeled.stats.json": "research.filtering.filter",
    "timing.stats.json": "research.enrichment.timing",
    "timing_90d.stats.json": (
        "research.enrichment.timing --retired-by 2026-07-11 --out research/data/timing_90d.jsonl"
    ),
    "timing.jsonl": "research.enrichment.timing",
    "lag.stats.json": "research.analysis.lag --retired-by 2026-07-11",
    "targets.stats.json": "research.enrichment.targets",
    "files.stats.json": "research.enrichment.files",
    "files.jsonl": "research.enrichment.files",
    "robustness.json": "research.analysis.robustness",
    "validation_v2_adjudicated/sample.csv": "the labelled second sample (Step 15)",
    "validation_v2_adjudicated/sample_key.csv": "research.validation.sample (Step 15)",
    "validation_v2_adjudicated/strata.json": "research.validation.sample (Step 15)",
    "validation_v2_adjudicated/sample_b.csv": "the second person's labels (Step 16)",
    "validation_v2_adjudicated/targets_check.csv": "research.validation.targets_check",
    "validation_files/sample.csv": "the labelled file-kind sheet (Step 20)",
    "validation_files/sample_key.csv": "research.validation.files_check",
}

# Kim (2026), arXiv:2609.31288, with where each number is in the paper.
KIM: dict[str, Any] = {
    "commits": 22_555,  # abstract
    "repos": 17_703,  # abstract
    "after_shutdown": (82, 79, 84),  # abstract: share after the shutdown, 95% CI
    "file_level": 3_931,  # Section 4.4: migrations with file data
    "touch_test": 16,  # Section 4.4: "16% of migrations also touch a test file"
    "mention_eval": 4.5,  # Section 4.5: messages that mention an evaluation suite
}

# Numbers that cannot be rebuilt from today's code, with their source.
RECORDED: dict[str, tuple[int, int, str]] = {
    # Target check on the held-out sample before the rules were tuned (Step 19).
    "TargetCheckBefore": (70, 97, "ADR 0017, revision of 13 October 2026"),
}

PROVIDERS = ("openai", "anthropic", "google")
NAMES = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "google": "Google",
    "openai+anthropic": "OpenAI and Anthropic",
    "all": "All",
}
# Categorical slots 1 to 3 of the reference palette (validated, fixed order).
COLORS = {"openai": "#2a78d6", "anthropic": "#eb6834", "google": "#1baf7a"}
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#d9d8d4"


class MissingInputs(Exception):
    """Some input files are not there yet."""


class OutOfDate(Exception):
    """An input was built from older data than the others."""


@dataclass
class Paper:
    """Everything the script writes."""

    numbers: dict[str, str] = field(default_factory=dict)  # command -> LaTeX text
    raw: dict[str, Any] = field(default_factory=dict)  # command -> unrounded value
    tables: dict[str, str] = field(default_factory=dict)  # file name -> LaTeX
    figures: dict[str, Figure] = field(default_factory=dict)  # file name -> figure

    def put(self, name: str, text: str, value: Any = None) -> None:
        if not name.isalpha():
            raise ValueError(f"LaTeX command names are letters only: {name!r}")
        if name in self.numbers:
            raise ValueError(f"{name} is set twice")
        self.numbers[name] = text
        self.raw[name] = text if value is None else value

    def count(self, name: str, value: int) -> None:
        self.put(name, f"{value:,}", value)

    def share(self, name: str, part: int, whole: int, ci: bool = True) -> None:
        """``name`` as a percentage; with ``ci``, also ``nameLow`` and ``nameHigh``."""
        value = part / whole if whole else math.nan
        self.put(name, pct(value), value)
        if ci:
            low, high = wilson(part, whole)
            self.put(name + "Low", pct(low), low)
            self.put(name + "High", pct(high), high)


def pct(value: float) -> str:
    """A share as a percentage with one decimal, without the % sign."""
    return "--" if math.isnan(value) else f"{100 * value:.1f}"


def days(value: float | None) -> str:
    """A number of days, with a LaTeX minus sign when negative."""
    if value is None or math.isnan(value):
        return "--"
    text = f"{value:,.0f}"
    return "$-$" + text[1:] if text.startswith("-") else text


def load(data: Path) -> dict[str, Any]:
    """Every input, parsed. Raises MissingInputs naming each file that is missing."""
    missing = [name for name in INPUTS if not (data / name).exists()]
    if missing:
        raise MissingInputs("\n".join(f"  {data / name}  <- {INPUTS[name]}" for name in missing))
    out: dict[str, Any] = {}
    for name in INPUTS:
        if name.endswith(".stats.json"):
            out[name.removesuffix(".stats.json")] = json.loads((data / name).read_text("utf-8"))
    out["timing_rows"] = list(read_jsonl(data / "timing.jsonl"))
    out["robustness"] = json.loads((data / "robustness.json").read_text("utf-8"))
    return out


def dataset(paper: Paper, inputs: dict[str, Any]) -> None:
    """How the dataset was built: mining and filtering."""
    mining, labels = inputs["candidates"], inputs["labeled"]
    paper.put("MiningStart", mining["start"])
    paper.put("MiningEnd", mining["end"])
    paper.count("ModelIds", mining["model_ids"])
    paper.count("Searches", mining["queries"])
    paper.count("ResultsSeen", mining["items_seen"])
    paper.count("TruncatedWindows", len(mining["truncated_windows"]))
    paper.count("FailedWindows", len(mining["failed_windows"]))
    paper.count("Candidates", labels["candidates"])
    paper.count("WithMigrationWord", labels["with_migration_word"])
    paper.count("KimMigration", labels["migration"])
    paper.count("KimMigrationWithAI", labels["migration_with_ai"])
    paper.count("MigrationsAway", labels["migration_away"])
    paper.count("KimCommits", KIM["commits"])
    paper.count("KimRepos", KIM["repos"])

    rows = [
        ("Model IDs searched (with aliases)", mining["model_ids"]),
        ("Searches", mining["queries"]),
        ("Search results seen", mining["items_seen"]),
        ("Candidate commits (one per SHA)", labels["candidates"]),
        ("with a migration word", labels["with_migration_word"]),
        ("not a move into the model", labels["not_into"]),
        ("not more than 30 days before the notice", labels["not_before_notice"]),
        ("not from a bot", labels["not_bot"]),
        ("Kim's rules (\\texttt{migration})", labels["migration"]),
        ("Moves away from the model (\\texttt{migration\\_away})", labels["migration_away"]),
    ]
    body = "\n".join(f"{text} & {value:,} \\\\" for text, value in rows)
    paper.tables["dataset.tex"] = tabular("lr", "Step & Commits", body)


def validation(paper: Paper, data: Path) -> None:
    """How good the labels, the targets and the file kinds are."""
    v2 = data / "validation_v2_adjudicated"
    labels = filter_score.read_labels(v2 / "sample.csv")
    key = filter_score.read_key(v2 / "sample_key.csv")
    strata = json.loads((v2 / "strata.json").read_text("utf-8"))
    _, kept, missed_strata = filter_score.DESIGNS[strata.get("design", "v1")]
    scores = filter_score.score_strata(labels, key, strata["population"])
    away = scores[kept[0]]
    paper.share("Precision", away.yes, away.labelled)
    paper.count("PrecisionRows", away.labelled)
    precision, _ = filter_score.weighted_precision(scores, kept)
    true_kept = precision * sum(scores[s].population for s in kept)
    missed = sum(scores[s].share * scores[s].population for s in missed_strata)
    recall = true_kept / (true_kept + missed) if true_kept + missed else math.nan
    paper.put("Recall", pct(recall), recall)
    paper.put("RealMigrations", f"{round(true_kept, -2):,.0f}", true_kept)
    kappa, shared = cohen_kappa(labels, filter_score.read_labels(v2 / "sample_b.csv"))
    paper.put("FilterKappa", f"{kappa:.2f}", kappa)
    paper.count("FilterKappaRows", shared)

    with (v2 / "targets_check.csv").open(newline="", encoding="utf-8") as f:
        verdicts = Counter(row["verdict"] for row in csv.DictReader(f))
    n = sum(verdicts.values()) - verdicts["hand_not_model"]
    right = verdicts["match"] + verdicts["agree_none"]
    named = sum(
        verdicts[v] for v in ("match", "wrong_same_provider", "wrong_other_provider", "extra")
    )
    paper.share("TargetCheck", right, n)
    paper.count("TargetCheckRows", n)
    paper.share("TargetNamedRight", verdicts["match"], named)
    paper.count("TargetNamedRows", named)
    paper.share("TargetNamedProvider", verdicts["match"] + verdicts["wrong_same_provider"], named)
    good, total, _ = RECORDED["TargetCheckBefore"]
    paper.share("TargetCheckBefore", good, total)
    paper.count("TargetCheckBeforeRows", total)

    sheet = data / "validation_files"
    hand = files_check.read_hand(sheet / "sample.csv")
    frozen = files_check.read_key(sheet / "sample_key.csv")
    current = files_check.read_current(data / "files.jsonl", sheet / "sample_key.csv")
    paper.count("FileCheckRows", len(hand["has_test"]))
    for question, name in (("has_test", "Test"), ("has_eval", "Eval")):
        for when, code in (("Before", frozen), ("After", current)):
            c = files_check.compare(hand[question], code[question])
            paper.share(f"FileCheck{name}{when}", c["agree"], c["n"])
            paper.put(f"FileCheck{name}{when}Kappa", f"{c['kappa']:.2f}", c["kappa"])
            paper.count(f"FileCheck{name}{when}Found", c["both_yes"])
        hand_yes = sum(answer == "yes" for answer in hand[question].values())
        paper.count(f"FileCheck{name}HandYes", hand_yes)
        paper.share(f"FileHand{name}", hand_yes, len(hand[question]))

    def row(text: str, prefix: str, n: str, kappa: str = "--") -> str:
        p = paper.numbers
        return (
            f"{text} & {p[n]} & {p[prefix]}\\% & {p[prefix + 'Low']}--{p[prefix + 'High']} "
            f"& {kappa} \\\\"
        )

    p = paper.numbers
    lines = [
        row("Migration label: precision", "Precision", "PrecisionRows"),
        f"Migration label: second rater & {p['FilterKappaRows']} & & & {p['FilterKappa']} \\\\",
        "\\midrule",
        row("Target: same as hand (before tuning)", "TargetCheckBefore", "TargetCheckBeforeRows"),
        row("Target: same as hand", "TargetCheck", "TargetCheckRows"),
        row("Target named by the code: right model", "TargetNamedRight", "TargetNamedRows"),
        "\\midrule",
    ]
    for name, text in (("Test", "touches a test"), ("Eval", "touches an evaluation")):
        for when in ("Before", "After"):
            lines.append(
                row(
                    f"File {text} ({when.lower()} the fix)",
                    f"FileCheck{name}{when}",
                    "FileCheckRows",
                    p[f"FileCheck{name}{when}Kappa"],
                )
            )
    paper.tables["validation.tex"] = tabular(
        "lrrrr", "Check & Rows & Agreement & 95\\% CI & $\\kappa$", "\n".join(lines)
    )


def timing(paper: Paper, inputs: dict[str, Any]) -> None:
    """RQ1: how many migrations come after the shutdown, next to Kim's 82%."""
    share, low, high = KIM["after_shutdown"]
    paper.put("KimAfterShutdown", str(share), share / 100)
    paper.put("KimAfterShutdownLow", str(low), low / 100)
    paper.put("KimAfterShutdownHigh", str(high), high / 100)
    variants = (
        ("All", "timing", "exact_dates", "All migrations"),
        ("Late", "timing_90d", "exact_dates", "Shut down at least 90 days before the data ends"),
        ("Window", "timing_90d", "exact_dates_kim_window", "Same, from 30 days before the notice"),
        ("First", "timing_90d", "exact_dates_first_per_repo", "Same, first per repository"),
        ("Google", "timing_90d", "google_earliest_dates", "Google (earliest dates)"),
    )
    lines = []
    for name, source, key, text in variants:
        h = inputs[source]["headline"][key]
        paper.share(f"After{name}", h["after"], h["total"])
        paper.count(f"After{name}Total", h["total"])
        p = paper.numbers
        lines.append(
            f"{text} & {h['after']:,} of {h['total']:,} & {p[f'After{name}']}\\% "
            f"& {p[f'After{name}Low']}--{p[f'After{name}High']} \\\\"
        )
    paper.put("RetiredBy", inputs["timing_90d"]["retired_by"])
    lines.append("\\midrule")
    lines.append(f"Kim (2026) & & {share}\\% & {low}--{high} \\\\")
    paper.tables["timing.tex"] = tabular(
        "lrrr", "Migrations counted & After the shutdown & Share & 95\\% CI", "\n".join(lines)
    )


def lag(paper: Paper, inputs: dict[str, Any]) -> None:
    """RQ2: how many days before or after the shutdown projects migrate."""
    stats = inputs["lag"]
    names = {"openai+anthropic": "Exact", "anthropic": "Anthropic", "openai": "OpenAI"}
    names["google"] = "Google"
    lines = []
    for group, name in names.items():
        g = stats["groups"].get(group)
        if g is None:
            continue
        for part, short in (
            ("days_from_shutdown", "Days"),
            ("first_per_repo", "FirstDays"),
            ("after_shutdown", "LateDays"),
        ):
            s = g[part]
            paper.put(f"{name}{short}", days(s["median"]), s["median"])
            paper.put(f"{name}{short}Low", days(s["median_low"]), s["median_low"])
            paper.put(f"{name}{short}High", days(s["median_high"]), s["median_high"])
            paper.put(f"{name}{short}QOne", days(s["q1"]), s["q1"])
            paper.put(f"{name}{short}QThree", days(s["q3"]), s["q3"])
        used = g["notice_used"]["median"]
        used_text = "--" if used is None else pct(used)
        paper.put(f"{name}NoticeUsed", used_text, used)
        total = sum(g["windows"].values())
        peak = max(g["windows"], key=lambda w: g["windows"][w])
        paper.put(f"{name}PeakWindow", peak)
        paper.share(f"{name}PeakShare", g["windows"][peak], total)
        s = g["days_from_shutdown"]
        late = g["after_shutdown"]
        lines.append(
            f"{NAMES[group]} & {s['n']:,} & {days(s['median'])} "
            f"({days(s['median_low'])} to {days(s['median_high'])}) "
            f"& {days(s['q1'])} to {days(s['q3'])} & {days(late['median'])} "
            f"& {used_text}{'' if used is None else chr(92) + '%'} \\\\"
        )
    paper.tables["lag.tex"] = tabular(
        "lrrrrr",
        "Provider & Migrations & Median days (95\\% CI) & Quartiles & Median if late & Notice used",
        "\n".join(lines),
    )
    paper.figures["lag-windows.pdf"] = windows_figure(stats)
    retired_by = stats["retired_by"]
    rows = [r for r in inputs["timing_rows"] if r["shutdown"] <= retired_by]
    paper.figures["lag-ecdf.pdf"] = ecdf_figure(rows)


def targets(paper: Paper, inputs: dict[str, Any]) -> None:
    """RQ3: what projects migrate to."""
    stats = inputs["targets"]
    rows = stats["rows"]
    every = stats["destinations"]["all"]
    found = rows - every["no target"]
    paper.count("TargetRows", rows)
    paper.share("TargetFound", found, rows)
    paper.share("SameProvider", every["same provider"], found)
    paper.share("OpenOrOther", every["open or other"], found)
    other_big = sum(every[p] for p in PROVIDERS)
    paper.share("OtherBigProvider", other_big, found)
    follows = stats["follows"]["all"]
    paper.share("FollowsExact", follows["exact"], found)
    paper.share("FollowsLine", follows["exact"] + follows["same_line"], found)
    paper.share("TargetOnList", stats["target_retired_list"], found)
    paper.share("TargetAnnounced", stats["target_announced_before"], found)
    paper.share("TargetShutDown", stats["target_shut_down_before"], found)
    paper.share("TargetShutDownEarlier", stats.get("target_shut_down_earlier", 0), found)
    generation = stats["generation_change"]
    paper.share("GenerationUp", generation.get("up", 0), found)
    paper.share("GenerationDown", generation.get("down", 0), found)
    tier = stats["tier_change"]
    paper.share("TierDown", tier.get("down", 0), found)
    paper.share("TierUp", tier.get("up", 0), found)
    ai, total = stats["ai_assisted"]["all with a target"]
    paper.share("AIAssisted", ai, total)
    for group, name in (("generation down", "Down"), ("generation up", "Up")):
        ai, total = stats["ai_assisted"][group]
        paper.share(f"AIAssistedGeneration{name}", ai, total)

    columns = [c for c in (*PROVIDERS, "all") if c in stats["follows"]]
    header = "Target & " + " & ".join(NAMES[c] for c in columns)
    kinds = (
        ("exact", "The provider's recommended replacement"),
        ("same_line", "A newer model of the recommended line"),
        ("other", "Another model"),
        ("none_listed", "Another model (no replacement listed)"),
        ("no_target", "No target named"),
    )
    lines = []
    for key, text in kinds:
        cells = []
        for c in columns:
            column = stats["follows"][c]
            whole = sum(column.values())
            cells.append(f"{pct(column[key] / whole) if whole else '--'}\\%")
        lines.append(f"{text} & " + " & ".join(cells) + " \\\\")
    totals = [f"{sum(stats['follows'][c].values()):,}" for c in columns]
    lines.append("\\midrule")
    lines.append("Migrations & " + " & ".join(totals) + " \\\\")
    paper.tables["targets.tex"] = tabular("l" + "r" * len(columns), header, "\n".join(lines))

    pairs = [
        f"\\texttt{{{tt(a)}}} & \\texttt{{{tt(b)}}} & {n:,} \\\\"
        for a, b, n in stats["top_pairs"][:10]
    ]
    paper.tables["top-switches.tex"] = tabular("llr", "From & To & Commits", "\n".join(pairs))
    paper.figures["targets.pdf"] = targets_figure(stats, columns, kinds)


RQ4_MEASURES = (
    ("touches a test file", "TouchTest"),
    ("adds a test file", "AddTest"),
    ("changes a test that names a model", "TestNamesModel"),
    ("touches an evaluation file", "TouchEval"),
    ("adds an evaluation file", "AddEval"),
    ("touches a test or evaluation file", "TouchTestOrEval"),
    ("touches a prompt file", "TouchPrompt"),
    ("pure ID swap (diffs known)", "IdSwap"),
)


def changed_files(paper: Paper, inputs: dict[str, Any]) -> None:
    """RQ4: do migrations come with tests or evaluations?"""
    stats = inputs["files"]
    paper.count("FilesSample", stats["sampled"])
    paper.count("FilesFound", stats["found"])
    paper.put("FilesSeed", str(stats["seed"]), stats["seed"])
    paper.put("FilesMedian", f"{stats['median_files']:g}", stats["median_files"])
    paper.count("KimFileLevel", KIM["file_level"])
    paper.put("KimTouchTest", str(KIM["touch_test"]), KIM["touch_test"] / 100)
    paper.put("KimMentionEval", str(KIM["mention_eval"]), KIM["mention_eval"] / 100)
    lines = []
    for measure, name in RQ4_MEASURES:
        r = stats["rates"][measure]
        paper.share(name, r["yes"], r["n"])
        p = paper.numbers
        kim = {"TouchTest": f"{KIM['touch_test']}\\%"}.get(name, "")
        lines.append(
            f"{measure[0].upper() + measure[1:]} & {r['yes']:,} of {r['n']:,} & {p[name]}\\% "
            f"& {p[name + 'Low']}--{p[name + 'High']} & {kim} \\\\"
        )
    for group, name in (("AI-assisted", "AI"), ("not AI-assisted", "NotAI")):
        for measure, short in (
            ("touches a test file", "TouchTest"),
            ("touches a test or evaluation file", "TouchTestOrEval"),
        ):
            r = stats["by_ai"][group][measure]
            paper.share(f"{name}{short}", r["yes"], r["n"])
    paper.tables["changed-files.tex"] = tabular(
        "lrrrr", "Migration commit & Commits & Share & 95\\% CI & Kim", "\n".join(lines)
    )
    paper.figures["changed-files.pdf"] = rq4_figure(stats)


# Robustness rows: key in robustness.json, command name, text in the table.
ROBUST_ROWS = (
    (("labels", "kim_label"), "KimLabel", "Kim's rules (\\texttt{migration})"),
    (("labels", "strict"), "Strict", "Strict rules (\\texttt{migration\\_strict})"),
    (("labels", "no_ai"), "NoAI", "Without AI-assisted commits"),
    (("incomplete", "exact"), "Complete", "Without models searched incompletely"),
)


def robustness(paper: Paper, inputs: dict[str, Any]) -> None:
    """Checks of RQ1 and RQ2 against a reviewer's objections (ADR 0021)."""
    r = inputs["robustness"]
    head = r["labels"]["headline"]
    expected = inputs["timing_90d"]["headline"]["exact_dates"]
    if (head["rows"], head["after"]) != (expected["total"], expected["after"]):
        raise OutOfDate(
            "robustness.json does not match timing_90d.stats.json. Run again:\n"
            "  uv run python -m research.analysis.robustness"
        )

    def spread(s: dict[str, Any]) -> str:
        return f"{days(s['median_days'])} ({days(s['median_low'])} to {days(s['median_high'])})"

    def line(text: str, s: dict[str, Any], low: float, high: float, median: str) -> str:
        return (
            f"{text} & {s['rows']:,} & {pct(known(s['share']))}\\% & {pct(low)}--{pct(high)} "
            f"& {median} \\\\"
        )

    boot = r["repo_bootstrap"]
    paper.put("AfterLateRepoLow", pct(boot["share_low"]), boot["share_low"])
    paper.put("AfterLateRepoHigh", pct(boot["share_high"]), boot["share_high"])
    paper.put("ExactDaysRepoLow", days(boot["median_low"]), boot["median_low"])
    paper.put("ExactDaysRepoHigh", days(boot["median_high"]), boot["median_high"])
    paper.count("BootReps", boot["reps"])
    paper.count("BootRepos", boot["repos"])
    repo_median = (
        f"{days(head['median_days'])} ({days(boot['median_low'])} to {days(boot['median_high'])})"
    )
    lines = [
        line(
            "\\texttt{migration\\_away}, as in RQ1",
            head,
            head["low"],
            head["high"],
            spread(head),
        ),
        line(
            "same, intervals by repository",
            head,
            boot["share_low"],
            boot["share_high"],
            repo_median,
        ),
        line(
            "First per repository and model",
            r["first_per_repo"],
            r["first_per_repo"]["low"],
            r["first_per_repo"]["high"],
            spread(r["first_per_repo"]),
        ),
    ]
    for (group, key), name, text in ROBUST_ROWS:
        s = r[group][key]
        paper.share(f"After{name}", s["after"], s["rows"])
        paper.count(f"After{name}Total", s["rows"])
        paper.put(f"{name}Days", days(s["median_days"]), s["median_days"])
        lines.append(line(text, s, s["low"], s["high"], spread(s)))
    incomplete = r["incomplete"]
    paper.count("IncompleteModels", len(incomplete["models"]))
    paper.count("IncompleteExactRows", head["rows"] - incomplete["exact"]["rows"])
    lines.append("\\midrule")
    for key, name, text in (
        ("google", "", "Google (earliest dates)"),
        ("google_without", "GoogleComplete", "Google, without models searched incompletely"),
    ):
        s = incomplete[key]
        if name:
            paper.share(f"After{name}", s["after"], s["rows"])
            paper.count(f"After{name}Total", s["rows"])
        if s["rows"]:
            lines.append(line(text, s, s["low"], s["high"], spread(s)))
    paper.tables["robustness.tex"] = tabular(
        "lrrrr",
        "Migrations counted & Migrations & After the shutdown & 95\\% CI & Median days (95\\% CI)",
        "\n".join(lines),
    )

    hand = r["hand"]
    for key, name in (
        ("precision_after", "PrecisionAfter"),
        ("precision_before", "PrecisionBefore"),
    ):
        paper.share(name, hand[key]["yes"], hand[key]["rows"])
        paper.count(f"{name}Rows", hand[key]["rows"])
    paper.share("SampleLabelAfter", hand["label_after"]["after"], hand["label_after"]["rows"])
    paper.share("SampleMissedAfter", hand["missed_after"]["after"], hand["missed_after"]["rows"])
    paper.count("SampleMissedRows", hand["missed_after"]["rows"])
    true_after = hand["true_after"]
    for suffix, field_name in (("", "share"), ("Low", "low"), ("High", "high")):
        value = true_after[field_name]
        paper.put(f"SampleTrueAfter{suffix}", pct(known(value)), value)

    for key, name in (("all", "All"), ("after_shutdown", "Late"), ("first_per_repo", "First")):
        t = r["providers"][key]
        paper.put(f"Cliff{name}", signed(t["delta"]), t["delta"])
        paper.put(f"Cliff{name}Size", t["size"] or "--")
        paper.put(f"Cliff{name}P", p_value(t["p"]), t["p"])
        paper.put(f"Cliff{name}Z", signed(t["z"]), t["z"])


def known(value: float | None) -> float:
    """``value``, with None (unknown in the JSON file) as NaN."""
    return math.nan if value is None else value


def signed(value: float | None) -> str:
    """A number with two decimals and a LaTeX minus sign."""
    if value is None or math.isnan(value):
        return "--"
    return f"{value:.2f}".replace("-", "$-$")


def p_value(p: float | None) -> str:
    """A p-value as the paper writes it."""
    if p is None or math.isnan(p):
        return "--"
    return "$<$0.001" if p < 0.001 else f"{p:.3f}"


# ---------------------------------------------------------------- LaTeX output


def tt(text: str) -> str:
    """``text`` safe inside \\texttt."""
    return text.replace("\\", "\\textbackslash{}").replace("_", "\\_").replace("&", "\\&")


def tabular(columns: str, header: str, body: str) -> str:
    """A booktabs tabular."""
    return (
        f"\\begin{{tabular}}{{{columns}}}\n\\toprule\n{header} \\\\\n\\midrule\n"
        f"{body}\n\\bottomrule\n\\end{{tabular}}\n"
    )


def numbers_tex(paper: Paper) -> str:
    lines = [
        "% Generated by research.analysis.paper. Do not edit: run the script again.",
        *(f"\\newcommand{{\\{name}}}{{{text}}}" for name, text in sorted(paper.numbers.items())),
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------- figures


def style(ax: Any) -> None:
    """Recessive axes and grid."""
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(MUTED)
    ax.tick_params(colors=MUTED, labelcolor=INK, labelsize=8)
    ax.grid(axis="y", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def new_figure(width: float = 6.0, height: float = 2.8) -> tuple[Figure, Any]:
    figure, ax = plt.subplots(figsize=(width, height), layout="constrained")
    style(ax)
    return figure, ax


def windows_figure(stats: dict[str, Any]) -> Figure:
    """Share of migrations in each window around the shutdown, per group."""
    figure, ax = new_figure()
    names = [name for name, _, _ in WINDOWS]
    groups = [g for g in ("openai+anthropic", "google") if g in stats["groups"]]
    width = 0.8 / max(len(groups), 1)
    colors = {"openai+anthropic": COLORS["openai"], "google": COLORS["google"]}
    for i, group in enumerate(groups):
        counts = stats["groups"][group]["windows"]
        total = sum(counts.values()) or 1
        xs = [j + (i - (len(groups) - 1) / 2) * width for j in range(len(names))]
        ax.bar(
            xs,
            [100 * counts[n] / total for n in names],
            width=width * 0.92,
            color=colors[group],
            label=NAMES[group],
        )
    shutdown = names.index("0 to 30 days after") - 0.5
    ax.axvline(shutdown, color=INK, linewidth=0.8, linestyle="--")
    # Above the plot, so it never sits on a bar (x in data units, y in axes units).
    ax.text(
        shutdown,
        1.01,
        "shutdown",
        transform=ax.get_xaxis_transform(),
        fontsize=7,
        color=MUTED,
        ha="center",
        va="bottom",
    )
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels([short_window(n) for n in names], fontsize=7)
    ax.set_xlabel("Days before (left) and after (right) the shutdown", fontsize=8)
    ax.set_ylabel("Share of migrations (%)", fontsize=8)
    # Above the plot too, on the right, so it never covers a bar.
    ax.legend(frameon=False, fontsize=8, ncol=2, loc="lower right", bbox_to_anchor=(1, 1))
    return figure


def short_window(name: str) -> str:
    """A window's name for an axis: "91 to 180 days before" -> "91-180", with an en dash."""
    for long, short in (
        ("more than ", ">"),
        (" to ", "\u2013"),
        (" days before", ""),
        (" days after", ""),
    ):
        name = name.replace(long, short)
    return name


def ecdf_figure(rows: Sequence[dict[str, Any]]) -> Figure:
    """Cumulative share of migrations by days from the shutdown, per provider."""
    figure, ax = new_figure()
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    for provider in PROVIDERS:
        values = sorted(r["days_from_shutdown"] for r in rows if r["provider"] == provider)
        if not values:
            continue
        n = len(values)
        ax.step(
            values,
            [100 * (i + 1) / n for i in range(n)],
            where="post",
            color=COLORS[provider],
            linewidth=1.6,
            label=f"{NAMES[provider]} ({n:,})",
        )
    ax.axvline(0, color=INK, linewidth=0.8, linestyle="--")
    ax.set_xlim(-365, 730)
    ax.set_ylim(0, 100)
    ax.set_xlabel("Days from the shutdown (commit day minus shutdown day)", fontsize=8)
    ax.set_ylabel("Migrations so far (%)", fontsize=8)
    ax.legend(frameon=False, fontsize=8, loc="lower right")
    return figure


def targets_figure(
    stats: dict[str, Any], columns: Sequence[str], kinds: Sequence[tuple[str, str]]
) -> Figure:
    """For each provider, how the targets relate to the recommended replacement."""
    figure, ax = new_figure(height=2.2)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    colors = ["#2a78d6", "#86b6ef", "#eda100", "#f3cf7a", "#c9c8c3"]
    labels = [NAMES[c] for c in columns]
    left = [0.0] * len(columns)
    for (key, text), color in zip(kinds, colors, strict=True):
        shares = []
        for c in columns:
            column = stats["follows"][c]
            whole = sum(column.values()) or 1
            shares.append(100 * column[key] / whole)
        ax.barh(
            labels,
            shares,
            left=left,
            color=color,
            label=text,
            edgecolor="white",
            linewidth=1,
        )
        left = [a + b for a, b in zip(left, shares, strict=True)]
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xlabel("Share of migrations (%)", fontsize=8)
    ax.legend(frameon=False, fontsize=6.5, ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.3))
    return figure


def rq4_figure(stats: dict[str, Any]) -> Figure:
    """Share of migration commits with each property, with 95% intervals."""
    figure, ax = new_figure(height=2.6)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    measures = [m for m, _ in RQ4_MEASURES]
    ys = list(range(len(measures)))
    for y, measure in zip(ys, measures, strict=True):
        r = stats["rates"][measure]
        share = 100 * r["yes"] / r["n"] if r["n"] else math.nan
        ax.plot([100 * r["low"], 100 * r["high"]], [y, y], color=COLORS["openai"], linewidth=2)
        ax.plot([share], [y], "o", color=COLORS["openai"], markersize=5)
    ax.plot([], [], "o", color=COLORS["openai"], markersize=5, label="This study, 95% CI")
    ax.plot(
        [KIM["touch_test"]],
        [0.35],
        "D",
        markerfacecolor="white",
        markeredgecolor=INK,
        markersize=5,
        label="Kim (2026)",
    )
    ax.set_yticks(ys)
    ax.set_yticklabels([m[0].upper() + m[1:] for m in measures], fontsize=7)
    ax.invert_yaxis()
    ax.set_xlim(0, max(40, 5 + max(100 * stats["rates"][m]["high"] for m in measures)))
    ax.set_xlabel("Share of migration commits (%)", fontsize=8)
    ax.legend(frameon=False, fontsize=7, ncol=2, loc="upper center", bbox_to_anchor=(0.5, -0.25))
    return figure


# ------------------------------------------------------------------------ run


def build(data: Path) -> Paper:
    """Every number, table and figure."""
    inputs = load(data)
    paper = Paper()
    dataset(paper, inputs)
    validation(paper, data)
    timing(paper, inputs)
    lag(paper, inputs)
    targets(paper, inputs)
    changed_files(paper, inputs)
    robustness(paper, inputs)
    return paper


def write(paper: Paper, out: Path) -> None:
    """Write the numbers, tables and figures under ``out``."""
    (out / "tables").mkdir(parents=True, exist_ok=True)
    (out / "figures").mkdir(parents=True, exist_ok=True)
    (out / "numbers.tex").write_text(numbers_tex(paper), encoding="utf-8")
    raw = {k: None if isinstance(v, float) and math.isnan(v) else v for k, v in paper.raw.items()}
    (out / "numbers.json").write_text(
        json.dumps(dict(sorted(raw.items())), indent=2) + "\n", encoding="utf-8"
    )
    for name, text in paper.tables.items():
        (out / "tables" / name).write_text(text, encoding="utf-8")
    plt.rcParams["pdf.fonttype"] = 42  # embed TrueType fonts, as journals ask
    for name, figure in paper.figures.items():
        figure.savefig(out / "figures" / name, metadata={"CreationDate": None})
        plt.close(figure)


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=Path, default=Path("research/data"))
    parser.add_argument("--out", type=Path, default=Path("paper/generated"))
    args = parser.parse_args(argv)
    try:
        paper = build(args.data)
    except MissingInputs as missing:
        print(f"Missing inputs (file <- what makes it):\n{missing}", file=sys.stderr)
        return 1
    except OutOfDate as stale:
        print(stale, file=sys.stderr)
        return 1
    write(paper, args.out)
    print(f"Written to {args.out}/ on {date.today().isoformat()}:")
    print(f"  numbers.tex and numbers.json: {len(paper.numbers)} numbers")
    print(f"  tables/: {', '.join(sorted(paper.tables))}")
    print(f"  figures/: {', '.join(sorted(paper.figures))}")
    p = paper.numbers
    print("\nKey numbers, to check against the earlier outputs:")
    for name, text in (
        ("MigrationsAway", "migration_away commits"),
        ("Precision", "precision of migration_away (%)"),
        ("AfterLate", "after the shutdown, 90-day rule (%)"),
        ("ExactDays", "median days from the shutdown"),
        ("TargetFound", "target found (%)"),
        ("FollowsLine", "follows the recommended line (%)"),
        ("TouchTest", "touches a test file (%)"),
        ("TouchEval", "touches an evaluation file (%)"),
        ("AfterKimLabel", "after the shutdown, Kim's label (%)"),
        ("CliffAll", "Cliff's delta, OpenAI against Anthropic"),
    ):
        print(f"  \\{name:<20}{p.get(name, '--'):>10}  {text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
