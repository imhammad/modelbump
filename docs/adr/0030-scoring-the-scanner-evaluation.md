# ADR 0030: Score the scanner's precision by group, weighted by group size

- **Status:** Accepted
- **Date:** 2026-10-22

## Context

[ADR 0029](0029-scanner-evaluation-set.md) built a blind sheet of up to 50 findings from each of five groups. The groups are very different in size: in the real build, config and code strings each hold over 2,000 findings, while documentation holds under 300. A plain share of `yes` over the 250 rows would give a small group the same weight as a big one. The sheet also allows an `unclear` answer, and scoring has to say what that does to the numbers.

## Decision

- **Per group:** the share of `yes` among rows labelled `yes` or `no`, with a 95% Wilson interval. `unclear` rows are left out of the share and counted on their own.
- **Overall precision:** the per-group shares weighted by each group's number of findings in the whole build (`group_population` in `build.stats.json`), with a normal 95% interval from the stratified standard error. This reuses `wilson`, `score_strata` and `weighted_precision` from `research.validation.score`, the same estimator as the migration filter in Paper 1, unchanged.
- **Precision with `--skip-comments`:** the same weighted estimate without the documentation group, because that flag drops exactly the comment and docstring findings.
- **By context:** the share of `yes` for each of the seven contexts is shown unweighted, for interest only. It is not an estimate for the full set.
- **Agreement:** if a second person labels a copy of the sheet, `--second` reports Cohen's kappa over the rows both labelled, with `unclear` as its own answer, as in Paper 1.
- **Recall is copied from the build,** so `scanner_eval.json` holds every number the tool paper needs.

## Alternatives considered

- **Count `unclear` as `no`:** gives a lower bound, but mixes "not a dependency" with "could not tell". The count is reported, so a reader can do this by hand.
- **One unweighted share over all 250 rows:** simpler, but it describes the sheet, not the scanner's output.

## Consequences

- The overall interval is wider than a single group's would suggest, because big groups with few labelled rows carry most of the weight.
- A row whose answer is not `yes`, `no` or `unclear` stops the script, so typos cannot silently drop rows. Blank rows are allowed and counted, so the script can be run halfway through labelling.
