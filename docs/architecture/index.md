# Architecture overview

ModelBump is a pipeline of independent stages. Each stage has one job, a typed input and a typed output, so stages can be tested, evaluated and replaced on their own.

```mermaid
flowchart LR
    code[Target repo:<br/>code, configs, tests] --> scan[1 Scanner]
    registry[(Retirement<br/>registry)] --> scan
    scan --> synth[2 Suite synthesizer]
    synth --> runner[3 Runner<br/>cache + budget]
    runner --> stats[4 Stats engine]
    stats --> repair[5 Prompt repair]
    repair --> runner
    stats --> report[6 Reporter]
    repair --> pr[7 GitHub PR]
    report --> pr
```

| Stage | Responsibility | Status |
|-------|----------------|--------|
| [Registry](registry.md) | Which model IDs are retired, and when | v1 (Phase 1) |
| [Scanner](scanner.md) | Find model IDs in code and config; match them against retirement dates | v0.1.0 (Phase 2) |
| [Suite synthesizer](synth.md) | Build regression test cases and oracles from the target repo | v0.4.0 (Phase 5) |
| [Oracles](oracles.md) | Decide whether each answer still does the job, by output type | v0.4.0 (Phase 5) |
| [Suites](suite.md) | Write the suite file and run it on two models (`modelbump test`) | v0.4.0 (Phase 5) |
| [Runner](runner.md) | Call models with caching, retries and a cost budget | Done (Phase 3) |
| [Stats engine](stats.md) | Decide REGRESSED / IMPROVED / EQUIVALENT / INCONCLUSIVE per test case | v0.3.0 (Phase 4) |
| [Prompt repair](repair.md) | Find prompt edits that fix regressions safely | Patches (Phase 6, in progress) |
| Reporter / GitHub | Produce reports and open the upgrade PR | Planned (Phase 7) |

Each stage gets its own page here when it is built.
