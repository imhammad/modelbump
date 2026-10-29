"""Tests for checking the judge against hand labels (ADR 0055)."""

import csv
import json
from pathlib import Path

import pytest

from modelbump.oracles.calibrate import (
    agreement,
    agreement_lines,
    make_sheet,
    parse_label,
    read_report,
)


def answer(
    model: str, sample: int, judge: str | None, text: str | None = None
) -> dict[str, object]:
    return {
        "model": model,
        "sample": sample,
        "score": 1.0,
        "failed": [],
        "judge": judge,
        "text": text if text is not None else f"{model} answer {sample}",
    }


def report_data() -> dict[str, object]:
    """Old: 40 judged answers, 30 PASS. New: 40, 20 PASS. A label case is not judged."""
    text_answers = [answer("old", s, "PASS" if s < 30 else "FAIL") for s in range(40)]
    text_answers += [answer("new", s, "PASS" if s < 20 else "FAIL") for s in range(40)]
    text_answers.append(answer("new", 99, "unclear"))
    return {
        "version": 1,
        "old": "ollama/old",
        "new": "ollama/new",
        "judge": "ollama/judge",
        "judge_version": "d1",
        "cases": [
            {
                "id": "bot.py:14#1",
                "messages": [
                    {"role": "system", "content": "Be brief."},
                    {"role": "user", "content": "Q?"},
                ],
                "reference_answer": "The reference.",
                "answers": text_answers,
            },
            {
                "id": "support.py:24#1",
                "messages": [{"role": "user", "content": "Ticket"}],
                "reference_answer": "bug",
                "answers": [answer("old", 3, None, "bug")],
            },
        ],
    }


def write_report(tmp_path: Path, data: dict[str, object] | None = None) -> Path:
    path = tmp_path / "report.json"
    path.write_text(json.dumps(data or report_data()), encoding="utf-8")
    return path


def read_sheet(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def label_sheet(sheet: Path, key: Path, person: dict[tuple[str, str], bool]) -> None:
    """Fill in your_label: the person's verdict per (model, judge verdict) of each row."""
    key_data = json.loads(key.read_text(encoding="utf-8"))
    rows = read_sheet(sheet)
    by_item = {item["item"]: item for item in key_data["items"]}
    for row in rows:
        first = by_item[int(row["item"])]["answers"][0]
        row["your_label"] = "PASS" if person[(first["model"], first["judge"])] else "fail"
    with sheet.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_read_report_keeps_only_pass_and_fail(tmp_path: Path) -> None:
    _, judged = read_report(write_report(tmp_path))
    assert len(judged) == 80
    assert {j.judge for j in judged} == {"PASS", "FAIL"}


def test_sheet_is_blind_balanced_and_reproducible(tmp_path: Path) -> None:
    report = write_report(tmp_path)
    sheet, key = tmp_path / "sheet.csv", tmp_path / "key.json"
    made = make_sheet(report, sheet, key, size=20, seed=1)
    assert (made.rows, made.answers) == (20, 20)
    assert made.drawn == {"PASS": 10, "FAIL": 10}
    assert made.available == {"PASS": 50, "FAIL": 30}
    rows = read_sheet(sheet)
    assert list(rows[0]) == ["item", "prompt", "reference", "answer", "your_label", "note"]
    assert rows[0]["prompt"] == "[system]\nBe brief.\n\n[user]\nQ?"
    assert rows[0]["reference"] == "The reference."
    assert {row["your_label"] for row in rows} == {""}
    # Nothing on the sheet says which model wrote the answer or what the judge said.
    text = sheet.read_text(encoding="utf-8")
    assert "ollama/" not in text and "PASS" not in text and "FAIL" not in text
    data = json.loads(key.read_text(encoding="utf-8"))
    assert data["population"] == {"new FAIL": 20, "new PASS": 20, "old FAIL": 10, "old PASS": 30}
    assert (data["judge"], data["judge_version"], data["seed"]) == ("ollama/judge", "d1", 1)
    first = sheet.read_text(encoding="utf-8")
    make_sheet(report, sheet, key, size=20, seed=1)
    assert sheet.read_text(encoding="utf-8") == first


def test_a_short_verdict_is_filled_from_the_other(tmp_path: Path) -> None:
    made = make_sheet(write_report(tmp_path), tmp_path / "s.csv", tmp_path / "k.json", size=70)
    assert made.drawn == {"PASS": 40, "FAIL": 30}


def test_equal_answers_share_one_row(tmp_path: Path) -> None:
    data = report_data()
    case = data["cases"][0]  # type: ignore[index]
    case["answers"] = [answer("old", s, "PASS", "same text") for s in range(4)] + [
        answer("new", 0, "FAIL", "other")
    ]
    sheet, key = tmp_path / "s.csv", tmp_path / "k.json"
    made = make_sheet(write_report(tmp_path, data), sheet, key, size=10)
    assert (made.rows, made.answers) == (2, 5)
    items = json.loads(key.read_text(encoding="utf-8"))["items"]
    assert sorted(len(item["answers"]) for item in items) == [1, 4]


def test_agreement_and_corrected_pass_rates(tmp_path: Path) -> None:
    sheet, key = tmp_path / "sheet.csv", tmp_path / "key.json"
    make_sheet(write_report(tmp_path), sheet, key, size=80, seed=3)
    # The person agrees with every judge PASS and disagrees with every judge FAIL on old
    # answers, but agrees with FAILs on new answers.
    person = {
        ("old", "PASS"): True,
        ("new", "PASS"): True,
        ("old", "FAIL"): True,
        ("new", "FAIL"): False,
    }
    label_sheet(sheet, key, person)
    result = agreement(sheet, key)
    assert result.labelled == 80
    assert (result.on_pass.agree, result.on_pass.total) == (50, 50)
    assert (result.on_fail.agree, result.on_fail.total) == (20, 30)
    _, old_fail = result.per_model["old"]
    assert (old_fail.agree, old_fail.total) == (0, 10)
    # Old: judge 75% PASS; corrected = .75 * 1 + .25 * (1 - 2/3).
    old, new = result.rates
    assert old.model == "ollama/old"
    assert old.judged_pass == pytest.approx(0.75)
    assert old.corrected == pytest.approx(0.75 + 0.25 / 3)
    assert old.low <= old.corrected <= old.high
    assert new.corrected == pytest.approx(0.5 + 0.5 / 3)
    lines = agreement_lines(result)
    assert lines[0] == "Judge: ollama/judge"
    assert lines[1] == "Labelled 80 answers."
    assert lines[2].startswith("When the judge said PASS, you agreed 100% (50/50, 95% CI")
    assert lines[3].startswith("When the judge said FAIL, you agreed 67% (20/30")
    assert "  old answers: PASS 100% (30/30" in lines[4]
    assert any(line.startswith("ollama/new: judge pass rate 50%, corrected 67%") for line in lines)


def test_partly_labelled_sheet(tmp_path: Path) -> None:
    sheet, key = tmp_path / "sheet.csv", tmp_path / "key.json"
    make_sheet(write_report(tmp_path), sheet, key, size=10, seed=3)
    rows = read_sheet(sheet)
    key_items = {i["item"]: i for i in json.loads(key.read_text(encoding="utf-8"))["items"]}
    passes = [r for r in rows if key_items[int(r["item"])]["answers"][0]["judge"] == "PASS"]
    passes[0]["your_label"] = "pass"
    with sheet.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    result = agreement(sheet, key)
    assert result.labelled == 1
    assert result.unlabelled_rows == 9
    assert result.rates == ()
    lines = agreement_lines(result)
    assert lines[1] == "Labelled 1 answers (9 rows still blank)."
    assert "When the judge said FAIL, you agreed no answers." in lines
    assert lines[-1] == "Label answers the judge PASSed and FAILed to correct the pass rates."


@pytest.mark.parametrize(
    ("text", "label"),
    [
        ("PASS", True),
        (" p ", True),
        ("Yes", True),
        ("1", True),
        ("fail", False),
        ("N", False),
        ("", None),
        ("  ", None),
    ],
)
def test_parse_label(text: str, label: bool | None) -> None:
    assert parse_label(text) is label


def test_bad_labels_and_files(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="is not PASS or FAIL"):
        parse_label("maybe")
    report = write_report(tmp_path)
    sheet, key = tmp_path / "sheet.csv", tmp_path / "key.json"
    make_sheet(report, sheet, key, size=4)
    rows = read_sheet(sheet)
    rows[0]["your_label"] = "maybe"
    with sheet.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ValueError, match=r"row \d+: label 'maybe'"):
        agreement(sheet, key)
    rows[0]["your_label"] = ""
    rows[0]["item"] = "999"
    with sheet.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ValueError, match="row 999 is not in"):
        agreement(sheet, key)
    empty = tmp_path / "empty.csv"
    empty.write_text("item,your_label\n1,\n\n", encoding="utf-8")
    with pytest.raises(ValueError, match="has no labels yet"):
        agreement(empty, key)
    wrong = tmp_path / "wrong.csv"
    wrong.write_text("a,b\n", encoding="utf-8")
    with pytest.raises(ValueError, match="has no item, your_label column"):
        agreement(wrong, key)
    old_key = tmp_path / "old.json"
    old_key.write_text('{"version": 9}', encoding="utf-8")
    with pytest.raises(ValueError, match="not a version 1 judge key"):
        agreement(sheet, old_key)
    with pytest.raises(ValueError, match="size must be at least 2"):
        make_sheet(report, sheet, key, size=1)


def test_reports_that_cannot_make_a_sheet(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="is not a `modelbump test --format json` report"):
        read_report(bad)
    data = report_data()
    data["judge"] = None
    with pytest.raises(ValueError, match="run without a judge"):
        read_report(write_report(tmp_path, data))
    data = report_data()
    del data["cases"][0]["reference_answer"]  # type: ignore[index]
    with pytest.raises(ValueError, match="older ModelBump"):
        read_report(write_report(tmp_path, data))


# --- A second sheet, and checking a new judge on old labels (ADR 0056) ------------


def test_a_fresh_sheet_leaves_out_answers_already_labelled(tmp_path: Path) -> None:
    report = write_report(tmp_path)
    first_key = tmp_path / "key1.json"
    first = make_sheet(report, tmp_path / "s1.csv", first_key, size=20, seed=1)
    second_key = tmp_path / "key2.json"
    second = make_sheet(
        report, tmp_path / "s2.csv", second_key, size=20, seed=2, exclude=[first_key]
    )
    assert second.excluded == first.answers == 20
    assert second.available == {"PASS": 40, "FAIL": 20}
    one = {
        (i["case"], a["model"], a["sample"])
        for i in json.loads(first_key.read_text())["items"]
        for a in i["answers"]
    }
    two = {
        (i["case"], a["model"], a["sample"])
        for i in json.loads(second_key.read_text())["items"]
        for a in i["answers"]
    }
    assert not one & two
    assert json.loads(second_key.read_text())["excluded"] == [str(first_key)]


def test_old_labels_against_a_new_judge(tmp_path: Path) -> None:
    sheet, key = tmp_path / "sheet.csv", tmp_path / "key.json"
    make_sheet(write_report(tmp_path), sheet, key, size=80, seed=3)
    person = {
        ("old", "PASS"): True,
        ("new", "PASS"): False,
        ("old", "FAIL"): False,
        ("new", "FAIL"): False,
    }
    label_sheet(sheet, key, person)
    # The new judge fails every new answer, and gives no verdict on old answer 0.
    data = report_data()
    for item in data["cases"][0]["answers"]:  # type: ignore[index]
        if item["model"] == "new":
            item["judge"] = "FAIL"
        if item["model"] == "old" and item["sample"] == 0:
            item["judge"] = "unclear"
    data["judge"] = "ollama/bigger"
    rejudged = tmp_path / "rejudged.json"
    rejudged.write_text(json.dumps(data), encoding="utf-8")
    result = agreement(sheet, key, rejudged)
    assert result.rejudged
    assert result.judge == "ollama/bigger"
    assert result.unclear == 1
    assert result.labelled == 79
    # New answers: the person fails all 40, and so does the new judge.
    _, new_fail = result.per_model["new"]
    assert (new_fail.agree, new_fail.total) == (40, 40)
    assert result.rates == ()
    lines = agreement_lines(result)
    assert lines[0] == "Judge: ollama/bigger"
    assert lines[1].startswith("Verdicts from another report;")
    assert lines[2] == (
        "1 labelled answers have no PASS or FAIL in that report "
        "(an unclear verdict, or a case left out of it); left out."
    )
    assert not any("corrected" in line for line in lines[3:])


def test_a_new_report_must_compare_the_same_models(tmp_path: Path) -> None:
    sheet, key = tmp_path / "sheet.csv", tmp_path / "key.json"
    make_sheet(write_report(tmp_path), sheet, key, size=4)
    data = report_data()
    data["new"] = "ollama/other"
    other = tmp_path / "other.json"
    other.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="compares other models"):
        agreement(sheet, key, other)
