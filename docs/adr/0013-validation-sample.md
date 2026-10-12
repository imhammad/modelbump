# ADR 0013: Check the migration filter on a blind, stratified sample of 300 commits

- **Status:** Accepted
- **Date:** 2026-10-12

## Context

The filter (ADR 0012) labelled 39,181 of 254,765 candidates as migrations: 10,940 with a clear "away" direction (strict) and 28,241 where the direction was unclear. Another 35,318 pass the same rules but carry an AI-tool trailer. Rules written as regular expressions make mistakes, and nothing can be reported until we know how often. According to its Method section, Kim (2026) checked its keyword matches by hand on 300 commits with two coders and found that 62% were genuine migrations.

## Decision

- Draw **300** commits with a fixed seed (2026), stratified by what the filter decided: 100 strict, 100 broad-only (direction unclear), 50 AI-assisted, and 50 rejected.
- The sample is **blind**. `sample.csv` shows the commit (link, model IDs, date, message) but not the filter's decision. The decision is in `sample_key.csv`, which is only opened after labelling.
- Each commit is labelled by hand using the guide in `docs/research/validation.md`, opening the commit on GitHub whenever the message alone is not enough.
- Precision is estimated for each stratum, then weighted by the stratum's size in the full set. The rejected stratum estimates how many migrations the filter missed.
- A second person should label at least part of the same sample independently, so agreement (Cohen's kappa) can be reported, as Kim did.

## Alternatives considered

- **A simple random sample of 300:** most commits would come from the rejected stratum, so it would say little about the commits the filter keeps.
- **Showing the filter's decision while labelling:** faster, but it biases the labeller towards agreeing with the filter.
- **Labelling with an LLM:** cheap, but it would be checking rule-based labels with another unvalidated method. It could be compared against the human labels later.

## Consequences

- The paper can report the filter's precision with confidence intervals, and roughly how many migrations it missed.
- Hand-labelling 300 commits takes several hours.
- The labelled sample becomes training and test data if we later replace the rules with a classifier.
