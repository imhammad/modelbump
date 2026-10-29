"""Judge probes: answers broken on purpose, to see which mistakes the judge catches (ADR 0058).

Hand labels measure how often the judge is right on the answers models happen
to give. They cannot say *which* mistakes it misses, because each kind of
mistake shows up only a few times. A probe is made on purpose: a local model
(the "breaker") edits a case's reference answer in one known way.

- ``changed_source``: copied word for word, except where it sends the reader
  (a link, page, section, team) or one name or number.
- ``flipped_meaning``: mostly the same words, but the meaning is wrong.
- ``missing_fact``: the most important fact is left out.
- ``hedged_invention``: one invented detail, written vaguely or as an option.
- ``paraphrase``: other words, same meaning. A control: it should PASS, so a
  judge that fails everything does not look perfect.

The judge then grades each probe against the unchanged reference. The breaker
can fail too (an edit that changes nothing important, or a paraphrase that
changes the meaning), so a person labels every probe blind, and only probes the
person confirms count: the catch rate is judge FAILs among probes the person
FAILed, per kind.
"""

import csv
import json
import random
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from modelbump.oracles.calibrate import SHEET_COLUMNS, Rate, _prompt_text, parse_label
from modelbump.oracles.judge import judge_request, parse_verdict
from modelbump.runner import ChatRequest, ChatResult, Message, Runner, RunnerError

PROBES_VERSION = 1
DEFAULT_BREAKER = "ollama/qwen2.5:7b"
DEFAULT_PER_KIND = 2
DEFAULT_SEED = 2032
TEMPERATURE = 0.7
MAX_TOKENS = 500
MAX_ROUNDS = 3
"""Requests per probe at most: an edit equal to the reference, or empty, is asked again."""


class ProbeKind(StrEnum):
    CHANGED_SOURCE = "changed_source"
    FLIPPED_MEANING = "flipped_meaning"
    MISSING_FACT = "missing_fact"
    HEDGED_INVENTION = "hedged_invention"
    PARAPHRASE = "paraphrase"

    @property
    def broken(self) -> bool:
        """True when the probe is meant to be wrong (every kind but the paraphrase)."""
        return self is not ProbeKind.PARAPHRASE


INSTRUCTIONS = {
    ProbeKind.CHANGED_SOURCE: (
        "Copy the answer word for word, but change exactly one detail: where it sends the "
        "reader (a link, page, section, document, team or contact). If it sends the reader "
        "nowhere, change one name, number or date instead. The new detail must not appear "
        "in the prompt or the answer. Change nothing else."
    ),
    ProbeKind.FLIPPED_MEANING: (
        "Rewrite the answer using mostly the same words, but make its meaning wrong: swap "
        "who did what, turn a statement into its opposite, or change what happened. Keep "
        "the length and the tone, so it still sounds right."
    ),
    ProbeKind.MISSING_FACT: (
        "Rewrite the answer without its single most important fact: the one the prompt most "
        "needs. Keep everything else, and keep it sounding complete."
    ),
    ProbeKind.HEDGED_INVENTION: (
        "Copy the answer, but add one detail that is in neither the prompt nor the answer, "
        "written vaguely or as one of several options (for example 'your email or account "
        "details', or 'usually within a few days'). Change nothing else."
    ),
    ProbeKind.PARAPHRASE: (
        "Rewrite the answer in different words with exactly the same meaning and the same "
        "facts. Do not add, drop or change any fact, link or instruction."
    ),
}

SYSTEM = (
    "You edit answers to make test cases for an automatic grader. Follow the "
    "instruction exactly. Reply with the edited answer only: no title, quotes or explanation."
)


@dataclass(frozen=True, slots=True)
class Probe:
    """One edited answer and the judge's verdict on it."""

    case: str
    kind: ProbeKind
    sample: int
    text: str
    judge: str
    """``PASS``, ``FAIL`` or ``unclear``."""


@dataclass(frozen=True, slots=True)
class ProbeRun:
    probes: tuple[Probe, ...]
    cases: int
    """Free-text cases with a reference answer that were probed."""
    missing: Counter[str]
    """Probes per kind the breaker did not manage to write."""


def probe_request(
    messages: Sequence[tuple[str, str]], reference: str, kind: ProbeKind, model: str, sample: int
) -> ChatRequest:
    """The request that asks the breaker for one probe of ``kind``."""
    prompt = "\n\n".join(f"[{role}]\n{text}" for role, text in messages)
    user = (
        f"## The app's prompt\n{prompt}\n\n"
        f"## The answer\n{reference}\n\n"
        f"## Instruction\n{INSTRUCTIONS[kind]}"
    )
    return ChatRequest(
        model,
        (Message("system", SYSTEM), Message("user", user)),
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
        seed=sample,
        sample=sample,
    )


def clean(text: str, reference: str) -> str | None:
    """The probe text, or None when it is empty or the same as the reference."""
    probe = text.strip()
    if len(probe) >= 2 and probe[0] == probe[-1] and probe[0] in "\"'":
        probe = probe[1:-1].strip()
    if not probe or " ".join(probe.split()) == " ".join(reference.split()):
        return None
    return probe


def text_cases(report: dict[str, Any]) -> list[dict[str, Any]]:
    """The report's free-text cases that have a reference answer."""
    return [
        case
        for case in report["cases"]
        if case.get("kind") == "text" and (case.get("reference_answer") or "").strip()
    ]


def _texts(outcomes: Sequence[ChatResult | RunnerError]) -> list[str]:
    for outcome in outcomes:
        if isinstance(outcome, RunnerError):
            raise outcome
    return [outcome.text for outcome in outcomes if isinstance(outcome, ChatResult)]


async def make_probes(
    report: dict[str, Any],
    runner: Runner,
    *,
    breaker: str = DEFAULT_BREAKER,
    judge: str,
    judge_version: str = "",
    per_kind: int = DEFAULT_PER_KIND,
    kinds: Sequence[ProbeKind] = tuple(ProbeKind),
) -> ProbeRun:
    """Write ``per_kind`` probes of each kind for every free-text case, and judge them."""
    if per_kind < 1:
        raise ValueError(f"per_kind must be at least 1, got {per_kind}")
    cases = text_cases(report)
    made: list[tuple[dict[str, Any], tuple[tuple[str, str], ...], ProbeKind, int, str]] = []
    missing: Counter[str] = Counter()
    for case in cases:
        messages = tuple((str(m["role"]), str(m["content"])) for m in case["messages"])
        reference = str(case["reference_answer"])
        for kind in kinds:
            found: list[tuple[int, str]] = []
            seen = {" ".join(reference.split())}
            sample = 0
            while len(found) < per_kind and sample < per_kind * MAX_ROUNDS:
                want = range(sample, sample + per_kind - len(found))
                requests = [probe_request(messages, reference, kind, breaker, s) for s in want]
                for s, text in zip(want, _texts(await runner.run_each(requests)), strict=True):
                    probe = clean(text, reference)
                    if probe is not None and " ".join(probe.split()) not in seen:
                        seen.add(" ".join(probe.split()))
                        found.append((s, probe))
                sample = want.stop
            missing[kind.value] += per_kind - len(found)
            made.extend((case, messages, kind, s, text) for s, text in found)
    requests = [
        judge_request(messages, str(case["reference_answer"]), text, judge, judge_version)
        for case, messages, _, _, text in made
    ]
    replies = _texts(await runner.run_each(requests)) if requests else []
    probes = []
    for (case, _, kind, sample, text), reply in zip(made, replies, strict=True):
        verdict = parse_verdict(reply)
        label = "unclear" if verdict is None else ("PASS" if verdict else "FAIL")
        probes.append(Probe(str(case["id"]), kind, sample, text, label))
    return ProbeRun(tuple(probes), len(cases), +missing)


def write_probes(
    run: ProbeRun,
    report: dict[str, Any],
    report_path: Path,
    sheet: Path,
    key: Path,
    *,
    breaker: str,
    judge: str,
    judge_version: str,
    per_kind: int,
    seed: int = DEFAULT_SEED,
) -> None:
    """The blind sheet (no kind, no verdict, in shuffled order) and the key that holds both."""
    cases = {case["id"]: case for case in report["cases"]}
    order = list(run.probes)
    random.Random(seed).shuffle(order)
    with sheet.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(SHEET_COLUMNS)
        for number, probe in enumerate(order, start=1):
            case = cases[probe.case]
            writer.writerow(
                [
                    number,
                    _prompt_text(case["messages"]),
                    case["reference_answer"],
                    probe.text,
                    "",
                    "",
                ]
            )
    data = {
        "version": PROBES_VERSION,
        "report": str(report_path),
        "breaker": breaker,
        "judge": judge,
        "judge_version": judge_version,
        "per_kind": per_kind,
        "seed": seed,
        "cases": run.cases,
        "missing": dict(run.missing),
        "probes": [
            {
                "item": number,
                "case": probe.case,
                "kind": probe.kind.value,
                "sample": probe.sample,
                "judge": probe.judge,
                "text": probe.text,
            }
            for number, probe in enumerate(order, start=1)
        ],
    }
    key.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


@dataclass(frozen=True, slots=True)
class KindResult:
    """One kind of probe, checked against the person's labels."""

    kind: ProbeKind
    labelled: int
    confirmed: int
    """Probes the person labelled as the kind intends: FAIL for a broken kind, PASS for a
    paraphrase."""
    judge_right: Rate
    """Of the confirmed probes with a clear verdict, how many the judge got right."""
    unclear: int


@dataclass(frozen=True, slots=True)
class ProbeCheck:
    judge: str
    breaker: str
    kinds: tuple[KindResult, ...]
    unlabelled: int

    @property
    def caught(self) -> Rate:
        """All broken kinds together: judge FAILs among probes the person FAILed."""
        rates = [k.judge_right for k in self.kinds if k.kind.broken]
        return Rate(sum(r.agree for r in rates), sum(r.total for r in rates))


def check_probes(sheet: Path, key: Path) -> ProbeCheck:
    """Compare the person's labels on the probe sheet with the judge, kind by kind."""
    data = json.loads(key.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != PROBES_VERSION or "probes" not in data:
        raise ValueError(f"{key} is not a probe key from `modelbump judge probes`")
    probes = {int(p["item"]): p for p in data["probes"]}
    labels: dict[int, bool | None] = {}
    with sheet.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = {"item", "your_label"} - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"{sheet} has no {', '.join(sorted(missing))} column")
        for row in reader:
            if not (row.get("item") or "").strip():
                continue
            number = int(row["item"])
            if number not in probes:
                raise ValueError(f"row {number} is not in {key}")
            try:
                labels[number] = parse_label(row.get("your_label") or "")
            except ValueError as error:
                raise ValueError(f"row {number}: {error}") from error
    if not any(label is not None for label in labels.values()):
        raise ValueError(f"{sheet} has no labels yet")
    results = []
    for kind in ProbeKind:
        rows = [
            (probes[n], label)
            for n, label in labels.items()
            if label is not None and probes[n]["kind"] == kind.value
        ]
        if not rows:
            continue
        intended = not kind.broken  # the label a person should give: PASS only for paraphrase
        confirmed = [p for p, label in rows if label is intended]
        clear = [p for p in confirmed if p["judge"] in ("PASS", "FAIL")]
        right = sum((p["judge"] == "PASS") is intended for p in clear)
        results.append(
            KindResult(
                kind,
                len(rows),
                len(confirmed),
                Rate(right, len(clear)),
                len(confirmed) - len(clear),
            )
        )
    return ProbeCheck(
        str(data.get("judge", "")),
        str(data.get("breaker", "")),
        tuple(results),
        sum(label is None for label in labels.values()),
    )


def _share(rate: Rate) -> str:
    interval = rate.interval
    if interval is None:
        return "none to check"
    ci = f"95% CI {interval.low:.0%}-{interval.high:.0%}"
    return f"{rate.agree}/{rate.total} ({rate.value:.0%}, {ci})"


def probe_lines(result: ProbeCheck) -> list[str]:
    """The probe check, for people."""
    lines = [f"Judge: {result.judge}; probes written by {result.breaker}."]
    if result.unlabelled:
        lines.append(f"{result.unlabelled} rows are still blank and are left out.")
    for k in result.kinds:
        if k.kind.broken:
            lines.append(
                f"{k.kind.value}: {k.labelled} labelled, {k.confirmed} really wrong by you; "
                f"judge failed {_share(k.judge_right)}"
            )
        else:
            lines.append(
                f"{k.kind.value} (control): {k.labelled} labelled, {k.confirmed} still right "
                f"by you; judge passed {_share(k.judge_right)}"
            )
        if k.unclear:
            lines.append(f"  {k.unclear} had no clear verdict from the judge; left out.")
    lines.append(f"All broken kinds: judge caught {_share(result.caught)}.")
    return lines
