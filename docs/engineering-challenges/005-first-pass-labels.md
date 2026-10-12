# 005: The hand labels needed checking too

- **Date:** 2026-10-12
- **Area:** Research validation

## Context

To measure the migration filter (ADR 0012), 300 sampled commits were labelled by hand, blind to what the filter decided (ADR 0013). The labels are the ground truth that every precision and recall number rests on.

## Symptom

The first scores were lower than expected: 67% of the "strict" commits were labelled real migrations. When the labelled rows were read next to the filter's decisions, many `no` labels sat on commits that plainly said "from gemini-2.0-flash to gemini-2.5-flash".

## Investigation

- An AI model (Claude) read all 300 messages as a second rater, using the same labelling guide. It disagreed with the first pass on 31 rows (agreement 269 of 300, Cohen's kappa 0.78). In 29 of them the first pass said `no` where the message names a switch away from the model.
- Most of those were long commits that do many things, where the model switch is one bullet in the middle or at the end. A few were short and simply missed.
- To check that the re-check was not one-sided, 15 rows the AI had *not* flagged were picked at random (seed 2026) and re-read too. 3 of the 15 were changed, so first-pass slips were not limited to the flagged rows, and the AI reader missed things too (one was a model removed from a README table).

## Root cause

Labelling 300 long commit messages in one sitting is tiring, and a switch buried in a multi-change commit is easy to overlook. One person labelling once has no way to catch that.

## Options considered

- **Let the AI's reading replace the first pass:** fast, but then the "human ground truth" would really be the AI's, and reviewers would rightly call it contaminated.
- **Ignore the disagreements:** keeps the first pass pure, but reports numbers we know are wrong.
- **Adjudicate and report both:** the human re-reads every disagreement plus random control rows and decides each one, and both label sets are reported.

## Fix

The third option. The first pass stays in `research/data/validation/`, the adjudicated labels are in `research/data/validation_adjudicated/`, and `research.validation.score --compare` shows them side by side. After adjudication the strict share is 86% (78% to 92%). First pass vs adjudicated: Cohen's kappa 0.76. The paper states that the second rater was an AI model.
