# ADR 0032: Re-score the same labels after a scanner change

- **Status:** Accepted
- **Date:** 2026-10-23

## Context

[ADR 0031](0031-describing-contexts-and-test-files.md) changed how the scanner labels a finding's context and added `--skip-tests` and new file types. The 250 hand labels from [ADR 0029](0029-scanner-evaluation-set.md) took hours to make, and drawing a new sheet for every scanner change would waste them. The text finder did not change, so the new scanner reports the same IDs at the same places in the snapshots. Only their contexts differ.

## Decision

- **Same findings, new contexts.** `research.scanner_eval.rescore` scans the saved snapshots again and matches every finding to the old one by commit, path, line and column. If the set of places differs, it stops: the labels would no longer describe the population.
- **Same sheet.** It draws the sheet again with the build's seed and checks every row against `sheet.csv` before using a label.
- **Precision within the original strata.** For each setting (all findings, `--skip-comments`, `--skip-tests`, both), each group keeps the findings the setting keeps. The group's precision comes from its labelled rows that are kept, and its weight is the exact number of kept findings. This is domain estimation within strata, with the same estimator as [ADR 0030](0030-scoring-the-scanner-evaluation.md).
- **Recall on every setting,** because `--skip-comments` and `--skip-tests` can drop known sites too.
- **New file types are tested on the missed sites only.** For sites missed with "file type not scanned" whose file the scanner reads now, the file is downloaded from `raw.githubusercontent.com` at the parent commit into `extra/`, apart from the snapshots. So the new file types add recall without changing the precision population.
- **Nothing the build wrote changes.** Outputs are `rescore.json`, `rescore.findings.jsonl` and `extra/`.

## Alternatives considered

- **Label a fresh sample:** unbiased for the new version, but it costs another day of labelling for each change.
- **Download whole snapshots again with the new file types:** measures precision on the new file types too, but changes the population the labels were drawn from.

## Consequences

- A group whose kept findings have no labelled row cannot be estimated. Its findings are counted in `unestimated_findings` and left out of the weights.
- The rules of ADR 0031 were written after reading these labels. So the gain they show on this sheet is an in-sample number, and the paper must say so. An unbiased check needs a fresh sample.
- Precision on the new file types is not measured.
