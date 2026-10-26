"""Smoke tests for the command-line interface."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from modelbump import __version__
from modelbump.cli import app

runner = CliRunner()


def test_version_flag_prints_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == f"modelbump {__version__}"


def test_scan_lists_findings_with_their_severity(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(
        'A = "claude-3-haiku-20240307"\n'
        'B = "gpt-9-turbo"\n'
        'C = "anthropic.claude-3-haiku-20240307-v1:0"\n'
        'D = "gpt-5.1"\n'
        'E = "gemini-3.1-flash-lite"\n'
    )
    result = runner.invoke(app, ["scan", str(tmp_path), "--today", "2026-10-22"])
    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    assert lines == [
        "app.py:1:6  claude-3-haiku-20240307  RETIRED  shut down on 2026-04-20; "
        "suggested replacement claude-haiku-4-5-20251001  [assigned to A]",
        "app.py:2:6  gpt-9-turbo  UNKNOWN  no retirement announced  [assigned to B]",
        "app.py:3:16  claude-3-haiku-20240307-v1 (= claude-3-haiku-20240307)  RETIRED  "
        "shut down on 2026-04-20; suggested replacement claude-haiku-4-5-20251001  "
        "[assigned to C]",
        "app.py:4:6  gpt-5.1  DEPRECATED  shuts down on 2027-04-01 (in 161 days); "
        "suggested replacement gpt-6-sol  [assigned to D]",
        "app.py:5:6  gemini-3.1-flash-lite  DEPRECATED  shuts down no earlier than 2027-05-07 "
        "(in 197 days); suggested replacement gemini-3.5-flash-lite  [assigned to E]",
        "Found 5 model IDs in 1 file (scanned 1 file): 2 RETIRED, 2 DEPRECATED, 1 UNKNOWN.",
    ]


def test_scan_soon_days_sets_the_warning_window(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text('D = "gpt-5.1"\n')
    result = runner.invoke(
        app, ["scan", str(tmp_path), "--today", "2026-10-22", "--soon-days", "200"]
    )
    assert result.exit_code == 0
    assert "gpt-5.1  RETIRING_SOON  shuts down on 2027-04-01 (in 161 days)" in result.stdout


def test_scan_fail_within_sets_the_exit_code(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text('A = "claude-3-haiku-20240307"\nD = "gpt-5.1"\n')
    args = ["scan", str(tmp_path), "--today", "2026-10-22", "--fail-within"]
    retired_only = runner.invoke(app, [*args, "30"])
    assert retired_only.exit_code == 1
    assert "Failed: 1 model ID is retired or shut down within 30 days." in retired_only.stdout
    both = runner.invoke(app, [*args, "161"])
    assert both.exit_code == 1
    assert "Failed: 2 model IDs are retired or shut down within 161 days." in both.stdout
    before_notices = ["scan", str(tmp_path), "--today", "2026-01-01", "--fail-within", "30"]
    clean = runner.invoke(app, before_notices)
    assert clean.exit_code == 0


def test_scan_before_the_notice_is_unknown(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text('A = "claude-3-haiku-20240307"\n')
    result = runner.invoke(
        app, ["scan", str(tmp_path), "--today", "2026-02-18", "--fail-within", "0"]
    )
    assert result.exit_code == 0
    assert "claude-3-haiku-20240307  UNKNOWN  no retirement announced" in result.stdout


def test_scan_rejects_a_bad_date(tmp_path: Path) -> None:
    result = runner.invoke(app, ["scan", str(tmp_path), "--today", "22/10/2026"])
    assert result.exit_code == 2


def test_scan_reports_when_nothing_is_found(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("print('hello')\n")
    (tmp_path / "big.json").write_text("x" * 1_000_001)
    result = runner.invoke(app, ["scan", str(tmp_path)])
    assert result.exit_code == 0
    assert "No model IDs found (scanned 1 file, skipped 1 too big or binary)." in result.stdout


def test_scan_rejects_a_missing_path(tmp_path: Path) -> None:
    result = runner.invoke(app, ["scan", str(tmp_path / "nope")])
    assert result.exit_code == 2


def test_check_known_retired_model() -> None:
    result = runner.invoke(app, ["check", "claude-3-haiku-20240307"])
    assert result.exit_code == 0
    assert "(anthropic): RETIRED since 2026-04-20." in result.stdout
    assert "Suggested replacement: claude-haiku-4-5-20251001" in result.stdout


def test_check_unknown_model() -> None:
    result = runner.invoke(app, ["check", "not-a-real-model"])
    assert result.exit_code == 0
    assert "not in the registry" in result.stdout


def test_check_rescheduled_model() -> None:
    result = runner.invoke(app, ["check", "gpt-4-0314"])
    assert result.exit_code == 0
    assert "(openai): RETIRED since 2026-03-26." in result.stdout
    assert "Rescheduled: 1 earlier plan(s) were replaced." in result.stdout


def test_check_earliest_possible_date() -> None:
    result = runner.invoke(app, ["check", "gemini-2.0-flash"])
    assert result.exit_code == 0
    assert "RETIRED since 2026-06-01 (the earliest possible date" in result.stdout


def test_scan_json_to_screen_stays_valid_json(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text('A = "claude-3-haiku-20240307"\n')
    args = ["scan", str(tmp_path), "--today", "2026-10-22", "--format", "json"]
    result = runner.invoke(app, [*args, "--fail-within", "0"])
    assert result.exit_code == 1
    data = json.loads(result.stdout)
    assert data["failed"] is True
    assert data["findings"][0]["severity"] == "retired"
    assert "Failed: 1 model ID is retired" in result.stderr


def test_scan_sarif_to_a_file(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text('A = "claude-3-haiku-20240307"\n')
    out = tmp_path / "out" / "modelbump.sarif"
    out.parent.mkdir()
    args = ["scan", str(tmp_path / "app.py"), "--today", "2026-10-22"]
    result = runner.invoke(app, [*args, "--format", "sarif", "--output", str(out)])
    assert result.exit_code == 0
    assert result.stdout.splitlines() == [
        f"Wrote sarif report to {out}.",
        "Found 1 model ID in 1 file (scanned 1 file): 1 RETIRED.",
    ]
    sarif = json.loads(out.read_text())
    assert sarif["runs"][0]["results"][0]["ruleId"] == "modelbump/retired"


def test_scan_rejects_an_unknown_format(tmp_path: Path) -> None:
    result = runner.invoke(app, ["scan", str(tmp_path), "--format", "xml"])
    assert result.exit_code == 2


def test_scan_exclude_can_be_repeated(tmp_path: Path) -> None:
    for rel in ["app.py", "tests/test_app.py", "notebooks/try.ipynb"]:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('MODEL = "gpt-4o"\n')
    result = runner.invoke(
        app, ["scan", str(tmp_path), "--exclude", "tests", "--exclude", "*.ipynb"]
    )
    assert result.exit_code == 0
    assert "Found 1 model ID in 1 file (scanned 1 file): 1 UNKNOWN." in result.stdout


def test_scan_sarif_paths_are_relative_to_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "app.py").write_text('A = "claude-3-haiku-20240307"\n')
    monkeypatch.chdir(tmp_path)

    def first_uri(target: str) -> str:
        result = runner.invoke(app, ["scan", target, "--format", "sarif"])
        location = json.loads(result.stdout)["runs"][0]["results"][0]["locations"][0]
        uri: str = location["physicalLocation"]["artifactLocation"]["uri"]
        return uri

    assert first_uri(".") == "sub/app.py"
    assert first_uri("sub") == "sub/app.py"
    assert first_uri("sub/app.py") == "sub/app.py"
    monkeypatch.chdir(tmp_path / "sub")
    assert first_uri(str(tmp_path / "sub")) == "app.py"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert first_uri(str(tmp_path / "sub")) == "app.py"


def test_scan_skip_comments(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(
        '"""Uses gpt-4o."""\n# old: gpt-4o\nclient.create(model="gpt-4o")\n'
    )
    every = runner.invoke(app, ["scan", str(tmp_path)])
    assert "[in a docstring]" in every.stdout
    assert "[in a comment]" in every.stdout
    assert "Found 3 model IDs" in every.stdout
    skipped = runner.invoke(app, ["scan", str(tmp_path), "--skip-comments"])
    assert skipped.stdout.splitlines() == [
        "app.py:3:22  gpt-4o  UNKNOWN  no retirement announced  [in client.create(model=)]",
        "Found 1 model ID in 1 file (scanned 1 file): 1 UNKNOWN.",
    ]


def test_scan_skip_comments_also_skips_sentences_and_tables(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(
        'PRICES = {"gpt-4o": 2.5}\nprint("Using gpt-4o today")\nMODEL = "gpt-4o"\n'
    )
    every = runner.invoke(app, ["scan", str(tmp_path)])
    assert "[key of a price or limit table]" in every.stdout
    assert "[in a sentence]" in every.stdout
    skipped = runner.invoke(app, ["scan", str(tmp_path), "--skip-comments"])
    assert "Found 1 model ID" in skipped.stdout
    assert "[assigned to MODEL]" in skipped.stdout


def test_scan_skip_tests(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text('MODEL = "gpt-4o"\n')
    (tmp_path / "app.test.ts").write_text('const m = "gpt-4o";\n')
    (tmp_path / "app.py").write_text('MODEL = "gpt-4o"\n')
    every = runner.invoke(app, ["scan", str(tmp_path)])
    assert "Found 3 model IDs" in every.stdout
    skipped = runner.invoke(app, ["scan", str(tmp_path), "--skip-tests"])
    assert "Found 1 model ID in 1 file" in skipped.stdout
    assert "app.py:1:" in skipped.stdout


def test_ask_prints_the_answer_and_a_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    from modelbump.runner import ChatResult, Runner

    async def fake_run(self: Runner, request: object) -> ChatResult:
        return ChatResult("Hi there.", "ollama/qwen2.5:7b", 12, 3, "stop", 1, 0.5)

    monkeypatch.setattr(Runner, "run", fake_run)
    result = runner.invoke(app, ["ask", "Say hi"])
    assert result.exit_code == 0
    assert result.stdout == "Hi there.\n"
    assert "12 tokens in, 3 out, 1 attempt, 0.5s, finish: stop" in result.stderr


def test_ask_explains_when_ollama_is_not_running(monkeypatch: pytest.MonkeyPatch) -> None:
    from modelbump.runner import Runner, RunnerError

    async def fake_run(self: Runner, request: object) -> object:
        raise RunnerError("ollama/qwen2.5:7b: could not reach http://localhost:11434/v1")

    monkeypatch.setattr(Runner, "run", fake_run)
    result = runner.invoke(app, ["ask", "Say hi"])
    assert result.exit_code == 1
    assert "open -a Ollama" in result.stderr


def test_ask_rejects_a_model_without_an_endpoint() -> None:
    result = runner.invoke(app, ["ask", "Say hi", "--model", "qwen2.5:7b"])
    assert result.exit_code == 1
    assert "endpoint/model" in result.stderr
