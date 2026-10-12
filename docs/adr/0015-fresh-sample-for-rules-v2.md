# ADR 0015: Measure rules v2 on a fresh, blind sample of 200 commits

- **Status:** Accepted
- **Date:** 2026-10-12

## Context

Rules v2 (ADR 0014) were written by reading the 300 commits of the first validation sample. Scored on those same commits they look good (the `migration_away` label flags 131 rows, 113 of them labelled `yes`), but that is in-sample: the rules were fitted to those rows, so the numbers are too optimistic to report.

On the full set, rules v2 label 40,876 of 254,765 candidates `migration_away`.

## Decision

- Draw a **second, fresh sample** of **200** commits with a new seed (2027), stratified by rules v2:
  - `away`: 100 commits labelled `migration_away`. This measures its precision.
  - `other_kept`: 50 commits that Kim's rules keep (with or without an AI-tool trailer) but that are not `migration_away`.
  - `rejected`: 50 of the rest.
  The last two estimate how many real migrations `migration_away` misses.
- Leave out every commit of the first sample, so no labelled commit is seen twice.
- Label it **blind** with the same guide. The filter's decisions stay in `sample_key.csv` until labelling is done.
- Freeze rules v2 until this sample is scored. Any later change to the rules needs another fresh sample before its numbers are reported.
- Ask a second person to label the same sample, or at least 50 rows of it, independently, so human agreement (Cohen's kappa) can be reported.
- The files go to `research/data/validation_v2/`, and `research.validation.score --dir research/data/validation_v2` reads the design from `strata.json`.

## Alternatives considered

- **Report the in-sample numbers:** quick, but reviewers would rightly discount them.
- **Split the first 300 rows into development and test halves:** no new labelling, but the rules were written from all 300, so neither half is unseen.
- **A larger fresh sample:** tighter intervals, but more labelling time. 200 commits give a 95% interval of roughly ±7 points on the `away` precision. The sample can be extended with another seed later.

## Consequences

- The paper reports rules v2's precision and recall from this sample only, and the first sample's numbers as development history.
- Labelling 200 commits takes a few hours. Long messages hide switches ([challenge 005](../engineering-challenges/005-first-pass-labels.md)), so the guide now asks to read every message to the end.
