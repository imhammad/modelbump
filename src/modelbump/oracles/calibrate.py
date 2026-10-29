"""Check the judge against people, and correct pass rates for its mistakes (ADR 0055).

1. :func:`make_sheet` draws judged answers from a ``modelbump test --format json``
   report, half where the judge said PASS and half where it said FAIL, and
   writes a blind CSV: the prompt, the reference and the answer, with no model
   name and no judge verdict. A key file keeps what the sheet hides.
2. A person fills in ``your_label`` (PASS or FAIL) for each row.
3. :func:`agreement` reads both files. Because the sample is drawn by judge
   verdict, it estimates, for each verdict, how often the person agrees:
   the judge's precision on PASS (``P(person PASS | judge PASS)``) and on FAIL.
   With how often the judge said PASS for each model in the whole report,
   that gives each model's pass rate as a person would have scored it:
   ``P(judge PASS) * agree_on_pass + P(judge FAIL) * (1 - agree_on_fail)``.

This assumes the judge's mistakes, given its verdict, do not depend on which
model wrote the answer. The report shows the agreement per model so the
assumption can be checked.
"""

import csv
import json
import random
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from modelbump.stats import Interval, wilson_interval

KEY_VERSION = 1
DEFAULT_SIZE = 200
DEFAULT_SEED = 2030
SHEET_COLUMNS = ("item", "prompt", "reference", "answer", "your_label", "note")
_YES = {"pass", "p", "yes", "y", "1", "ok"}
_NO = {"fail", "f", "no", "n", "0"}


@dataclass(frozen=True, slots=True)
class Judged:
    """One judged answer from a report."""

    case: str
    model: str
    sample: int
    text: str
    judge: str


@dataclass(frozen=True, slots=True)
class Sheet:
    """What :func:`make_sheet` wrote."""

    rows: int
    answers: int
    """Sampled answers; equal answers to the same case share one row."""
    drawn: Counter[str]
    """Sampled answers per judge verdict."""
    available: Counter[str]
    """Judged answers in the report per judge verdict."""


def _prompt_text(messages: Sequence[Any]) -> str:
    return "\n\n".join(f"[{m['role']}]\n{m['content']}" for m in messages)


def read_report(path: Path) -> tuple[dict[str, Any], list[Judged]]:
    """The report and every answer the judge gave a PASS or FAIL."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1 or "cases" not in data:
        raise ValueError(f"{path} is not a `modelbump test --format json` report")
    if any("reference_answer" not in case for case in data["cases"]):
        raise ValueError(f"{path} is from an older ModelBump; run `modelbump test` again")
    if not data.get("judge"):
        raise ValueError(f"{path} was run without a judge (--no-judge or no free-text cases)")
    judged = [
        Judged(case["id"], answer["model"], answer["sample"], answer["text"], answer["judge"])
        for case in data["cases"]
        for answer in case["answers"]
        if answer.get("judge") in ("PASS", "FAIL")
    ]
    return data, judged


def make_sheet(
    report: Path,
    sheet: Path,
    key: Path,
    size: int = DEFAULT_SIZE,
    seed: int = DEFAULT_SEED,
) -> Sheet:
    """Write the blind sheet and its key. Returns what was drawn."""
    if size < 2:
        raise ValueError(f"size must be at least 2, got {size}")
    data, judged = read_report(report)
    cases = {case["id"]: case for case in data["cases"]}
    rng = random.Random(seed)
    by_verdict = {v: [j for j in judged if j.judge == v] for v in ("PASS", "FAIL")}
    available = Counter({v: len(items) for v, items in by_verdict.items()})
    # Half from each verdict; when one runs short, the other fills the rest.
    want = {"PASS": size // 2, "FAIL": size - size // 2}
    short = {v: max(0, want[v] - available[v]) for v in want}
    want = {"PASS": want["PASS"] + short["FAIL"], "FAIL": want["FAIL"] + short["PASS"]}
    drawn: list[Judged] = []
    for verdict, items in by_verdict.items():
        drawn.extend(rng.sample(items, min(want[verdict], len(items))))
    # One row per distinct (case, answer text); the key lists every answer it stands for.
    rows: dict[tuple[str, str], list[Judged]] = {}
    for item in drawn:
        rows.setdefault((item.case, item.text), []).append(item)
    order = list(rows)
    rng.shuffle(order)
    with sheet.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(SHEET_COLUMNS)
        for number, (case, text) in enumerate(order, start=1):
            writer.writerow(
                [
                    number,
                    _prompt_text(cases[case]["messages"]),
                    cases[case]["reference_answer"],
                    text,
                    "",
                    "",
                ]
            )
    population = Counter(f"{j.model} {j.judge}" for j in judged)
    key_data = {
        "version": KEY_VERSION,
        "report": str(report),
        "judge": data["judge"],
        "judge_version": data.get("judge_version", ""),
        "old": data["old"],
        "new": data["new"],
        "seed": seed,
        "population": dict(sorted(population.items())),
        "items": [
            {
                "item": number,
                "case": case,
                "answers": [
                    {"model": j.model, "sample": j.sample, "judge": j.judge}
                    for j in rows[(case, text)]
                ],
            }
            for number, (case, text) in enumerate(order, start=1)
        ],
    }
    key.write_text(json.dumps(key_data, indent=2) + "\n", encoding="utf-8")
    return Sheet(len(order), len(drawn), Counter(j.judge for j in drawn), available)


def parse_label(text: str) -> bool | None:
    """A person's label: True for PASS, False for FAIL, None for blank."""
    value = text.strip().lower()
    if not value:
        return None
    if value in _YES:
        return True
    if value in _NO:
        return False
    raise ValueError(f"label {text!r} is not PASS or FAIL")


@dataclass(frozen=True, slots=True)
class Rate:
    """Agreeing answers out of answers, with a 95% interval."""

    agree: int
    total: int

    @property
    def value(self) -> float:
        return self.agree / self.total if self.total else float("nan")

    @property
    def interval(self) -> Interval | None:
        return wilson_interval(self.agree, self.total, alpha=0.025) if self.total else None


@dataclass(frozen=True, slots=True)
class ModelRate:
    """One model's pass rate, by the judge and corrected to a person's view."""

    model: str
    judged_pass: float
    corrected: float
    low: float
    high: float


@dataclass(frozen=True, slots=True)
class Agreement:
    labelled: int
    """Labelled answers (a row counts once per answer it stands for)."""
    unlabelled_rows: int
    on_pass: Rate
    """Of answers the judge PASSed, how many the person PASSed."""
    on_fail: Rate
    """Of answers the judge FAILed, how many the person FAILed."""
    per_model: dict[str, tuple[Rate, Rate]]
    kappa: float
    """Cohen's kappa on the sheet (judge-stratified, so it is not a population number)."""
    overall: float
    """How often judge and person agree on the report's answers, weighted back."""
    rates: tuple[ModelRate, ...]


def _kappa(pairs: Sequence[tuple[bool, bool]]) -> float:
    n = len(pairs)
    if n == 0:
        return float("nan")
    observed = sum(a == b for a, b in pairs) / n
    judge_pass = sum(a for a, _ in pairs) / n
    person_pass = sum(b for _, b in pairs) / n
    expected = judge_pass * person_pass + (1 - judge_pass) * (1 - person_pass)
    return (observed - expected) / (1 - expected) if expected < 1 else 1.0


def agreement(sheet: Path, key: Path) -> Agreement:
    """Compare the person's labels with the judge, and correct each model's pass rate."""
    key_data = json.loads(key.read_text(encoding="utf-8"))
    if key_data.get("version") != KEY_VERSION:
        raise ValueError(f"{key} is not a version {KEY_VERSION} judge key")
    items = {int(item["item"]): item for item in key_data["items"]}
    with sheet.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = {"item", "your_label"} - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"{sheet} has no {', '.join(sorted(missing))} column")
        labels: dict[int, bool | None] = {}
        for row in reader:
            if not (row.get("item") or "").strip():
                continue
            number = int(row["item"])
            if number not in items:
                raise ValueError(f"row {number} is not in {key}")
            try:
                labels[number] = parse_label(row.get("your_label") or "")
            except ValueError as error:
                raise ValueError(f"row {number}: {error}") from error
    pairs: list[tuple[bool, bool, str]] = []  # (judge PASS, person PASS, model)
    for number, label in labels.items():
        if label is None:
            continue
        for answer in items[number]["answers"]:
            pairs.append((answer["judge"] == "PASS", label, answer["model"]))
    if not pairs:
        raise ValueError(f"{sheet} has no labels yet")

    def rates(subset: Sequence[tuple[bool, bool, str]]) -> tuple[Rate, Rate]:
        on_pass = [p for j, p, _ in subset if j]
        on_fail = [p for j, p, _ in subset if not j]
        return Rate(sum(on_pass), len(on_pass)), Rate(len(on_fail) - sum(on_fail), len(on_fail))

    on_pass, on_fail = rates(pairs)
    population = Counter(key_data["population"])
    seen_models = {name.split()[0] for name in population}
    models = [m for m in ("old", "new") if m in seen_models]
    per_model = {m: rates([p for p in pairs if p[2] == m]) for m in models}
    total_pass = sum(population[f"{m} PASS"] for m in models)
    total = sum(population.values())
    overall = (
        (total_pass * on_pass.value + (total - total_pass) * on_fail.value) / total
        if on_pass.total and on_fail.total
        else float("nan")
    )
    model_rates = []
    pass_iv = on_pass.interval
    fail_iv = on_fail.interval
    for m in models:
        n = population[f"{m} PASS"] + population[f"{m} FAIL"]
        if n == 0:
            continue
        judged_pass = population[f"{m} PASS"] / n
        if pass_iv is None or fail_iv is None:
            continue
        corrected = judged_pass * on_pass.value + (1 - judged_pass) * (1 - on_fail.value)
        low = judged_pass * pass_iv.low + (1 - judged_pass) * (1 - fail_iv.high)
        high = judged_pass * pass_iv.high + (1 - judged_pass) * (1 - fail_iv.low)
        name = key_data["old"] if m == "old" else key_data["new"]
        model_rates.append(ModelRate(name, judged_pass, corrected, low, high))
    return Agreement(
        labelled=len(pairs),
        unlabelled_rows=sum(label is None for label in labels.values()),
        on_pass=on_pass,
        on_fail=on_fail,
        per_model=per_model,
        kappa=_kappa([(j, p) for j, p, _ in pairs]),
        overall=overall,
        rates=tuple(model_rates),
    )


def _rate(rate: Rate) -> str:
    interval = rate.interval
    if interval is None:
        return "no answers"
    share = f"{rate.agree}/{rate.total}"
    return f"{rate.value:.0%} ({share}, 95% CI {interval.low:.0%}-{interval.high:.0%})"


def agreement_lines(result: Agreement) -> list[str]:
    """The agreement report, for people."""
    lines = [
        f"Labelled {result.labelled} answers"
        + (f" ({result.unlabelled_rows} rows still blank)." if result.unlabelled_rows else "."),
        f"When the judge said PASS, you agreed {_rate(result.on_pass)}.",
        f"When the judge said FAIL, you agreed {_rate(result.on_fail)}.",
    ]
    for model, (on_pass, on_fail) in result.per_model.items():
        lines.append(f"  {model} answers: PASS {_rate(on_pass)}; FAIL {_rate(on_fail)}")
    if result.overall == result.overall:  # not NaN
        lines.append(f"Judge and you agree on {result.overall:.0%} of the report's judged answers.")
    lines.append(
        f"Cohen's kappa on the sheet: {result.kappa:.2f} (the sheet is drawn half PASS, half FAIL)."
    )
    for rate in result.rates:
        lines.append(
            f"{rate.model}: judge pass rate {rate.judged_pass:.0%}, "
            f"corrected {rate.corrected:.0%} (range {rate.low:.0%}-{rate.high:.0%})"
        )
    if not result.rates:
        lines.append("Label answers the judge PASSed and FAILed to correct the pass rates.")
    return lines
