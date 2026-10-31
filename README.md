# ModelBump

**Dependabot for LLM models.** ModelBump finds the AI models your code depends on, warns you before a provider retires them, and tests the replacement on your app's own prompts. Later versions will also repair prompts that regress and open the upgrade pull request for you.

[![PyPI](https://img.shields.io/pypi/v/modelbump)](https://pypi.org/project/modelbump/)
[![CI](https://github.com/imhammad/modelbump/actions/workflows/ci.yml/badge.svg)](https://github.com/imhammad/modelbump/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.12%20%7C%203.13-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-Apache%202.0-green)](https://github.com/imhammad/modelbump/blob/main/LICENSE)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-261230)](https://github.com/astral-sh/ruff)
[![Checked with mypy](https://img.shields.io/badge/mypy-strict-2a6db2)](https://mypy-lang.org/)

> **Status:** `v0.5.0` ships the first three stages. **Scan** finds retiring models, as a command-line tool and a GitHub Action. **Test** builds a regression suite from your app's LLM calls and compares the old and new model on it (`modelbump suite`, `modelbump test`). **Repair** proposes prompt fixes for the cases that regressed and accepts one only if fresh answers show nothing got worse (`modelbump repair`). The upgrade pull request is still being built; see the [roadmap](#roadmap).

## The problem

Apps built on hosted LLMs (OpenAI, Anthropic, Google, ...) depend on specific model versions, and providers retire those versions on a schedule. When a model is retired, an app either breaks outright or keeps running while quietly producing worse answers, because prompts tuned for the old model don't transfer cleanly to the new one.

A 2026 study of 22,555 migration commits across 17,703 open-source repositories found that:

- **82%** of migrations happened *after* the old model was already shut down (our own re-check on a larger dataset finds a smaller share, but still more than half),
- model identifiers were **hard-coded in 94%** of migrating apps, and
- only **4%** of migrations came with any evaluation suite.

*Source: H. L. Kim, "When the Model Retires: An Empirical Study of LLM Migration in Open-Source Applications", arXiv:2609.31288, 2026.*

## Install and scan

Requires Python 3.12 or newer.

```bash
pip install modelbump
modelbump scan .
```

Or run it once without installing, with [uv](https://docs.astral.sh/uv/):

```bash
uvx modelbump scan .
```

Each line of the report gives the file, line and column, the model ID, its status (`OK`, `RETIRING_SOON`, `DEPRECATED`, `RETIRED` or `UNKNOWN`), the shutdown date with the suggested replacement, and where the ID sits (a call argument, an assignment, a config value, a comment, ...).

Useful options:

| Option | What it does |
|--------|--------------|
| `--fail-within 30` | Exit with code 1 if a model is retired or shuts down within 30 days (for CI) |
| `--skip-comments` | Leave out IDs that only describe a model: comments, docstrings, sentences, price tables |
| `--skip-tests` | Leave out test files and test folders |
| `--exclude PATTERN` | Skip matching paths, e.g. `--exclude '*.ipynb'` (repeat for more) |
| `--format json` / `--format sarif` | Machine-readable reports; SARIF shows up in GitHub code scanning |

Run `modelbump scan --help` for the rest.

## GitHub Action

```yaml
name: ModelBump
on:
  pull_request:
  schedule:
    - cron: "0 6 * * 1"  # every Monday, to catch new retirement notices

permissions:
  contents: read
  security-events: write  # to upload findings to code scanning

jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: imhammad/modelbump@v0.1.0
        with:
          fail-within: "30"
          skip-comments: "true"
```

All inputs are listed in the [scanner documentation](https://imhammad.github.io/modelbump/architecture/scanner/).

## How well the scanner works

We ran the scanner on 100 real projects, each at the commit just before it moved off a retired model, and labelled a sample of 250 findings by hand ([evaluation details](https://imhammad.github.io/modelbump/research/scanner-eval/)):

| Setting | Finds the old model's lines (recall) | Findings that are real dependencies (precision) |
|---------|------|------|
| Default | 97.7% | 47.9% |
| `--skip-comments --skip-tests` | 82.0% | 75.2% |

Replayed on those 100 projects, the scanner flagged 96 before they migrated. The default is tuned not to miss anything; the two flags trade some misses for a much quieter report.

## Is the new model worse, or is it just randomness?

LLM answers change from run to run, so one run of each model proves little. Give the statistics engine how often each model passed a test case, and it says whether the difference is real:

```console
$ modelbump stats item 45/50 30/50
Old model: 45/50 passed (90.0%)
New model: 30/50 passed (60.0%)
Difference (new - old): -30.0 points, 90% interval -43.8 to -14.5
Verdict: REGRESSED (the new model is worse on this test case)
```

It also stops asking as soon as the answer is clear, and controls false alarms across a whole suite. On real answers from two local models (Qwen 2.5 against itself), a single-run diff flagged 2.6 of 60 unchanged test cases as worse on every run; the engine's suite methods flagged almost none ([results](https://imhammad.github.io/modelbump/research/stats-real/), [how it works](https://imhammad.github.io/modelbump/architecture/stats/)).

## Test the new model on your app

`modelbump suite` finds the LLM calls in your Python code, reads their prompts, and makes test cases: from your own code where it calls them with real values, or with inputs written by a local model. Each case gets a check that fits its output: JSON keys and types, a label from a list, or free text graded by an LLM judge. `modelbump test` then runs both models on every case several times and decides each one with the statistics engine.

```console
$ modelbump suite . --generate 2 --output suite.json
$ modelbump test suite.json --from ollama/qwen2.5:7b --to ollama/qwen3:8b --to-think none
Compared ollama/qwen2.5:7b -> ollama/qwen3:8b on 9 test cases: fixed k=50 + BH ...
REGRESSED    support.py:24#1  label  old 1.00 -> new 0.12  (50 runs)
...
```

It exits with code 1 when a case regressed, so it can gate CI. Everything runs on free local models through [Ollama](https://ollama.com/) by default.

On 40 real open-source apps, drawn at random from projects that really migrated, it built and ran 70 test cases. The free-text judge agreed with blind hand labels on 83% of answers (87% of its PASSes and 68% of its FAILs were right), and it caught 22 of 24 answers broken on purpose ([results](https://imhammad.github.io/modelbump/research/suites/), [how suites work](https://imhammad.github.io/modelbump/architecture/suite/)).

## Repair a prompt that regressed

When a case regresses, the fix is often a line in the prompt. `modelbump repair propose` asks a local model for candidate fixes, using the failing answers. `modelbump repair run` screens them, then confirms the best one on fresh answers. It accepts a fix only if every test case of that LLM call is statistically no worse than with the old model.

```console
$ modelbump test suite.json --from ollama/qwen2.5:7b --to ollama/qwen3:8b --to-think none --format json --output report.json
$ modelbump repair propose suite.json report.json
$ modelbump repair run suite.json modelbump-proposals --from ollama/qwen2.5:7b --to ollama/qwen3:8b --to-think none
$ modelbump test suite.json --from ollama/qwen2.5:7b --to ollama/qwen3:8b --to-think none --patch modelbump-repair.json
```

On 6 real regressions in two model migrations, it repaired 2. A plain "rewrite this prompt for the new model" repaired none. The safety check stopped two fixes that looked good at first: one failed on fresh answers, and one broke another input ([results](https://imhammad.github.io/modelbump/research/repair/), [how repair works](https://imhammad.github.io/modelbump/architecture/repair/)).

## The plan

| Stage | What it does | Status |
|-------|--------------|--------|
| **Scan** | Static analysis finds every model ID in your code and config, checks it against a registry of provider retirement dates, and fails CI *before* the shutdown date. | Available (`v0.1.0`) |
| **Test** | Builds an app-specific regression suite from your prompts and tests, with an oracle per output type and a calibrated LLM judge for free text. | Available (`v0.4.0`) |
| **Compare** | Runs old vs. new model with sequential statistical tests, separating real regressions from normal LLM randomness, within a cost budget. | Available (`v0.4.0`, `modelbump test`) |
| **Repair** | Searches for prompt edits that fix regressions without breaking anything that already worked. | Available (`v0.5.0`, `modelbump repair`) |
| **Bump** | Opens a ready-to-review PR with the new model, repaired prompts, the regression suite, and an evidence report. | Planned |

## Development

Requires [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/imhammad/modelbump.git
cd modelbump
uv sync
uv run modelbump --version
uv run pytest
```

## Roadmap

- [x] **Phase 0:** Foundations: packaging, CI, pre-commit, branch protection
- [x] **Phase 1:** Migration dataset + model retirement registry
- [x] **Phase 2:** Scanner + GitHub Action (`v0.1.0`)
- [x] **Phase 3:** Model runner with caching and cost budgets (`v0.2.0`)
- [x] **Phase 4:** Statistical comparison engine (`v0.3.0`)
- [x] **Phase 5:** Regression suite synthesis + LLM-judge calibration (`v0.4.0`)
- [x] **Phase 6:** Prompt repair (`v0.5.0`)
- [ ] **Phase 7:** End-to-end `modelbump bump` + `v1.0.0`

## Research

ModelBump is also a research project: an empirical study of how open-source LLM apps migrate off retired models (paper in preparation), and later a paper on the tool itself. Research notes, protocols and results are in the [research section of the docs](https://imhammad.github.io/modelbump/research/).

## License

[Apache License 2.0](https://github.com/imhammad/modelbump/blob/main/LICENSE)
