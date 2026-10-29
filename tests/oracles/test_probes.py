"""Tests for judge probes (ADR 0058). No real model is used."""

import asyncio
import csv
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from modelbump.oracles.calibrate import SHEET_COLUMNS
from modelbump.oracles.probes import (
    INSTRUCTIONS,
    ProbeKind,
    check_probes,
    clean,
    make_probes,
    probe_lines,
    probe_request,
    text_cases,
    write_probes,
)
from modelbump.runner import Runner

REFERENCE = "You can read how we keep your data safe in our privacy policy."
REPORT: dict[str, Any] = {
    "version": 1,
    "judge": "ollama/judge",
    "cases": [
        {
            "id": "support.py:24#1",
            "kind": "text",
            "messages": [
                {"role": "system", "content": "Answer the customer."},
                {"role": "user", "content": "Is my data safe?"},
            ],
            "reference_answer": REFERENCE,
            "answers": [],
        },
        {"id": "bot.py:14#1", "kind": "label", "messages": [], "reference_answer": "bug"},
        {"id": "empty.py:1#1", "kind": "text", "messages": [], "reference_answer": " "},
    ],
}


def fake_runner() -> tuple[Runner, list[dict[str, Any]]]:
    seen: list[dict[str, Any]] = []

    def server(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        user = body["messages"][-1]["content"]
        if body["messages"][0]["content"].startswith("You grade"):
            candidate = user.split("## Candidate answer\n")[1]
            text = "FAIL" if "FAQ" in candidate or "maybe" in candidate else "PASS"
        elif INSTRUCTIONS[ProbeKind.CHANGED_SOURCE] in user:
            text = REFERENCE.replace("privacy policy", f"FAQ section {body['seed']}")
        elif INSTRUCTIONS[ProbeKind.PARAPHRASE] in user:
            # The first try copies the reference, so it must be asked again.
            text = (
                REFERENCE
                if body["seed"] == 0
                else f'"Our privacy policy explains it. {body["seed"]}"'
            )
        elif INSTRUCTIONS[ProbeKind.MISSING_FACT] in user:
            text = "   "  # never manages it
        elif INSTRUCTIONS[ProbeKind.HEDGED_INVENTION] in user:
            text = REFERENCE + " It is maybe encrypted."  # the same answer every time
        else:
            text = f"We never keep your data, says the policy {body['seed']}."
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    return Runner(transport=httpx.MockTransport(server)), seen


def test_probe_request_shows_prompt_answer_and_instruction() -> None:
    request = probe_request(
        (("user", "Is my data safe?"),), REFERENCE, ProbeKind.FLIPPED_MEANING, "ollama/b", 3
    )
    assert (request.model, request.seed, request.sample, request.temperature) == (
        "ollama/b",
        3,
        3,
        0.7,
    )
    user = request.messages[1].content
    assert user.startswith("## The app's prompt\n[user]\nIs my data safe?\n\n## The answer\n")
    assert user.endswith(INSTRUCTIONS[ProbeKind.FLIPPED_MEANING])


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('  "Changed answer."  ', "Changed answer."),
        ("", None),
        (REFERENCE, None),
        (REFERENCE.replace(" ", "  "), None),
        ("Other text.", "Other text."),
    ],
)
def test_clean(text: str, expected: str | None) -> None:
    assert clean(text, REFERENCE) == expected


def test_only_text_cases_with_a_reference_are_probed() -> None:
    assert [case["id"] for case in text_cases(REPORT)] == ["support.py:24#1"]
    assert all(kind.broken for kind in ProbeKind if kind is not ProbeKind.PARAPHRASE)
    assert not ProbeKind.PARAPHRASE.broken


def run_probes() -> tuple[Any, list[dict[str, Any]]]:
    runner, seen = fake_runner()
    run = asyncio.run(make_probes(REPORT, runner, breaker="ollama/b", judge="ollama/judge"))
    return run, seen


def test_make_probes_retries_and_counts_what_it_could_not_write() -> None:
    run, seen = run_probes()
    assert run.cases == 1
    kinds = [probe.kind for probe in run.probes]
    assert kinds.count(ProbeKind.CHANGED_SOURCE) == 2
    assert kinds.count(ProbeKind.FLIPPED_MEANING) == 2
    assert kinds.count(ProbeKind.PARAPHRASE) == 2
    # The hedged edit is the same every time, so only one distinct probe; no missing-fact probe.
    assert kinds.count(ProbeKind.HEDGED_INVENTION) == 1
    assert run.missing == {"missing_fact": 2, "hedged_invention": 1}
    paraphrases = [p for p in run.probes if p.kind is ProbeKind.PARAPHRASE]
    assert [p.sample for p in paraphrases] == [1, 2]
    assert paraphrases[0].text == "Our privacy policy explains it. 1"
    verdicts = {p.kind: p.judge for p in run.probes}
    assert verdicts[ProbeKind.CHANGED_SOURCE] == "FAIL"
    assert verdicts[ProbeKind.FLIPPED_MEANING] == "PASS"  # the fake judge misses it
    judged = [body for body in seen if body["messages"][0]["content"].startswith("You grade")]
    assert len(judged) == len(run.probes)
    assert all(REFERENCE in body["messages"][1]["content"] for body in judged)


def write(tmp_path: Path) -> tuple[Path, Path, dict[str, Any]]:
    run, _ = run_probes()
    sheet, key = tmp_path / "probes.csv", tmp_path / "probes.json"
    write_probes(
        run,
        REPORT,
        tmp_path / "report.json",
        sheet,
        key,
        breaker="ollama/b",
        judge="ollama/judge",
        judge_version="d1",
        per_kind=2,
        seed=1,
    )
    return sheet, key, json.loads(key.read_text(encoding="utf-8"))


def test_the_sheet_is_blind_and_the_key_holds_kinds(tmp_path: Path) -> None:
    sheet, _, data = write(tmp_path)
    with sheet.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert tuple(rows[0]) == SHEET_COLUMNS
    assert len(rows) == len(data["probes"]) == 7
    assert rows[0]["reference"] == REFERENCE
    assert rows[0]["prompt"] == "[system]\nAnswer the customer.\n\n[user]\nIs my data safe?"
    assert {p["item"] for p in data["probes"]} == set(range(1, 8))
    assert data["missing"] == {"missing_fact": 2, "hedged_invention": 1}
    assert (data["judge"], data["judge_version"], data["breaker"]) == (
        "ollama/judge",
        "d1",
        "ollama/b",
    )
    by_item = {str(p["item"]): p for p in data["probes"]}
    assert all(row["answer"] == by_item[row["item"]]["text"] for row in rows)
    # Shuffled: the sheet is not in kind order.
    assert [p["kind"] for p in data["probes"]] != sorted(p["kind"] for p in data["probes"])


def label(sheet: Path, key_data: dict[str, Any], rule: Any) -> None:
    kinds = {str(p["item"]): p for p in key_data["probes"]}
    with sheet.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["your_label"] = rule(kinds[row["item"]])
    with sheet.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SHEET_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def test_check_probes_counts_confirmed_probes_per_kind(tmp_path: Path) -> None:
    sheet, key, data = write(tmp_path)

    def rule(probe: dict[str, Any]) -> str:
        if probe["kind"] == "paraphrase":
            return "PASS" if probe["sample"] == 1 else "FAIL"  # one paraphrase broke the meaning
        return "FAIL"

    label(sheet, data, rule)
    result = check_probes(sheet, key)
    kinds = {k.kind: k for k in result.kinds}
    assert set(kinds) == {
        ProbeKind.CHANGED_SOURCE,
        ProbeKind.FLIPPED_MEANING,
        ProbeKind.HEDGED_INVENTION,
        ProbeKind.PARAPHRASE,
    }
    changed = kinds[ProbeKind.CHANGED_SOURCE]
    assert (changed.labelled, changed.confirmed) == (2, 2)
    assert (changed.judge_right.agree, changed.judge_right.total) == (2, 2)
    flipped = kinds[ProbeKind.FLIPPED_MEANING].judge_right
    assert (flipped.agree, flipped.total) == (0, 2)
    paraphrase = kinds[ProbeKind.PARAPHRASE]
    assert (paraphrase.labelled, paraphrase.confirmed) == (2, 1)
    assert (paraphrase.judge_right.agree, paraphrase.judge_right.total) == (1, 1)
    assert (result.caught.agree, result.caught.total) == (3, 5)
    lines = probe_lines(result)
    assert lines[0] == "Judge: ollama/judge; probes written by ollama/b."
    assert "changed_source: 2 labelled, 2 really wrong by you; judge failed 2/2 (100%" in lines[1]
    assert any(line.startswith("paraphrase (control): 2 labelled, 1 still right") for line in lines)
    assert lines[-1].startswith("All broken kinds: judge caught 3/5 (60%")


def test_check_probes_reports_blank_rows_and_bad_input(tmp_path: Path) -> None:
    sheet, key, data = write(tmp_path)
    with pytest.raises(ValueError, match="no labels yet"):
        check_probes(sheet, key)
    label(sheet, data, lambda p: "FAIL" if p["kind"] == "changed_source" else "")
    result = check_probes(sheet, key)
    assert result.unlabelled == 5
    assert "5 rows are still blank and are left out." in probe_lines(result)
    label(sheet, data, lambda p: "maybe")
    with pytest.raises(ValueError, match="row 1"):
        check_probes(sheet, key)
    not_a_key = tmp_path / "other.json"
    not_a_key.write_text('{"version": 1, "items": []}')
    with pytest.raises(ValueError, match="not a probe key"):
        check_probes(sheet, not_a_key)


def test_unclear_verdicts_are_left_out(tmp_path: Path) -> None:
    sheet, key, data = write(tmp_path)
    for probe in data["probes"]:
        probe["judge"] = "unclear"
    key.write_text(json.dumps(data))
    label(sheet, data, lambda p: "FAIL" if p["kind"] == "changed_source" else "")
    result = check_probes(sheet, key)
    (changed,) = result.kinds
    assert (changed.confirmed, changed.unclear, changed.judge_right.total) == (2, 2, 0)
    lines = probe_lines(result)
    assert "judge failed none to check" in lines[2]
    assert "  2 had no clear verdict from the judge; left out." in lines
