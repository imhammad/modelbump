# ADR 0001: Python 3.12+, uv, and a src layout

- **Status:** Accepted
- **Date:** 2026-10-07

## Context

ModelBump combines static analysis, LLM API calls and statistics. The LLM, data and research ecosystems are strongest in Python. We need reproducible environments across a MacBook (Apple Silicon) and Linux/macOS CI runners.

## Decision

- **Python 3.12+**, tested on 3.12 and 3.13 in CI.
- **uv** manages Python versions, the virtual environment, dependencies and the lockfile (`uv.lock`).
- **src layout** (`src/modelbump/`), so tests run against the installed package, not loose files in the working directory.
- **Typer** for the CLI, **pytest** for tests, **ruff** for lint and format, **mypy --strict** for types.

## Alternatives considered

- **pip + venv + requirements.txt:** no lockfile by default, slower, more manual steps.
- **Poetry:** mature, but slower and has its own non-standard config history; uv follows the standard `pyproject.toml` fields.
- **Flat layout:** simpler, but tests can accidentally import the local folder instead of the installed package.

## Consequences

- One command (`uv sync`) reproduces the exact environment anywhere; CI uses `uv sync --locked` to fail if the lockfile is stale.
- Contributors need uv installed.
