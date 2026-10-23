"""Tests for re-scoring the labelled findings with the current scanner. No network is used."""

import csv
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from modelbump.registry import load_registry
from research.filtering.filter import read_jsonl, write_jsonl
from research.scanner_eval.build import draw_sheet, write_sheet
from research.scanner_eval.rescore import (
    SheetMismatchError,
    fetch_missing,
    kept_by,
    main,
    recall,
    rescan,
    rescore,
)

SNAPSHOT = {
    "app.py": 'MODEL = "gpt-4o"\nprint("Using gpt-4o today")\n',
    "prices.py": 'PRICES = {\n    "gpt-4o": 2.5,\n}\n',
    "main.go": '// gpt-4o is old\nmodel := "gpt-4o"\n',
    "tests/test_app.py": 'client.create(model="gpt-4o")\n',
    "conf.yaml": "model: gpt-4o\n",
}
# What the scanner that built the set said, before ADR 0031.
OLD_CONTEXT = {"prose": "string", "table": "string"}
OLD_TEXT_COMMENT = ("main.go", 1)
LABELS = {
    ("app.py", 1): "yes",
    ("app.py", 2): "no",
    ("prices.py", 2): "no",
    ("main.go", 1): "no",
    ("main.go", 2): "yes",
    ("tests/test_app.py", 1): "no",
    ("conf.yaml", 1): "yes",
}
HTML = b'<script>const model = "gpt-4o";</script>\n'


def make_set(folder: Path) -> list[dict[str, Any]]:
    """An evaluation folder as the build wrote it, with the sheet labelled."""
    snap = folder / "snapshots" / "aaa"
    for path, text in SNAPSHOT.items():
        (snap / path).parent.mkdir(parents=True, exist_ok=True)
        (snap / path).write_text(text)
    commits = [{"sha": "aaa", "repo": "acme/app", "parent": "paaa", "model_id": "gpt-4o"}]
    write_jsonl(commits, folder / "commits.jsonl")
    old = rescan(commits, folder / "snapshots", load_registry())
    for finding in old:
        finding["repo"] = "acme/app"
        finding["context"] = OLD_CONTEXT.get(finding["context"], finding["context"])
        if (finding["path"], finding["line"]) == OLD_TEXT_COMMENT:
            finding["context"] = "text"
    write_jsonl(old, folder / "findings.jsonl")
    chosen = draw_sheet(old, 10, 2031)
    write_sheet(
        chosen,
        folder / "snapshots",
        {"aaa": "paaa"},
        folder / "sheet.csv",
        folder / "sheet_key.csv",
    )
    with (folder / "sheet.csv").open(newline="") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        row["dependency"] = LABELS[(row["path"], int(row["line"]))]
    with (folder / "sheet.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    sites = [
        {
            "sha": "aaa",
            "model_id": "gpt-4o",
            "path": "app.py",
            "line": 1,
            "found": True,
            "reason": None,
        },
        {
            "sha": "aaa",
            "model_id": "gpt-4o",
            "path": "main.go",
            "line": 1,
            "found": True,
            "reason": None,
        },
        {
            "sha": "aaa",
            "model_id": "gpt-4o",
            "path": "web/index.html",
            "line": 1,
            "found": False,
            "reason": "file type not scanned",
        },
        {
            "sha": "aaa",
            "model_id": "gpt-4o",
            "path": "init.el",
            "line": 1,
            "found": False,
            "reason": "file type not scanned",
        },
    ]
    write_jsonl(sites, folder / "sites.jsonl")
    return old


def raw_github(requests: list[str]) -> httpx.Client:
    def serve(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url.path == "/acme/app/paaa/web/index.html":
            return httpx.Response(200, content=HTML)
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(serve))


def test_kept_by() -> None:
    prose = {"context": "prose", "path": "app.py"}
    test = {"context": "string", "path": "tests/test_app.py"}
    assert kept_by("all")(prose) and kept_by("all")(test)
    assert not kept_by("skip_comments")(prose) and kept_by("skip_comments")(test)
    assert kept_by("skip_tests")(prose) and not kept_by("skip_tests")(test)
    assert not kept_by("both")(prose) and not kept_by("both")(test)


def test_rescore_end_to_end(tmp_path: Path) -> None:
    make_set(tmp_path)
    requests: list[str] = []
    result = rescore(tmp_path, load_registry(), raw_github(requests), per_group=10)
    p = result["precision"]
    # code_use: app.py:1 yes, tests call no; code_string: prose no, table no;
    # text: go comment no, go code yes; config: yes.
    assert p["all"]["findings"] == 7
    assert p["all"]["groups"]["code_use"]["share"] == pytest.approx(0.5)
    # Population weights: code_use 2, code_string 2, text 2, config 1 -> (1 + 0 + 1 + 1) / 7.
    assert p["all"]["estimate"] == pytest.approx(3 / 7)
    # --skip-comments drops the sentence, the table and the Go comment.
    assert p["skip_comments"]["findings"] == 4
    assert p["skip_comments"]["estimate"] == pytest.approx((2 * 0.5 + 1 + 1) / 4)
    assert p["skip_tests"]["findings"] == 6
    assert p["both"]["estimate"] == pytest.approx(1.0)
    assert p["both"]["unestimated_findings"] == 0
    changes = {(c["from"], c["to"], c["label"]): c["rows"] for c in result["changed_labelled_rows"]}
    assert changes == {
        ("string", "prose", "no"): 1,
        ("string", "table", "no"): 1,
        ("text", "comment", "no"): 1,
    }
    # Only the HTML file is read by the scanner now; the Emacs file still is not.
    assert result["missing_files"] == {"fetched": 1}
    assert requests == ["https://raw.githubusercontent.com/acme/app/paaa/web/index.html"]
    assert result["recall_snapshots"]["yes"] == 2
    assert result["recall"]["all"]["yes"] == 3
    assert result["recall"]["all"]["n"] == 4
    # The Go comment is a known site, so --skip-comments loses it.
    assert result["recall"]["skip_comments"]["yes"] == 2
    assert (tmp_path / "rescore.findings.jsonl").exists()
    # The second run reads the fetched file from disk.
    again: list[str] = []
    second = rescore(tmp_path, load_registry(), raw_github(again), per_group=10)
    assert second["missing_files"] == {"cached": 1}
    assert {**second, "missing_files": None} == {**result, "missing_files": None}
    assert again == []


def test_rescore_never_changes_the_build_files(tmp_path: Path) -> None:
    make_set(tmp_path)
    names = ("commits.jsonl", "findings.jsonl", "sites.jsonl", "sheet.csv", "sheet_key.csv")
    before = {n: (tmp_path / n).read_bytes() for n in names}
    rescore(tmp_path, load_registry(), None, per_group=10)
    assert {n: (tmp_path / n).read_bytes() for n in names} == before


def test_a_sheet_that_does_not_match_the_draw_is_refused(tmp_path: Path) -> None:
    make_set(tmp_path)
    with pytest.raises(SheetMismatchError, match="sheet has 7 rows, the draw has 4"):
        rescore(tmp_path, load_registry(), None, per_group=1)
    sheet = (tmp_path / "sheet.csv").read_text().replace("app.py", "other.py", 1)
    (tmp_path / "sheet.csv").write_text(sheet)
    with pytest.raises(SheetMismatchError, match="is not the finding the build drew"):
        rescore(tmp_path, load_registry(), None, per_group=10)


def test_a_bad_answer_is_refused(tmp_path: Path) -> None:
    make_set(tmp_path)
    sheet = (tmp_path / "sheet.csv").read_text().replace(",yes,", ",yse,", 1)
    (tmp_path / "sheet.csv").write_text(sheet)
    with pytest.raises(SheetMismatchError, match="not yes, no or unclear"):
        rescore(tmp_path, load_registry(), None, per_group=10)


def test_findings_at_new_places_are_refused(tmp_path: Path) -> None:
    make_set(tmp_path)
    (tmp_path / "snapshots" / "aaa" / "new.py").write_text('M = "gpt-4o"\n')
    with pytest.raises(SheetMismatchError, match="other places"):
        rescore(tmp_path, load_registry(), None, per_group=10)


def test_fetch_missing_without_network_and_on_failure(tmp_path: Path) -> None:
    sites = [
        {"sha": "a", "path": "x.html", "found": False, "reason": "file type not scanned"},
        {"sha": "a", "path": "y.html", "found": True, "reason": None},
        {"sha": "a", "path": "z.py", "found": False, "reason": "not found by the finder"},
    ]
    assert fetch_missing(sites, {"a": "p"}, {"a": "o/r"}, tmp_path, None) == {"not fetched": 1}
    failing = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    assert fetch_missing(sites, {"a": "p"}, {"a": "o/r"}, tmp_path, failing) == {"failed (404)": 1}


def test_recall_counts_registry_ids() -> None:
    sites = [{"sha": "a", "path": "x.py", "line": 1, "model_id": "gpt-4o"}]
    found = [
        {
            "sha": "a",
            "path": "x.py",
            "line": 1,
            "model_id": "openai/gpt-4o",
            "registry_id": "gpt-4o",
            "context": "string",
        }
    ]
    assert recall(sites, found, "all")["share"] == 1.0
    assert recall([], [], "all")["share"] is None


def test_main(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--dir", str(tmp_path)]) == 1
    assert "Run the build first" in capsys.readouterr().err
    make_set(tmp_path)
    # Every group is smaller than 50, so the default draw is the same sheet.
    assert main(["--dir", str(tmp_path), "--no-fetch"]) == 0
    out = capsys.readouterr().out
    assert "--skip-comments --skip-tests" in out
    assert "string -> prose" in out
    assert "{'not fetched': 1}" in out
    requests: list[str] = []
    assert main(["--dir", str(tmp_path)], http=raw_github(requests)) == 0
    written = json.loads((tmp_path / "rescore.json").read_text())
    assert written["missing_files"] == {"fetched": 1}
    assert list(read_jsonl(tmp_path / "rescore.findings.jsonl"))


def test_main_reports_a_mismatch(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_set(tmp_path)
    (tmp_path / "snapshots" / "aaa" / "new.py").write_text('M = "gpt-4o"\n')
    assert main(["--dir", str(tmp_path), "--no-fetch"]) == 1
    assert "Cannot re-score" in capsys.readouterr().err


def test_fetch_missing_skips_files_too_big_to_scan(tmp_path: Path) -> None:
    sites = [{"sha": "a", "path": "x.html", "found": False, "reason": "file type not scanned"}]
    big = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * 1_000_001))
    )
    assert fetch_missing(sites, {"a": "p"}, {"a": "o/r"}, tmp_path, big) == {"too big to scan": 1}
    assert not (tmp_path / "a").exists()
