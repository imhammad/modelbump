"""Tests for running a suite on two models, with fake model servers (ADR 0053)."""

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from modelbump.oracles import OracleChoice, OutputKind
from modelbump.runner import Budget, Runner
from modelbump.stats import Verdict
from modelbump.suite import Method, Settings, Suite, SuiteCase, SuiteRun, run_suite_on_models
from modelbump.suite.report import method_line, render_run_json, render_run_text, run_summary
from modelbump.suite.run import FIXED_UP_TO, request

OLD = "ollama/old"
NEW = "ollama/new"
LABELS = OracleChoice(OutputKind.LABEL, "r", ("bug", "feature", "question"))
TEXT = OracleChoice(OutputKind.TEXT, "r")


def make_case(name: str, oracle: OracleChoice = LABELS) -> SuiteCase:
    return SuiteCase(
        id=f"app.py:1#{name}",
        path="app.py",
        line=1,
        api="openai_chat",
        app_model="gpt-4o-mini",
        oracle=oracle,
        source="tests/test_app.py:3",
        generated_by=None,
        messages=(("system", "Answer with one label: bug, feature, question."), ("prompt", name)),
    )


Answers = Callable[[str, str, int], str]


def fake_runner(
    answer: Answers, budget: Budget | None = None
) -> tuple[Runner, list[dict[str, Any]]]:
    seen: list[dict[str, Any]] = []

    def server(http_request: httpx.Request) -> httpx.Response:
        body = json.loads(http_request.content)
        seen.append(body)
        text = answer(body["model"], body["messages"][-1]["content"], body["seed"])
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2},
            },
        )

    return Runner(transport=httpx.MockTransport(server), budget=budget), seen


def run(suite: Suite, answer: Answers, **options: object) -> tuple[SuiteRun, list[dict[str, Any]]]:
    runner, seen = fake_runner(answer)
    settings = Settings(old=OLD, new=NEW, **options)  # type: ignore[arg-type]
    return asyncio.run(run_suite_on_models(suite, runner, settings)), seen


def breaks_on(broken: str) -> Answers:
    """The new model gives the wrong label for one case; everything else matches."""

    def answer(model: str, prompt: str, seed: int) -> str:
        if model == "new" and prompt == broken:
            return "feature"
        return "Bug."

    return answer


SUITE = Suite(tuple(make_case(name) for name in ("crash", "login", "slow")))


# --- Requests --------------------------------------------------------------------


def test_request_uses_the_chosen_model_seed_and_settings() -> None:
    settings = Settings(
        old=OLD, new=NEW, temperature=0.5, max_tokens=20, new_think="none", new_version="d1"
    )
    old = request(SUITE.cases[0], settings, "old", 4)
    new = request(SUITE.cases[0], settings, "new", 4)
    assert (old.model, new.model) == (OLD, NEW)
    assert old.seed == old.sample == 4
    assert old.messages[1].role == "user"  # "prompt" is sent as the user message
    assert (old.reasoning_effort, new.reasoning_effort) == (None, "none")
    assert (old.model_version, new.model_version) == ("", "d1")
    assert (new.temperature, new.max_tokens) == (0.5, 20)


def test_settings_check_their_numbers() -> None:
    with pytest.raises(ValueError, match="runs"):
        Settings(old=OLD, new=NEW, runs=0)
    with pytest.raises(ValueError, match="reference"):
        Settings(old=OLD, new=NEW, reference=0)


def test_auto_follows_adr_0047() -> None:
    assert Settings(old=OLD, new=NEW, runs=FIXED_UP_TO).chosen is Method.FIXED
    assert Settings(old=OLD, new=NEW, runs=FIXED_UP_TO + 1).chosen is Method.SEQUENTIAL
    assert Settings(old=OLD, new=NEW, runs=5, method=Method.SEQUENTIAL).chosen is (
        Method.SEQUENTIAL
    )


# --- Fixed k + BH ----------------------------------------------------------------


def test_fixed_finds_the_broken_case_and_clears_the_others() -> None:
    result, seen = run(SUITE, breaks_on("login"), runs=50)
    verdicts = {r.case.id: r.verdict for r in result.cases}
    assert verdicts == {
        "app.py:1#crash": Verdict.EQUIVALENT,
        "app.py:1#login": Verdict.REGRESSED,
        "app.py:1#slow": Verdict.EQUIVALENT,
    }
    assert result.regressed
    # Per case: 3 reference answers, then 50 from each model.
    assert len(seen) == 3 * (3 + 50 + 50)
    login = result.cases[1]
    assert (login.old_mean, login.new_mean) == (1.0, 0.0)
    assert login.new_failures == [("same label as before (bug)", 50)]
    # Reference answers (samples 0-2) are never scored; compared ones start at 3.
    assert [a.sample for a in login.old][:2] == [3, 4]
    assert [a.sample for a in login.new][-1] == 52


def test_fixed_with_few_runs_is_inconclusive() -> None:
    result, _ = run(SUITE, breaks_on("nothing"), runs=5)
    assert result.counts == {Verdict.INCONCLUSIVE: 3}
    assert not result.regressed


def test_fixed_improvement() -> None:
    def answer(model: str, prompt: str, seed: int) -> str:
        # The old model gives the reference label only on its first three answers.
        return "bug" if model == "new" or seed < 3 else "feature"

    result, _ = run(Suite((make_case("x"),)), answer, runs=50)
    assert result.cases[0].verdict is Verdict.IMPROVED


# --- Sequential + e-BH -----------------------------------------------------------


def test_sequential_stops_early_and_finds_the_broken_case() -> None:
    result, seen = run(SUITE, breaks_on("crash"), runs=200, method=Method.SEQUENTIAL)
    verdicts = {r.case.id: r.verdict for r in result.cases}
    assert verdicts["app.py:1#crash"] is Verdict.REGRESSED
    assert verdicts["app.py:1#login"] is Verdict.EQUIVALENT
    assert len(result.cases[0].new) < 200  # stopped as soon as it was clear
    assert len(seen) < 3 * (3 + 2 * 200)


# --- Errors and the budget -------------------------------------------------------


def test_a_failing_case_is_reported_and_the_rest_still_run() -> None:
    def answer(model: str, prompt: str, seed: int) -> str:
        return "Bug."

    def server(http_request: httpx.Request) -> httpx.Response:
        body = json.loads(http_request.content)
        if body["messages"][-1]["content"] == "login":
            return httpx.Response(400, json={"error": {"message": "bad request"}})
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": answer("", "", 0)}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    for method in (Method.FIXED, Method.SEQUENTIAL):
        runner = Runner(transport=httpx.MockTransport(server))
        settings = Settings(old=OLD, new=NEW, runs=50, method=method)
        result = asyncio.run(run_suite_on_models(SUITE, runner, settings))
        login = result.cases[1]
        assert login.error is not None
        assert result.errors == 1
        assert result.counts[Verdict.EQUIVALENT] == 2
        text = render_run_text(result)
        assert f"NOT RUN      app.py:1#login  label  {login.error}" in text
        assert text.splitlines()[-1].endswith("1 could not be run.")


def test_budget_stops_the_run() -> None:
    runner, _ = fake_runner(breaks_on("x"), Budget(max_requests=10))
    settings = Settings(old=OLD, new=NEW, runs=50)
    result = asyncio.run(run_suite_on_models(SUITE, runner, settings))
    assert result.errors == 3


def test_an_empty_suite_is_an_error() -> None:
    runner, _ = fake_runner(breaks_on("x"))
    with pytest.raises(ValueError, match="no test cases"):
        asyncio.run(run_suite_on_models(Suite(()), runner, Settings(old=OLD, new=NEW)))


# --- Reports ---------------------------------------------------------------------


def test_text_report_puts_regressions_first() -> None:
    suite = Suite((*SUITE.cases, make_case("long", TEXT)))
    result, _ = run(suite, breaks_on("slow"), runs=50)
    lines = render_run_text(result).splitlines()
    assert lines[0] == (
        "Compared ollama/old -> ollama/new on 4 test cases: fixed k=50 + BH "
        "(q 0.05, margin 0.10), 3 reference answers per case."
    )
    assert lines[1] == "REGRESSED    app.py:1#slow  label  old 1.00 -> new 0.00  (50 runs)"
    assert lines[2] == "             new model failed: same label as before (bug) (50/50)"
    assert lines[3].startswith("EQUIVALENT   app.py:1#")
    assert lines[-1] == "Result: 1 regressed, 0 inconclusive, 3 equivalent, 0 improved."
    assert run_summary(result) == lines[-1]


def test_method_line_for_sequential_and_one_reference() -> None:
    result, _ = run(
        Suite((make_case("a"),)), breaks_on("x"), runs=3, reference=1, method=Method.SEQUENTIAL
    )
    assert method_line(result) == (
        "Compared ollama/old -> ollama/new on 1 test case: sequential + e-BH, up to 3 "
        "(q 0.05, margin 0.10), 1 reference answer per case."
    )


def test_json_report_has_every_answer() -> None:
    result, _ = run(Suite((make_case("crash"),)), breaks_on("crash"), runs=50)
    data = json.loads(render_run_json(result))
    assert data["version"] == 1
    assert (data["old"], data["new"], data["method"], data["runs"]) == (OLD, NEW, "fixed", 50)
    assert data["counts"]["REGRESSED"] == 1
    (only,) = data["cases"]
    assert only["verdict"] == "REGRESSED"
    assert only["new_failures"] == {"same label as before (bug)": 50}
    assert len(only["answers"]) == 100
    assert only["answers"][-1] == {
        "model": "new",
        "sample": 52,
        "score": 0.0,
        "failed": ["same label as before (bug)"],
        "judge": None,
        "text": "feature",
    }


# --- The judge (ADR 0054) --------------------------------------------------------

JUDGE = "ollama/judge"


def judging(new_is_wrong: bool, unclear: bool = False) -> Answers:
    """Both models write similar text; the judge fails the new model's answers."""

    def answer(model: str, prompt: str, seed: int) -> str:
        if model == "judge":
            if unclear:
                return "Hard to say."
            return "FAIL" if new_is_wrong and "from new" in prompt else "PASS"
        return f"A fine answer from {model}, take {seed}."

    return answer


def test_judge_fails_new_text_answers_and_the_case_regresses() -> None:
    suite = Suite((make_case("long", TEXT), make_case("crash")))
    result, seen = run(suite, judging(new_is_wrong=True), runs=50, judge=JUDGE)
    text, label = result.cases
    assert text.verdict is Verdict.REGRESSED
    assert {a.judge for a in text.new} == {"FAIL"}
    assert {a.judge for a in text.old} == {"PASS"}
    assert text.new_failures[0] == ("judge: as good as the reference", 50)
    # The label case is not sent to the judge.
    assert label.new[0].judge is None
    assert sum(body["model"] == "judge" for body in seen) == 100
    # The judge reads the first reference answer, never the answer's model name.
    judge_prompt = next(b for b in seen if b["model"] == "judge")["messages"][1]["content"]
    assert "## Reference answer\nA fine answer from old, take 0." in judge_prompt
    assert "ollama/" not in judge_prompt
    assert "free text judged by ollama/judge" in render_run_text(result).splitlines()[0]


def test_judge_in_sequential_rounds() -> None:
    suite = Suite((make_case("long", TEXT),))
    result, _ = run(
        suite, judging(new_is_wrong=True), runs=200, method=Method.SEQUENTIAL, judge=JUDGE
    )
    (text,) = result.cases
    assert text.verdict is Verdict.REGRESSED
    assert len(text.new) < 200


def test_unclear_judge_keeps_property_scores() -> None:
    result, _ = run(
        Suite((make_case("long", TEXT),)), judging(False, unclear=True), runs=50, judge=JUDGE
    )
    (text,) = result.cases
    assert {a.judge for a in text.new} == {"unclear"}
    assert text.verdict is Verdict.EQUIVALENT
    data = json.loads(render_run_json(result))
    assert data["judge"] == JUDGE
    assert data["cases"][0]["answers"][0]["judge"] == "unclear"
