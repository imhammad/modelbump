# ADR 0043: Control the false discovery rate across a suite with e-BH on the betting wealths

- **Status:** Accepted
- **Date:** 2026-10-27

## Context

[ADR 0041](0041-item-verdict-from-pass-counts.md) and [ADR 0042](0042-sequential-stopping-by-betting.md) keep each test case's wrong claims at or below alpha. A real suite has hundreds of test cases. With 300 cases and alpha = 0.05 each, a new model that changed nothing still gets several REGRESSED by chance. In our simulation (below) per-case tests gave 4.5 false alarms per 300-case suite on average, and up to 9. A report with a few false alarms in every run teaches people to ignore it.

The usual answer is to control the **false discovery rate (FDR)**: among the cases we call REGRESSED, the expected share that did not really regress is at most q. Benjamini–Hochberg (BH) does this for p-values. Our sequential tests produce wealths, not p-values. A wealth stopped at any time is an **e-value** (its expected value under the null is at most 1). That is exactly what e-BH needs.

## Decision

- **e-BH** (Wang and Ramdas, *JRSS-B* 84(3), 2022). With m test cases and e-values e₁…eₘ, reject the k largest, for the largest k whose k-th largest e-value is at least m/(q·k). It controls FDR at q under **any** dependence between test cases. That matters because test cases from one app share a prompt and are not independent.
- **One e-BH per claim:** REGRESSED, IMPROVED and EQUIVALENT each get their own e-BH at level q (default 0.05). For EQUIVALENT the e-value is the smaller of the two half-wealths, which is an e-value whichever half's null is true. Order as before: EQUIVALENT, then REGRESSED, then IMPROVED.
- **Stopping each test case:** a case stops when one of its wealths reaches m/q, or at `max_runs`. A wealth of m/q is rejected by e-BH whatever the other cases show, so stopping there loses nothing. Cases that stop lower can still be rejected at the end if enough cases are strong. Stopping on our own wealth is a stopping time, so each stopped wealth stays an e-value.
- **Classic BH** (Benjamini and Hochberg, *JRSS-B* 57(1), 1995) is also included as `benjamini_hochberg`, for the fixed-k baselines in the simulation study (P4-4).
- **Code:** `run_suite(items)` runs the suite, `decide_suite(evidence)` applies e-BH, and `simulated_suite(...)` makes a suite with known true pass rates. The command `modelbump stats simulate-suite` shows one run against per-case tests with no suite control.

## Results from simulation

20 simulated suites of 300 test cases per row (seeds 1–20), q = alpha = 0.05, margin 0.10, at most 200 answers per model per case. Unchanged cases pass 60%, 80%, 90% or 100% of the time.

| Suite | Suite control (e-BH): true regressions found | FDR | Answers per model | No control: true found | False alarms per suite | Answers per model |
|-------|---------------------------------------------|-----|-------------------|------------------------|------------------------|-------------------|
| Nothing changed | 0 | 0% | 52,870 | 0 | 4.5 (up to 9) | 45,970 |
| 30 cases lose 30 points | 30 of 30 | 0.3% | 50,645 | 30 | 4.0 (up to 9) | 42,604 |
| 30 cases lose 15 points | 17.2 of 30 | 0.2% | 53,148 | 27.1 | 4.0 (up to 9) | 44,369 |
| 150 cases lose 15 points | 109.7 of 150 | 0.1% | 54,349 | 132.1 | 2.2 (up to 5) | 38,195 |

What this shows:

- **False alarms almost vanish.** The FDR stayed far below q. Across the 80 suites the most false alarms in one suite was 2, in a suite where about 110 real regressions were found. Suites where nothing changed had none.
- **Clear drops are still all found,** at about 19% more answers.
- **The price is power on small drops.** A 15-point drop is found in 17 of 30 cases instead of 27, because each case must now reach m/q = 6,000 instead of 20. The e-BH step at the end helps: in the 30-case row it added 6.7 cases on top of the 10.5 that reached 6,000 on their own, and in the 150-case row 55.
- The FDR is much lower than q, so the method is conservative. A smarter stopping rule could use the room. Ideas are listed below.

## Alternatives considered

- **Bonferroni (each case at alpha/m):** controls the chance of any false alarm at all, and is stricter than needed. It equals our per-case stop at m/q, but without the extra rejections e-BH gives at the end.
- **Classic BH on sequential p-values:** BH needs independence or positive dependence (PRDS) between cases. Test cases that share a prompt template need not satisfy that. e-BH needs nothing.
- **No correction, report raw per-case verdicts:** cheapest and most powerful, but every unchanged suite gets several false alarms, as the table shows.
- **Stopping each case at a lower bar that depends on how many others are already strong:** could win back power on small drops, and is still valid. It is more complex, so it is left for the simulation study, where we can measure the gain.

## Consequences

- A suite report can say "at most 5% of the REGRESSED cases are expected to be false alarms" for any suite size, and that holds however the cases depend on each other.
- Bigger suites need more answers per case to call a small drop, because the bar m/q grows with m (it grows only as log m in answers). The Phase 5 suite builder should prefer fewer, sharper test cases.
- `run_suite` runs the cases one after another. The real runner (P4-6) will ask models concurrently and use the budget, but the statistics stay the same.
