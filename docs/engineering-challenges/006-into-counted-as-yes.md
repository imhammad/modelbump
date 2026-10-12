# 006: A model switch is not always a migration away

- **Date:** 2026-10-12
- **Area:** Research validation

## Context

Rules v2 were measured on a fresh, blind sample of 200 commits ([ADR 0015](../adr/0015-fresh-sample-for-rules-v2.md)). A classmate labelled the same sample so that agreement between two people could be reported.

## Symptom

The first scores looked strange. 34.7% of the commits the rules had *rejected* were labelled real migrations. The first sample had found 8% (3% to 19%) in the same group, and the two intervals did not even overlap. Because that group holds 166,942 commits, the one number pulled recall down to 33%. Agreement with the classmate was 0.90, which looked excellent.

## Investigation

- The `yes` rows in the "rejected" and "other_kept" groups were read one by one, next to the `model_ids` column. 12 of the 17 rejected `yes` rows moved **into** the listed model, for example "switch from gemini-1.5-flash to gemini-2.0-flash" with `model_ids` = `gemini-2.0-flash`. So did 9 of the 19 other_kept `yes` rows, and 2 more were not model switches at all.
- The same mistake was found on 6 rows of the "away" group. There the *rules* had also been fooled: phrases like "replaces deprecated gemini-1.5-flash" sit next to the new model, so the rules read them as "away".
- The classmate's file had exactly the same `from_model` and `to_model` text as the first labeller's in all 117 rows both marked `yes`, including the same typos. Her copy had been made from the already-labelled file, so the 0.90 was not independent agreement.

## Root cause

- **Labels:** the guide asks whether the commit moves away from the model *in `model_ids`*. A commit that leaves another model for the listed one is a real model switch, so it feels like a `yes`. Over 200 rows, "a model switch" quietly replaced "a migration away from this model".
- **Agreement:** the second person's copy was taken after labelling had started, not from the blank file.

## Options considered

- **Report the first pass as it is:** honest about the process, but the recall estimate would rest on labels that break the guide's own definition.
- **Widen the definition so that "into" counts:** this would match the labels, but not Kim (2026), who drops migrations *into* a model, and not what the tool needs (it warns about the model that is going away).
- **Adjudicate and report both,** as in [challenge 005](005-first-pass-labels.md): fix the 29 rows that break the definition, keep the first pass untouched, and redo the second person's labels from a blank copy.

## Fix

The third option. The first pass stays in `research/data/validation_v2/`. The adjudicated labels are in `research/data/validation_v2_adjudicated/`, and the 29 changed rows are listed with their reasons. The classmate labelled rows 1 to 100 again from a blank copy, blind and on her own. After adjudication: precision 84.0% (75.6% to 89.9%), rejected group 10.2% (back in line with the first sample), recall about 58%. Agreement with the classmate's blind labels was 0.94 over 100 rows. The guide now gives an "into" example (see the [validation guide](../research/validation.md#results)).

The 6 "away" rows that fooled the rules are kept as test cases for a future rules v3. Rules v2 stay frozen, so their numbers are not changed here.
