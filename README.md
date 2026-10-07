# ModelBump

**Dependabot for LLM models.** ModelBump finds the AI models your code depends on, warns you before a provider retires them, tests the old model against its replacement with statistical rigor, repairs prompts that regress, and opens the upgrade pull request for you.

[![CI](https://github.com/imhammad/modelbump/actions/workflows/ci.yml/badge.svg)](https://github.com/imhammad/modelbump/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.12%20%7C%203.13-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-Apache%202.0-green)](LICENSE)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-261230)](https://github.com/astral-sh/ruff)
[![Checked with mypy](https://img.shields.io/badge/mypy-strict-2a6db2)](https://mypy-lang.org/)

> **Status:** early development (Phase 0: foundations). Not ready for use yet. Follow along in the [roadmap](#roadmap).

## The problem

Apps built on hosted LLMs (OpenAI, Anthropic, Google, ...) depend on specific model versions, and providers retire those versions on a schedule. When a model is retired, an app either breaks outright or keeps running while quietly producing worse answers, because prompts tuned for the old model don't transfer cleanly to the new one.

A 2026 study of 22,555 migration commits across 17,703 open-source repositories found that:

- **82%** of migrations happened *after* the old model was already shut down,
- model identifiers were **hard-coded in 94%** of migrating apps, and
- only **4%** of migrations came with any evaluation suite.

*Source: H. L. Kim, "When the Model Retires: An Empirical Study of LLM Migration in Open-Source Applications", arXiv:2609.31288, 2026.*

## What ModelBump will do

| Stage | What it does |
|-------|--------------|
| **Scan** | Static analysis finds every model ID in your code and config, checks it against a registry of provider retirement dates, and fails CI *before* the shutdown date. |
| **Test** | Builds an app-specific regression suite from your prompts, tests, and (optionally) logs. |
| **Compare** | Runs old vs. new model with sequential statistical tests, separating real regressions from normal LLM randomness, within a cost budget. |
| **Repair** | Searches for prompt edits that fix regressions without breaking anything that already worked. |
| **Bump** | Opens a ready-to-review PR with the new model, repaired prompts, the regression suite, and an evidence report. |

## Quickstart (development)

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
- [ ] **Phase 1:** Migration dataset + model retirement registry
- [ ] **Phase 2:** Scanner + GitHub Action (`v0.1.0`)
- [ ] **Phase 3:** Model runner with caching and cost budgets
- [ ] **Phase 4:** Statistical comparison engine
- [ ] **Phase 5:** Regression suite synthesis + LLM-judge calibration
- [ ] **Phase 6:** Prompt repair
- [ ] **Phase 7:** End-to-end `modelbump bump` + `v1.0.0`

## Research

ModelBump is also a research project. The goal is a peer-reviewed paper evaluating each stage on real migration history and real open-source applications. Research notes will live in `docs/research/`.

## License

[Apache License 2.0](LICENSE)
