"""Smoke tests for the command-line interface."""

import csv
import json
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from modelbump import __version__
from modelbump.cli import app
from modelbump.runner import ChatRequest, Runner, RunnerError

runner = CliRunner()


@pytest.fixture(autouse=True)
def _no_ollama_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    """`ask` pins Ollama models to their digest; tests have no Ollama to ask."""
    monkeypatch.setattr("modelbump.cli.pin_versions", lambda requests: list(requests))


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

    async def fake_run_each(self: Runner, requests: list[object]) -> list[ChatResult]:
        return [ChatResult("Hi there.", "ollama/qwen2.5:7b", 12, 3, "stop", 1, 0.5)]

    monkeypatch.setattr(Runner, "run_each", fake_run_each)
    result = runner.invoke(app, ["ask", "Say hi"])
    assert result.exit_code == 0
    assert result.stdout == "Hi there.\n"
    assert "12 tokens in, 3 out, 1 attempt, 0.5s, finish: stop" in result.stderr


def test_ask_explains_when_ollama_is_not_running(monkeypatch: pytest.MonkeyPatch) -> None:
    from modelbump.runner import Runner, RunnerError

    async def fake_run_each(self: Runner, requests: list[object]) -> list[RunnerError]:
        return [RunnerError("ollama/qwen2.5:7b: could not reach http://localhost:11434/v1")]

    monkeypatch.setattr(Runner, "run_each", fake_run_each)
    result = runner.invoke(app, ["ask", "Say hi"])
    assert result.exit_code == 1
    assert "open -a Ollama" in result.stderr


def test_ask_rejects_a_model_without_an_endpoint() -> None:
    result = runner.invoke(app, ["ask", "Say hi", "--model", "qwen2.5:7b"])
    assert result.exit_code == 1
    assert "endpoint/model" in result.stderr


def test_ask_reads_the_second_identical_question_from_the_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    from modelbump.runner import Runner

    calls = []

    def server(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "Apple"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 1},
            },
        )

    real_init = Runner.__init__

    def init_with_fake_server(self: Runner, **options: object) -> None:
        real_init(self, transport=httpx.MockTransport(server), **options)  # type: ignore[arg-type]

    monkeypatch.setattr(Runner, "__init__", init_with_fake_server)
    first = runner.invoke(app, ["ask", "Name a fruit."])
    second = runner.invoke(app, ["ask", "Name a fruit."])
    fresh = runner.invoke(app, ["ask", "Name a fruit.", "--no-cache"])
    assert first.stdout == second.stdout == fresh.stdout == "Apple\n"
    assert "1 attempt" in first.stderr
    assert "from cache" in second.stderr
    assert "from cache" not in fresh.stderr
    assert len(calls) == 2


def test_cache_info_and_clear(tmp_path: Path) -> None:
    from modelbump.runner import ChatRequest, ChatResult, ResponseCache

    cache = ResponseCache()
    request = ChatRequest.ask("ollama/m", "hi")
    cache.put(request, ChatResult("hello", request.model, 3, 7, "stop", 1, 0.2))
    cache.close()
    info = runner.invoke(app, ["cache", "info"])
    assert info.exit_code == 0
    assert "Answers stored: 1 (7 output tokens)" in info.stdout
    assert "modelbump-cache" in info.stdout
    kept = runner.invoke(app, ["cache", "clear"], input="n\n")
    assert kept.exit_code == 1
    assert "Answers stored: 1" in runner.invoke(app, ["cache", "info"]).stdout
    cleared = runner.invoke(app, ["cache", "clear", "--yes"])
    assert cleared.exit_code == 0
    assert "Deleted 1 stored answers." in cleared.stdout


def test_ask_several_prompts_with_a_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    from modelbump.runner import Runner

    def server(request: httpx.Request) -> httpx.Response:
        prompt = json.loads(request.content)["messages"][-1]["content"]
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": prompt.upper()}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    real_init = Runner.__init__

    def init_with_fake_server(self: Runner, **options: object) -> None:
        real_init(self, transport=httpx.MockTransport(server), **options)  # type: ignore[arg-type]

    monkeypatch.setattr(Runner, "__init__", init_with_fake_server)
    stopped = runner.invoke(app, ["ask", "a", "b", "c", "--budget-requests", "2"])
    assert stopped.exit_code == 1
    assert stopped.stdout == "## a\nA\n## b\nB\n## c\n"
    assert "Budget reached: 2 of 2 requests sent." in stopped.stderr
    assert "run the same command with a higher limit" in stopped.stderr
    rerun = runner.invoke(app, ["ask", "a", "b", "c", "--budget-requests", "2"])
    assert rerun.exit_code == 0
    assert rerun.stdout.endswith("## c\nC\n")
    assert "Spent: 1 requests, 15 tokens" in rerun.stderr
    assert "From cache: 2 answers (30 tokens saved)." in rerun.stderr


def test_ask_stops_before_sending_when_a_model_is_not_pulled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modelbump.runner import RunnerError

    def not_pulled(requests: list[object]) -> list[object]:
        raise RunnerError("ollama/qwen3:8b: this model is not pulled. Run: ollama pull qwen3:8b")

    monkeypatch.setattr("modelbump.cli.pin_versions", not_pulled)
    result = runner.invoke(app, ["ask", "hi", "-m", "ollama/qwen3:8b", "--think", "none"])
    assert result.exit_code == 1
    assert "Run: ollama pull qwen3:8b" in result.stderr


def test_ask_hints_when_ollama_is_down_at_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    from modelbump.runner import RunnerError

    def down(requests: list[object]) -> list[object]:
        raise RunnerError("could not reach http://localhost:11434 (ConnectError)")

    monkeypatch.setattr("modelbump.cli.pin_versions", down)
    result = runner.invoke(app, ["ask", "hi"])
    assert result.exit_code == 1
    assert "open -a Ollama" in result.stderr


def test_models_lists_what_ollama_has(monkeypatch: pytest.MonkeyPatch) -> None:
    from modelbump.runner import LocalModel

    found = [
        LocalModel(
            "qwen2.5:7b", "845dbda0ea48" + "1" * 52, 4_683_087_332, "qwen2", "7.6B", "Q4_K_M"
        ),
        LocalModel("qwen3:8b", "500a1f067a9f" + "0" * 52, 5_225_388_164, "qwen3", "8.2B", "Q4_K_M"),
    ]
    monkeypatch.setattr("modelbump.cli.list_local_models", lambda: found)
    result = runner.invoke(app, ["models"])
    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    assert lines[0].split() == ["MODEL", "PARAMS", "QUANT", "SIZE", "DIGEST"]
    assert lines[1].split() == ["ollama/qwen2.5:7b", "7.6B", "Q4_K_M", "4.7", "GB", "845dbda0ea48"]
    assert lines[2].split()[0] == "ollama/qwen3:8b"


def test_models_when_none_are_pulled_or_ollama_is_down(monkeypatch: pytest.MonkeyPatch) -> None:
    from modelbump.runner import RunnerError

    monkeypatch.setattr("modelbump.cli.list_local_models", lambda: [])
    assert "ollama pull qwen2.5:7b" in runner.invoke(app, ["models"]).stdout

    def down() -> list[object]:
        raise RunnerError("could not reach http://localhost:11434 (ConnectError)")

    monkeypatch.setattr("modelbump.cli.list_local_models", down)
    result = runner.invoke(app, ["models"])
    assert result.exit_code == 1
    assert "open -a Ollama" in result.stderr


def test_ask_warns_before_using_a_cloud_tier(monkeypatch: pytest.MonkeyPatch) -> None:
    from modelbump.runner import ChatResult, Runner

    async def fake_run_each(self: Runner, requests: list[object]) -> list[ChatResult]:
        return [ChatResult("Canberra", "groq/llama-3.1-8b-instant", 20, 2, "stop", 1, 0.3)]

    monkeypatch.setattr(Runner, "run_each", fake_run_each)
    cloud = runner.invoke(app, ["ask", "Capital of Australia?", "-m", "groq/llama-3.1-8b-instant"])
    assert cloud.exit_code == 0
    assert "groq is a free cloud tier" in cloud.stderr
    assert "Never send private data." in cloud.stderr
    local = runner.invoke(app, ["ask", "Capital of Australia?"])
    assert "cloud tier" not in local.stderr


def test_ask_rejects_an_unknown_endpoint() -> None:
    result = runner.invoke(app, ["ask", "hi", "-m", "paid/gpt-9"])
    assert result.exit_code == 1
    assert "Unknown endpoint 'paid'" in result.stderr


def test_stats_item_says_regressed_for_a_clear_drop() -> None:
    result = runner.invoke(app, ["stats", "item", "9/10", "4/10"])
    assert result.exit_code == 0
    assert "Old model: 9/10 passed (90.0%)" in result.stdout
    assert "Difference (new - old): -50.0 points, 90% interval -75.8 to -7.9" in result.stdout
    assert "Verdict: REGRESSED" in result.stdout


def test_stats_item_takes_margin_and_alpha() -> None:
    result = runner.invoke(
        app, ["stats", "item", "900/1000", "850/1000", "--margin", "0", "--alpha", "0.01"]
    )
    assert result.exit_code == 0
    assert "98% interval" in result.stdout
    assert "Verdict: REGRESSED" in result.stdout


def test_stats_item_rejects_badly_written_counts() -> None:
    result = runner.invoke(app, ["stats", "item", "9", "4/10"])
    assert result.exit_code == 2
    assert "PASSES/RUNS" in result.stderr


def test_stats_item_rejects_impossible_counts() -> None:
    result = runner.invoke(app, ["stats", "item", "11/10", "4/10"])
    assert result.exit_code == 2
    assert "between 0 and 10" in result.stderr


def test_stats_simulate_stops_early_on_a_clear_drop() -> None:
    result = runner.invoke(app, ["stats", "simulate", "0.9", "0.6", "--seed", "1"])
    assert result.exit_code == 0
    assert "old model passes 90%, new model 60% (seed 1)" in result.stdout
    assert "Stopped early after 61 answers per model (old 55/61, new 41/61)" in result.stdout
    assert "Verdict: REGRESSED" in result.stdout
    assert "a claim is proven at 20" in result.stdout


def test_stats_simulate_reports_hitting_max_runs() -> None:
    result = runner.invoke(app, ["stats", "simulate", "0.9", "0.9", "--max-runs", "30"])
    assert result.exit_code == 0
    assert "Reached --max-runs after 30 answers per model" in result.stdout
    assert "Verdict: INCONCLUSIVE" in result.stdout


def test_stats_simulate_rejects_a_rate_above_one() -> None:
    result = runner.invoke(app, ["stats", "simulate", "1.2", "0.5"])
    assert result.exit_code == 2
    assert "between 0 and 1" in result.stderr


def test_stats_simulate_suite_counts_false_alarms_with_and_without_control() -> None:
    result = runner.invoke(
        app, ["stats", "simulate-suite", "--items", "40", "--regressed", "10", "--seed", "1"]
    )
    assert result.exit_code == 0
    assert "Simulated suite: 40 test cases, 10 made worse by 30 points (seed 1)" in result.stdout
    assert "REGRESSED: 10 (10 really worse, 0 false alarms)" in result.stdout
    assert "Answers per model:" in result.stdout
    assert "Without suite control:" in result.stdout


def test_stats_simulate_suite_rejects_more_regressions_than_items() -> None:
    result = runner.invoke(app, ["stats", "simulate-suite", "--items", "5", "--regressed", "6"])
    assert result.exit_code == 2
    assert "regressed must be between 0 and 5" in result.stderr


def test_stats_simulate_with_scores_reports_means() -> None:
    result = runner.invoke(app, ["stats", "simulate", "0.9", "0.9", "--scores"])
    assert result.exit_code == 0
    assert "old model scores 0.90 on average, new model 0.90 (seed 1)" in result.stdout
    assert (
        "Stopped early after 59 answers per model (old mean 0.89, new mean 0.91)" in result.stdout
    )
    assert "Verdict: EQUIVALENT" in result.stdout


def test_stats_simulate_suite_with_futility_counts_cases_that_looked_fine() -> None:
    result = runner.invoke(
        app,
        ["stats", "simulate-suite", "--items", "40", "--regressed", "10", "--futility", "0.1"],
    )
    assert result.exit_code == 0
    assert "REGRESSED: 10 (10 really worse, 0 false alarms)" in result.stdout
    assert "Stopped early because they looked fine:" in result.stdout


DEMO = Path(__file__).parent / "fixtures" / "prompt-demo"


def test_prompts_lists_the_demo_apps_llm_calls() -> None:
    result = runner.invoke(app, ["prompts", str(DEMO)])
    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    assert lines[0] == "bot.py:14  openai_chat  self.client.chat.completions.create"
    # bot.py takes its model and system prompt from prompts.py.
    assert lines[1:4] == [
        "  model: gpt-4o-mini",
        '  system: "Answer questions about our product from the FAQ. '
        "If unsure, say you don't know.\"",
        # ...and its question from a prompt function there.
        '  user: "Question: {question}\\nAnswer in at most 2 sentences."',
    ]
    assert (
        '  system: "You sort support tickets.\\nAnswer with one label: bug, feature, question.\\n"'
        in lines
    )
    assert "  slots: words, thread" in lines
    assert lines[-1] == (
        "Found 5 LLM calls in 3 files (read 5 Python files): 4 with all prompt text, 1 partial."
    )


def test_prompts_model_filter_and_json_file(tmp_path: Path) -> None:
    out = tmp_path / "calls.json"
    result = runner.invoke(
        app,
        [
            "prompts",
            str(DEMO),
            "--model",
            "claude-3-haiku-20240307",
            "--format",
            "json",
            "--output",
            str(out),
        ],
    )
    assert result.exit_code == 0
    assert result.stdout.splitlines() == [
        f"Wrote json report to {out}.",
        "Found 1 LLM call in 1 file (read 5 Python files): 1 with all prompt text, 0 partial.",
    ]
    data = json.loads(out.read_text())
    assert [call["api"] for call in data["calls"]] == ["anthropic"]
    assert data["calls"][0]["parts"][1]["template"] == (
        "Summarize this support thread in at most {words} words:\n{thread}"
    )


def test_cases_reads_the_demo_apps_tests() -> None:
    result = runner.invoke(app, ["cases", str(DEMO)])
    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    assert lines[:2] == [
        "bot.py:14  openai_chat  self.client.chat.completions.create  model: gpt-4o-mini",
        '  tests/test_support.py:36  question="How do I reset my password?"',
    ]
    assert '  tests/test_support.py:17  ticket="Could you add a dark mode?"' in lines
    assert lines[-1] == (
        "Found 5 test cases (5 complete) for 3 of 5 LLM calls. "
        "No case yet for 1 with slots (extract.py:9)."
    )


def test_cases_json_for_one_model(tmp_path: Path) -> None:
    out = tmp_path / "cases.json"
    result = runner.invoke(
        app,
        [
            "cases",
            str(DEMO),
            "--model",
            "claude-3-haiku-20240307",
            "--format",
            "json",
            "--output",
            str(out),
            "--skip-tests",
        ],
    )
    assert result.exit_code == 0
    assert result.stdout.splitlines()[-1] == ("Found 1 test case (1 complete) for 1 of 1 LLM call.")
    (call,) = json.loads(out.read_text())["calls"]
    assert call["cases"][0]["messages"][1] == {
        "role": "user",
        "content": "Summarize this support thread in at most 30 words:\n"
        "Customer: my order is late.\nAgent: it ships tomorrow.",
    }


def _fake_writer(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """A writer model that answers with two value sets for the slots it is asked about."""
    asked: list[str] = []

    def server(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        prompt = body["messages"][-1]["content"]
        keys = json.loads(prompt.split("exactly the keys ")[1].split(", and every")[0])
        asked.append(",".join(keys))
        sets = [{k: f"{k} {n}" for k in keys} for n in (1, 2)]
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(sets)}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 200, "completion_tokens": 40},
            },
        )

    real_init = Runner.__init__

    def init_with_fake_server(self: Runner, **options: object) -> None:
        real_init(self, transport=httpx.MockTransport(server), **options)  # type: ignore[arg-type]

    monkeypatch.setattr(Runner, "__init__", init_with_fake_server)
    return asked


def test_cases_generate_fills_calls_up_to_the_count(monkeypatch: pytest.MonkeyPatch) -> None:
    asked = _fake_writer(monkeypatch)
    result = runner.invoke(app, ["cases", str(DEMO), "--generate", "2"])
    assert result.exit_code == 0
    assert sorted(asked) == ["email", "question", "words,thread"]
    lines = result.stdout.splitlines()
    assert '  generated by ollama/qwen2.5:7b, sample 0  email="email 1"' in lines
    assert lines[-1] == ("Found 9 test cases (9 complete, 4 generated) for 4 of 5 LLM calls.")
    assert "Asked ollama/qwen2.5:7b for inputs for 3 calls: 4 generated cases." in result.stderr
    again = runner.invoke(app, ["cases", str(DEMO), "--generate", "2"])
    assert again.stdout == result.stdout
    assert "From cache: 3 answers" in again.stderr


def test_cases_generate_says_when_ollama_is_down(monkeypatch: pytest.MonkeyPatch) -> None:
    def down(requests: object) -> object:
        raise RunnerError("cannot reach Ollama")

    monkeypatch.setattr("modelbump.cli.pin_versions", down)
    result = runner.invoke(app, ["cases", str(DEMO), "--generate", "1"])
    assert result.exit_code == 1
    assert "cannot reach Ollama" in result.stderr


def test_cases_generate_warns_before_a_cloud_writer(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_writer(monkeypatch)
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    result = runner.invoke(
        app, ["cases", str(DEMO), "--generate", "1", "--generator", "groq/llama-3.1-8b-instant"]
    )
    assert result.exit_code == 0
    assert "The app's prompts leave this machine" in result.stderr


def test_oracles_lists_the_check_for_each_demo_call() -> None:
    result = runner.invoke(app, ["oracles", str(DEMO)])
    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    assert "extract.py:9  gemini  json" in lines
    assert '  why: the prompt says "JSON"' in lines
    assert "support.py:24  openai_chat  label" in lines
    assert "  why: the prompt lists labels: bug, feature, question" in lines
    assert "  checks: one of the labels, same label as before" in lines
    assert lines[-1] == "Picked oracles for 5 LLM calls: 1 json, 1 label, 3 text."


def test_oracles_json_file_for_one_model(tmp_path: Path) -> None:
    out = tmp_path / "oracles.json"
    result = runner.invoke(
        app,
        ["oracles", str(DEMO), "--model", "gpt-4o-mini", "--format", "json", "--output", str(out)],
    )
    assert result.exit_code == 0
    assert result.stdout.splitlines() == [
        f"Wrote json report to {out}.",
        "Picked oracles for 2 LLM calls: 1 label, 1 text.",
    ]
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["version"] == 1
    kinds = {(c["path"], c["kind"]) for c in data["calls"]}
    assert kinds == {("bot.py", "text"), ("support.py", "label")}
    label = next(c for c in data["calls"] if c["kind"] == "label")
    assert label["labels"] == ["bug", "feature", "question"]


def test_oracles_mentions_tool_calls_are_not_scored(tmp_path: Path) -> None:
    (tmp_path / "agent.py").write_text(
        'client.chat.completions.create(model="m", messages=[], tools=TOOLS)\n', encoding="utf-8"
    )
    result = runner.invoke(app, ["oracles", str(tmp_path)])
    assert result.exit_code == 0
    assert "  why: the call passes tools (tool calls are not scored yet)" in result.stdout
    assert result.stdout.splitlines()[-1] == (
        "Picked oracles for 1 LLM call: 1 tools. Tool calls are not scored yet."
    )


def test_oracles_with_no_calls(tmp_path: Path) -> None:
    result = runner.invoke(app, ["oracles", str(tmp_path)])
    assert result.exit_code == 0
    assert result.stdout == "Picked oracles for 0 LLM calls.\n"


def _fake_models(monkeypatch: pytest.MonkeyPatch, broken: str = "") -> list[dict[str, object]]:
    """Two fake models. The new one gives a wrong label when the ticket contains `broken`."""
    seen: list[dict[str, object]] = []

    def server(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        prompt = body["messages"][-1]["content"]
        if body["messages"][0]["content"].startswith("You grade"):
            text = "FAIL" if "WRONG" in prompt else "PASS"  # the judge
        elif prompt.startswith("Ticket"):
            # A patch that asks for the label only fixes the new model (ADR 0062).
            fixed = "label only" in body["messages"][0]["content"]
            wrong = broken and broken in prompt and "new" in body["model"] and not fixed
            text = "feature" if wrong else "bug"
        else:
            # Every answer differs, so each one is a new question for the judge.
            text = f"A short answer from {body['model']}, number {body['seed']}. Done."
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 5},
            },
        )

    real_init = Runner.__init__

    def init_with_fake_server(self: Runner, **options: object) -> None:
        real_init(self, transport=httpx.MockTransport(server), **options)  # type: ignore[arg-type]

    monkeypatch.setattr(Runner, "__init__", init_with_fake_server)
    return seen


def test_suite_writes_the_demo_suite(tmp_path: Path) -> None:
    out = tmp_path / "suite.json"
    result = runner.invoke(app, ["suite", str(DEMO), "--output", str(out)])
    assert result.exit_code == 0
    assert result.stdout.splitlines() == [
        f"Wrote 5 test cases for 3 LLM calls to {out}.",
        "  left out extract.py:9: no complete test case",
        "  left out support.py:39: no complete test case",
    ]
    data = json.loads(out.read_text(encoding="utf-8"))
    assert [c["id"] for c in data["cases"]][:2] == ["bot.py:14#1", "support.py:24#1"]


def test_suite_with_generated_cases_and_a_model_filter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fake_writer(monkeypatch)
    out = tmp_path / "suite.json"
    result = runner.invoke(
        app,
        [
            "suite",
            str(DEMO),
            "--generate",
            "2",
            "--model",
            "gemini-2.0-flash",
            "--output",
            str(out),
        ],
    )
    assert result.exit_code == 0
    assert result.stdout.splitlines() == [f"Wrote 2 test cases for 1 LLM call to {out}."]
    data = json.loads(out.read_text(encoding="utf-8"))
    assert {c["generated_by"] for c in data["cases"]} == {"ollama/qwen2.5:7b"}
    assert data["cases"][0]["oracle"]["kind"] == "json"


def _demo_suite(tmp_path: Path) -> Path:
    out = tmp_path / "suite.json"
    assert runner.invoke(app, ["suite", str(DEMO), "--output", str(out)]).exit_code == 0
    return out


def test_test_passes_when_nothing_regressed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    suite_file = _demo_suite(tmp_path)
    seen = _fake_models(monkeypatch)
    result = runner.invoke(
        app,
        [
            "test",
            str(suite_file),
            "--from",
            "ollama/old",
            "--to",
            "ollama/new",
            "--to-think",
            "none",
        ],
    )
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[0] == (
        "Compared ollama/old -> ollama/new on 5 test cases: fixed k=50 + BH "
        "(q 0.05, margin 0.10), 3 reference answers per case, "
        "free text judged by ollama/gemma3:12b."
    )
    assert lines[-1] == "Result: 0 regressed, 0 inconclusive, 5 equivalent, 0 improved."
    # 5 cases x (3 reference + 50 + 50), and the judge reads the 100 answers of each
    # of the 2 free-text cases.
    assert len(seen) == 5 * (3 + 50 + 50) + 2 * 100
    judged = [body for body in seen if body["model"] == "gemma3:12b"]
    assert len(judged) == 200
    assert {body["temperature"] for body in judged} == {0.0}
    new = [body for body in seen if body["model"] == "new"]
    assert {body["reasoning_effort"] for body in new} == {"none"}
    assert "Spent: 715 requests" in result.stderr
    # A second run reads every answer from the cache.
    again = runner.invoke(
        app,
        [
            "test",
            str(suite_file),
            "--from",
            "ollama/old",
            "--to",
            "ollama/new",
            "--to-think",
            "none",
        ],
    )
    assert again.stdout == result.stdout
    assert "Spent: 0 requests" in again.stderr


def test_test_fails_on_a_regression_and_writes_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    suite_file = _demo_suite(tmp_path)
    _fake_models(monkeypatch, broken="crashes")
    out = tmp_path / "report.json"
    result = runner.invoke(
        app,
        [
            "test",
            str(suite_file),
            "--from",
            "ollama/old",
            "--to",
            "ollama/new",
            "--format",
            "json",
            "--output",
            str(out),
        ],
    )
    assert result.exit_code == 1
    assert result.stdout.splitlines() == [
        f"Wrote json report to {out}.",
        "Result: 1 regressed, 0 inconclusive, 4 equivalent, 0 improved.",
    ]
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["cases"][0]["id"] == "support.py:24#1"
    assert data["cases"][0]["verdict"] == "REGRESSED"


def _patch_file(tmp_path: Path, patch: dict[str, object]) -> Path:
    path = tmp_path / "patch.json"
    path.write_text(json.dumps({"version": 1, "patches": [patch]}), encoding="utf-8")
    return path


LABEL_ONLY: dict[str, object] = {
    "call": "support.py:24",
    "add_system": "Reply with the label only.",
}


def test_test_with_a_patch_sends_it_to_the_new_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    suite_file = _demo_suite(tmp_path)
    _fake_models(monkeypatch, broken="crashes")
    patch = _patch_file(tmp_path, LABEL_ONLY)
    args = ["test", str(suite_file), "--from", "ollama/old", "--to", "ollama/new", "--no-judge"]
    result = runner.invoke(app, [*args, "--patch", str(patch)])
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[0].startswith(
        "Compared ollama/old -> ollama/new on 5 test cases, 3 patched for the new model:"
    )
    assert any("support.py:24#1" in line and "[patched]" in line for line in lines)
    assert lines[-1] == "Result: 0 regressed, 0 inconclusive, 5 equivalent, 0 improved."


def test_test_refuses_a_patch_that_does_not_fit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    suite_file = _demo_suite(tmp_path)
    seen = _fake_models(monkeypatch)
    patch = _patch_file(tmp_path, {"call": "nowhere.py:1", "add_system": "x"})
    args = ["test", str(suite_file), "--from", "ollama/old", "--to", "ollama/new"]
    result = runner.invoke(app, [*args, "--patch", str(patch)])
    assert result.exit_code == 2
    assert "Error: no case in the suite for call nowhere.py:1" in result.stderr
    assert seen == []


def test_repair_show_prints_a_diff_per_case(tmp_path: Path) -> None:
    suite_file = _demo_suite(tmp_path)
    patch = _patch_file(
        tmp_path,
        {
            "call": "support.py:24",
            "edits": [{"find": "one label", "replace": "exactly one label"}],
        },
    )
    result = runner.invoke(app, ["repair", "show", str(suite_file), str(patch)])
    assert result.exit_code == 0, result.output
    out = result.stdout
    assert out.count("--- support.py:24#") == 3
    assert "-Answer with one label: bug, feature, question." in out
    assert "+Answer with exactly one label: bug, feature, question." in out
    assert out.splitlines()[-1] == "The patch changes 3 test cases in 1 LLM call."


def test_repair_show_warns_when_a_call_has_one_case(tmp_path: Path) -> None:
    suite_file = _demo_suite(tmp_path)
    patch = _patch_file(tmp_path, {"call": "bot.py:14", "add_system": "Be brief."})
    result = runner.invoke(app, ["repair", "show", str(suite_file), str(patch)])
    assert result.exit_code == 0
    assert result.stdout.splitlines()[-2:] == [
        "The patch changes 1 test case in 1 LLM call.",
        "  bot.py:14 has one test case, so an edit there could touch its inputs: check the diff.",
    ]


def test_repair_show_errors(tmp_path: Path) -> None:
    suite_file = _demo_suite(tmp_path)
    patch = _patch_file(
        tmp_path, {"call": "support.py:24", "edits": [{"find": "crashes", "replace": "works"}]}
    )
    result = runner.invoke(app, ["repair", "show", str(suite_file), str(patch)])
    assert result.exit_code == 2
    assert "Error: case support.py:24#2: 'crashes' is found 0 times" in result.stderr


def _demo_report(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path]:
    """The demo suite and a JSON report where support.py:24#1 REGRESSED."""
    suite_file = _demo_suite(tmp_path)
    report = tmp_path / "report.json"
    real_init = Runner.__init__
    _fake_models(monkeypatch, broken="crashes")
    args = ["test", str(suite_file), "--from", "ollama/old", "--to", "ollama/new", "--no-judge"]
    assert runner.invoke(app, [*args, "--format", "json", "--output", str(report)]).exit_code == 1
    monkeypatch.setattr(Runner, "__init__", real_init)
    return suite_file, report


def _fake_proposer(monkeypatch: pytest.MonkeyPatch, answers: list[str]) -> list[dict[str, object]]:
    seen: list[dict[str, object]] = []

    def server(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": answers[body["seed"]]}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20},
            },
        )

    real_init = Runner.__init__

    def init_with_fake_server(self: Runner, **options: object) -> None:
        real_init(self, transport=httpx.MockTransport(server), **options)  # type: ignore[arg-type]

    monkeypatch.setattr(Runner, "__init__", init_with_fake_server)
    return seen


def test_repair_propose_writes_candidates_to_test(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    suite_file, report = _demo_report(monkeypatch, tmp_path)
    good = json.dumps({"add_system": "Reply with the label only.", "edits": [], "why": "Short."})
    seen = _fake_proposer(monkeypatch, [good, good, "no idea"])
    out = tmp_path / "proposals"
    args = ["repair", "propose", str(suite_file), str(report), "--candidates", "3"]
    result = runner.invoke(app, [*args, "--output-dir", str(out)])
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines() == [
        "support.py:24: 1 candidate, 2 refused",
        "  sample 1 refused: the same as sample 0",
        "  sample 2 refused: no JSON object in the answer",
        f"Wrote 1 candidate patch for 1 call to {out}.",
    ]
    assert {body["model"] for body in seen} == {"gemma3:12b"}
    assert "Spent: 3 requests" in result.stderr
    # The candidate is a normal patch file: it can be shown and tested.
    candidate = out / "support.py-24.00.json"
    shown = runner.invoke(app, ["repair", "show", str(suite_file), str(candidate)])
    assert shown.stdout.splitlines()[-1] == "The patch changes 3 test cases in 1 LLM call."


def test_repair_propose_with_nothing_regressed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    suite_file = _demo_suite(tmp_path)
    report = tmp_path / "report.json"
    real_init = Runner.__init__
    _fake_models(monkeypatch)
    args = ["test", str(suite_file), "--from", "ollama/old", "--to", "ollama/new", "--no-judge"]
    assert runner.invoke(app, [*args, "--format", "json", "--output", str(report)]).exit_code == 0
    monkeypatch.setattr(Runner, "__init__", real_init)
    seen = _fake_proposer(monkeypatch, [])
    result = runner.invoke(app, ["repair", "propose", str(suite_file), str(report)])
    assert result.exit_code == 0
    assert result.stdout == "No case REGRESSED in the report: nothing to repair.\n"
    assert seen == []


def test_repair_propose_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    suite_file = _demo_suite(tmp_path)
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    result = runner.invoke(app, ["repair", "propose", str(suite_file), str(bad)])
    assert result.exit_code == 2
    assert "Error: the report has no cases" in result.stderr
    result = runner.invoke(
        app, ["repair", "propose", str(suite_file), str(bad), "--model", "nowhere/x"]
    )
    assert result.exit_code == 2
    assert "Unknown endpoint" in result.stderr


def test_repair_propose_warns_before_a_cloud_tier(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    suite_file, report = _demo_report(monkeypatch, tmp_path)
    _fake_proposer(monkeypatch, ["{}"])
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    args = ["repair", "propose", str(suite_file), str(report), "--candidates", "1"]
    result = runner.invoke(app, [*args, "--model", "groq/p", "--output-dir", str(tmp_path / "out")])
    assert "The app's prompts leave this machine" in result.stderr


def test_test_budget_says_how_to_continue(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    suite_file = _demo_suite(tmp_path)
    _fake_models(monkeypatch)
    result = runner.invoke(
        app,
        [
            "test",
            str(suite_file),
            "--from",
            "ollama/old",
            "--to",
            "ollama/new",
            "--budget-requests",
            "50",
        ],
    )
    assert result.exit_code == 1
    assert "could not be run" in result.stdout
    assert "run the same command with a higher limit" in result.stderr


def test_test_errors_before_running(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    result = runner.invoke(app, ["test", str(bad), "--from", "ollama/a", "--to", "ollama/b"])
    assert result.exit_code == 2
    assert "not a version 1 suite file" in result.stderr

    empty = tmp_path / "empty.json"
    empty.write_text('{"version": 1, "cases": []}', encoding="utf-8")
    result = runner.invoke(app, ["test", str(empty), "--from", "ollama/a", "--to", "ollama/b"])
    assert result.exit_code == 2
    assert "the suite has no test cases" in result.stderr

    suite_file = _demo_suite(tmp_path)
    result = runner.invoke(
        app, ["test", str(suite_file), "--from", "nowhere/a", "--to", "ollama/b"]
    )
    assert result.exit_code == 2
    assert "Error:" in result.stderr

    def not_pulled(requests: object) -> object:
        raise RunnerError("ollama/b: this model is not pulled. Run: ollama pull b")

    monkeypatch.setattr("modelbump.cli.pin_versions", not_pulled)
    result = runner.invoke(app, ["test", str(suite_file), "--from", "ollama/a", "--to", "ollama/b"])
    assert result.exit_code == 2
    assert "Run: ollama pull b" in result.stderr


def test_test_warns_before_a_cloud_tier(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    suite_file = _demo_suite(tmp_path)
    _fake_models(monkeypatch)
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    result = runner.invoke(
        app,
        # One allowed request: the warning comes first, and no request waits for Groq's pacing.
        [
            "test",
            str(suite_file),
            "--from",
            "ollama/old",
            "--to",
            "groq/new",
            "--runs",
            "1",
            "--reference",
            "1",
            "--budget-requests",
            "1",
        ],
    )
    assert "The app's prompts leave this machine" in result.stderr


def test_test_without_the_judge(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    suite_file = _demo_suite(tmp_path)
    seen = _fake_models(monkeypatch)
    result = runner.invoke(
        app,
        ["test", str(suite_file), "--from", "ollama/old", "--to", "ollama/new", "--no-judge"],
    )
    assert result.exit_code == 0
    assert result.stdout.splitlines()[0].endswith("3 reference answers per case.")
    assert len(seen) == 5 * (3 + 50 + 50)


def test_test_skips_the_judge_when_no_case_is_free_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    out = tmp_path / "suite.json"
    assert (
        runner.invoke(
            app, ["suite", str(DEMO), "--model", "gpt-4o-mini", "--output", str(out)]
        ).exit_code
        == 0
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    data["cases"] = [c for c in data["cases"] if c["oracle"]["kind"] == "label"]
    out.write_text(json.dumps(data), encoding="utf-8")
    asked: list[list[str]] = []

    def pin(requests: list[ChatRequest]) -> list[ChatRequest]:
        asked.append([r.model for r in requests])
        return list(requests)

    monkeypatch.setattr("modelbump.cli.pin_versions", pin)
    seen = _fake_models(monkeypatch)
    result = runner.invoke(app, ["test", str(out), "--from", "ollama/old", "--to", "ollama/new"])
    assert result.exit_code == 0
    assert asked == [["ollama/old", "ollama/new"]]
    assert all(body["model"] != "gemma3:12b" for body in seen)


def test_judge_sheet_and_agreement_end_to_end(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    suite_file = _demo_suite(tmp_path)
    _fake_models(monkeypatch)
    report = tmp_path / "report.json"
    result = runner.invoke(
        app,
        [
            "test",
            str(suite_file),
            "--from",
            "ollama/old",
            "--to",
            "ollama/new",
            "--format",
            "json",
            "--output",
            str(report),
        ],
    )
    assert result.exit_code == 0
    case = next(
        c
        for c in json.loads(report.read_text(encoding="utf-8"))["cases"]
        if c["id"] == "bot.py:14#1"
    )
    assert case["reference_answer"] == "A short answer from old, number 0. Done."
    assert case["messages"][0]["role"] == "system"
    sheet, key = tmp_path / "sheet.csv", tmp_path / "key.json"
    made = runner.invoke(
        app,
        ["judge", "sheet", str(report), "--output", str(sheet), "--key", str(key), "--size", "6"],
    )
    assert made.exit_code == 0, made.output
    # The fake judge passes everything, so the FAIL half is filled with PASSes.
    assert made.stdout.splitlines() == [
        f"Wrote 6 rows (6 answers: 6 judged PASS, 0 FAIL) to {sheet}, and the key to {key}.",
        "The report had 200 PASS and 0 FAIL. Fill in your_label with PASS or FAIL, "
        "without looking at the key.",
    ]
    text = sheet.read_text(encoding="utf-8")
    assert text.splitlines()[0] == "item,prompt,reference,answer,your_label,note"
    labelled = text.replace(",,\n", ",PASS,\n").replace(",,\r\n", ",PASS,\r\n")
    sheet.write_text(labelled, encoding="utf-8")
    checked = runner.invoke(app, ["judge", "agreement", str(sheet), str(key)])
    assert checked.exit_code == 0, checked.output
    assert checked.stdout.splitlines()[:4] == [
        "Judge: ollama/gemma3:12b",
        "Labelled 6 answers.",
        "When the judge said PASS, you agreed 100% (6/6, 95% CI 52%-100%).",
        "When the judge said FAIL, you agreed no answers.",
    ]


def test_judge_commands_report_bad_files(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("[]", encoding="utf-8")
    result = runner.invoke(app, ["judge", "sheet", str(bad), "--output", str(tmp_path / "s.csv")])
    assert result.exit_code == 2
    assert "is not a `modelbump test --format json` report" in result.stderr
    sheet = tmp_path / "s.csv"
    sheet.write_text("item,your_label\n", encoding="utf-8")
    key = tmp_path / "k.json"
    key.write_text('{"version": 1, "items": [], "population": {}}', encoding="utf-8")
    result = runner.invoke(app, ["judge", "agreement", str(sheet), str(key)])
    assert result.exit_code == 2
    assert "has no labels yet" in result.stderr


def test_judge_fresh_sheet_and_rejudged_agreement(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    suite_file = _demo_suite(tmp_path)
    _fake_models(monkeypatch)
    report = tmp_path / "report.json"
    args = ["test", str(suite_file), "--from", "ollama/old", "--to", "ollama/new"]
    assert runner.invoke(app, [*args, "--format", "json", "--output", str(report)]).exit_code == 0
    sheet1, key1 = tmp_path / "s1.csv", tmp_path / "k1.json"
    assert (
        runner.invoke(
            app,
            [
                "judge",
                "sheet",
                str(report),
                "--output",
                str(sheet1),
                "--key",
                str(key1),
                "--size",
                "4",
            ],
        ).exit_code
        == 0
    )
    sheet2, key2 = tmp_path / "s2.csv", tmp_path / "k2.json"
    fresh = runner.invoke(
        app,
        [
            "judge",
            "sheet",
            str(report),
            "--output",
            str(sheet2),
            "--key",
            str(key2),
            "--size",
            "4",
            "--exclude-key",
            str(key1),
        ],
    )
    assert fresh.exit_code == 0, fresh.output
    assert "Left out 4 answers that earlier sheets hold." in fresh.stdout
    sheet1.write_text(
        sheet1.read_text(encoding="utf-8")
        .replace(",,\r\n", ",PASS,\r\n")
        .replace(",,\n", ",PASS,\n"),
        encoding="utf-8",
    )
    checked = runner.invoke(
        app, ["judge", "agreement", str(sheet1), str(key1), "--report", str(report)]
    )
    assert checked.exit_code == 0, checked.output
    assert checked.stdout.splitlines()[0] == "Judge: ollama/gemma3:12b"
    assert "Verdicts from another report" in checked.stdout


def test_judge_probes_and_probe_check_end_to_end(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    suite_file = _demo_suite(tmp_path)
    seen = _fake_models(monkeypatch)
    report = tmp_path / "report.json"
    args = ["test", str(suite_file), "--from", "ollama/old", "--to", "ollama/new"]
    assert runner.invoke(app, [*args, "--format", "json", "--output", str(report)]).exit_code == 0
    sheet, key = tmp_path / "probes.csv", tmp_path / "probes.json"
    made = runner.invoke(
        app,
        [
            "judge",
            "probes",
            str(report),
            "--output",
            str(sheet),
            "--key",
            str(key),
            "--per-kind",
            "1",
        ],
    )
    assert made.exit_code == 0, made.output
    data = json.loads(key.read_text(encoding="utf-8"))
    cases = data["cases"]
    assert cases >= 1
    assert made.stdout.splitlines() == [
        f"Wrote {5 * cases} probes for {cases} free-text cases to {sheet}, and the key to {key}.",
        f"The judge said PASS {5 * cases}, FAIL 0.",
        "Fill in your_label with PASS or FAIL, without looking at the key.",
    ]
    breaker = [b for b in seen if "You edit answers" in json.dumps(b["messages"])]
    assert len(breaker) == 5 * cases
    assert {b["model"] for b in breaker} == {"qwen2.5:7b"}
    with sheet.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["your_label"] = "FAIL"
    with sheet.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    checked = runner.invoke(app, ["judge", "probe-check", str(sheet), str(key)])
    assert checked.exit_code == 0, checked.output
    lines = checked.stdout.splitlines()
    assert lines[0] == "Judge: ollama/gemma3:12b; probes written by ollama/qwen2.5:7b."
    assert lines[-1].startswith(f"All broken kinds: judge caught 0/{4 * cases} (0%")
    again = runner.invoke(app, ["judge", "probes", str(tmp_path / "suite.json")])
    assert again.exit_code == 2
    assert "is from an older ModelBump" in again.output or "not a" in again.output
