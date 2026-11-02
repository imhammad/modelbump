# 007: The pull request said nothing regressed, under a table of regressions

- **Date:** 2026-11-01
- **Area:** Bump / pull request

## Symptom

The first real run of `modelbump bump --pr-body` on the demo app ([ADR 0071](../adr/0071-pull-request-with-the-evidence-report.md)) wrote a description that contradicted itself. The table listed two cases as **REGRESSED**. Above it, the description said "No test case regressed", and below it "Result: 0 regressed, 0 inconclusive, 0 equivalent, 0 improved". All 1307 tests passed.

## Investigation

- The table was built from `cases[].verdict`, and showed the right verdicts.
- The warning and the summary were built from the report's `counts` object, read with lower-case keys (`counts["regressed"]`).
- The real report, written by `render_run_json`, keys `counts` by the verdict's value: `"REGRESSED"`. Every lookup missed and returned 0.
- The test fixture had been typed by hand with lower-case keys, so the tests agreed with the code instead of with the real report.

## Root cause

Two copies of the same fact (the per-case verdicts, and a count of them) read through a key whose case nobody checked. The fixture copied the reader's assumption instead of the writer's output.

## Options considered

- **Read upper-case keys:** a one-line fix, but the description would still trust a second copy of the data.
- **Count from the cases:** the warning, the table and the summary then come from the same list, so they cannot disagree. A case that could not run is left out of the counts, as in the table.

## Fix

The second option (Step P7-4b, merged with [ADR 0071](../adr/0071-pull-request-with-the-evidence-report.md)). The fixture now has upper-case verdicts and counts, as the real renderer writes them. Later tests that need a report build it with the real renderer ([ADR 0073](../adr/0073-redact-evidence-and-scan-large-repositories-fast.md) tests do).

## Lesson

Build fixtures from the real writer's output, not from what the reader expects. When one document shows the same fact twice, derive both from one source.
