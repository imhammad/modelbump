# ADR 0057: Build the benchmark corpus from apps that really migrated, as they were before the migration

- **Status:** Accepted
- **Date:** 2026-10-29

## Context

Phase 5's definition of done needs `modelbump test` to work on a corpus of 30 to 50 real LLM apps, and needs about 200 hand labels for the judge. Until now the synthesizer was only tried on five well-known apps picked by hand ([ADR 0049](0049-follow-prompts-across-files-classes-and-functions.md)). A corpus picked by hand would favour apps that look good and would be hard to defend in a paper.

We already have a population of real apps that depend on a model: the migration commits of Paper 1. The scanner evaluation ([ADR 0029](0029-scanner-evaluation-set.md)) drew a random order of them (seed 2030) and downloaded each repository as it was just **before** its migration commit. Those apps used a model that was being retired, and their owners did move off it, which is exactly the situation ModelBump is for.

## Decision

`research.corpus.build` (a new research folder; the frozen Paper 1 code is only imported) builds the corpus:

1. **Same frame and order as the scanner evaluation.** Migration commits from the RQ4 sample that removed a line naming the old model, in the seed-2030 order. The 100 snapshots that evaluation downloaded are reused from disk. Later ones are downloaded the same way (the parent commit, only the files the scanner reads) and cached in `research/data/corpus/`.
2. **Screening, in that order.** An app joins when:
   - its repository is not in the corpus yet (one snapshot per repository, checked before downloading);
   - it has Python files (the synthesizer reads Python only);
   - outside its tests, ModelBump finds at least one LLM call that does not pass tools and has written prompt text. A library or wrapper that only passes prompts through has none.
3. **Stop at 40 apps** (`--target`), or after 400 screened snapshots (`--max-screened`), so a run always ends.
4. **No model is called in this step.** For each app it records what the synthesizer finds: Python files, calls by API, calls by oracle kind, calls with prompt text, complete calls, fixed prompts, calls with slots, calls with test inputs from the app's own code, and the models the code names. Every screened snapshot is kept with its reason, so the paper can report the funnel.

Files written to `research/data/corpus/` (not committed, like all research data):

| File | What it holds |
|---|---|
| `apps.jsonl` | One row per corpus app: repository, commit, parent, the retired model, folder, link, measures |
| `screened.jsonl` | Every snapshot screened, with the reason it was left out |
| `apps.txt` | The app folders, one per line, for the next step's runs |
| `corpus.stats.json` | The totals for the paper |

Next steps run suites on these apps and draw the ~200 hand labels from those runs.

## Alternatives considered

- **Popular apps picked by hand or by stars:** easy to recognise, but the choice would be ours, and popular apps are not typical apps.
- **A fresh GitHub code search for SDK imports:** a wider population, but it needs a new sampling method and many requests. Paper 1's data already gives a random, documented frame.
- **The latest version of each repository:** the code after the migration, or after later rewrites. The snapshot before the migration is the code that depended on the retiring model.
- **Stratifying to force classification apps:** the five hand-picked apps had no label prompts at all ([ADR 0052](0052-oracles-by-output-type.md)). We keep the random order and report how many apps of each kind come out, rather than shape the corpus to the tool.

## Consequences

- The corpus is reproducible from Paper 1's data with one command, and the reasons for leaving apps out are counted.
- The snapshots are old code (2023 to 2026), so some calls use old SDK forms. Calls such as `openai.ChatCompletion.create(model=..., messages=...)` are still found, as other calls with `model=` and `messages=`.
- Prompts kept in `.txt` or `.md` files are not in the snapshots (the scanner does not read them). Such prompts are slots already, so nothing is lost that the synthesizer could read.
- Python only: apps in TypeScript and other languages are left out and counted.

## Results (29 October 2026)

`uv run python -m research.corpus.build` reused the scanner evaluation's 100 snapshots and downloaded 117 more. It screened 223 of the 308 eligible commits before reaching 40 apps:

| Screening | Snapshots |
|---|---|
| Joined the corpus | 40 |
| No Python files | 119 |
| No LLM call found | 36 |
| No call with written prompt text | 22 |
| Commit no longer on GitHub (404) | 5 |
| Repository too large | 1 |

What the synthesizer finds in the 40 apps (tests left out of the call list):

| | Count |
|---|---|
| Python files | 5,566 |
| LLM calls | 356 |
| with written prompt text | 187 |
| complete (every message read, each with text) | 146 |
| fixed prompts (complete, no slots) | 33 |
| with slots to fill | 243 |
| with test inputs from the app's own code | 11 (in 4 apps) |

Calls by API: OpenAI chat 131, other `model=` + `messages=` calls 88, Anthropic 76, Gemini 49, OpenAI Responses 7, OpenAI completions 4, LiteLLM 1.

Oracles: **224 text, 98 JSON, 34 tools and 0 label**. 31 apps have a free-text call, 28 a JSON call and 14 a tool call. No app in a random sample of 40 asks for a label from a list in a form the oracle rules detect, so free text, and with it the judge, carries most of the weight. As on the five hand-picked apps, the apps' own code gives test inputs for very few calls (11 of 356), so generated inputs ([ADR 0051](0051-generated-test-inputs-from-a-local-model.md)) are what make most cases.

Most of the 40 are small projects (personal bots, agents, back ends), which is what a random draw from GitHub migrations gives, not a choice of well-known apps.
