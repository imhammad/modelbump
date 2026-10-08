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
| Scanner | Find model IDs in code and config; match them against retirement dates | Planned (Phase 2) |
| Suite synthesizer | Build regression test cases and oracles from the target repo | Planned (Phase 5) |
| Runner | Call models with caching, retries and a cost budget | Planned (Phase 3) |
| Stats engine | Decide REGRESSED / EQUIVALENT / INCONCLUSIVE per test case | Planned (Phase 4) |
| Prompt repair | Find prompt edits that fix regressions safely | Planned (Phase 6) |
| Reporter / GitHub | Produce reports and open the upgrade PR | Planned (Phase 7) |

Each stage gets its own page here when it is built.
