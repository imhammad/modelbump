# ADR 0017: Measure how late projects migrate, and what they migrate to

- **Status:** Accepted
- **Date:** 2026-10-13

## Context

Paper 1 is an empirical study for *Empirical Software Engineering*. [ADR 0016](0016-migration-timing.md) answers *whether* migrations come after the shutdown (58% to 69% for OpenAI and Anthropic, against Kim's 82%). Two questions remain that need no new GitHub calls:

- **RQ2, how late:** how many days before or after the shutdown do projects move, and how much of the notice period do they use?
- **RQ3, to what:** which model does each migration move to? Is it the same provider or another? Does it match the provider's recommended replacement? Is it a smaller or larger tier, a newer or older generation?

Commit messages say this in many ways: "from X to Y", "X -> Y", "replace X with Y", "use Y instead of X", "switch to Y", or nothing at all when the old model is simply removed. Both samples have the target model written by hand in `to_model` for every row labelled `yes`, so the extraction can be measured.

## Decision

- **RQ2** (`research.analysis.lag`) reads `timing.jsonl` and reports, per provider group:
  - the **median days from the shutdown** with a distribution-free 95% confidence interval (order statistics, Conover), and the quartiles. This is done for all migrations, for each repository's first migration per model, and for migrations after the shutdown only;
  - the share in fixed **windows** (more than 180 days before, 91 to 180 before, and so on up to more than 365 days after);
  - the **notice period** per model (notice to shutdown) and, for migrations made during it, **how far into it** they came (0% is the notice day, 100% the shutdown);
  - one line per model with at least 100 migrations.
- The paper uses `--retired-by 2026-07-11`, as in ADR 0016. Every model then has at least 90 days of follow-up, so the windows up to "31 to 90 days after" are complete. Later windows are lower bounds, because later migrations may still come.
- **RQ3** (`research.enrichment.targets`) writes `targets.jsonl`, one row per `migration_away` commit, with the model left (chosen as in ADR 0016) and the **target**:
  - **Model IDs** are recognised by a pattern for the families of the three providers and the common open models (Llama, Mistral, DeepSeek, Qwen, Grok, Command). A name without a digit counts only if it is on a short list (for example `gemini-pro`), so tools like `claude-code` are not read as models.
  - **Target patterns**, tried in order: `X -> Y` or `X to Y`; `from X ... to Y`; `replace X with Y`; `Y instead of X` or `Y replaces X`; `switch/update/set ... to Y`; any arrow `-> Y`; and finally the only other model named in the message. The pattern that found the target is stored, so each can be checked or dropped.
  - Not a target: an alias of the model being left, or another retired model the message also moves away from.
  - **Kind of switch:** the target's provider (registry first, then the name); whether it is on a retirement list itself, and whether it was already announced for retirement on the commit day; the tier change (small, standard, large, read from words like `mini`, `haiku`, `opus`, `pro`); the generation change within the same series (`gpt`, `o`, `claude`, `gemini`, embeddings).
  - **Recommended replacement.** The registry stores what the provider recommends *today*, not on the commit day ([ADR 0006](0006-retirement-registry-format.md)). So we report two levels: **exact** (the same model, ignoring date endings) and **same line** (the same product line in any version, for example any Sonnet for a retired Sonnet). "Same line" is the fairer measure.
- **Validation** (`research.validation.targets_check`) runs the extraction on every hand-labelled `yes` row with `to_model` filled in. It reports agreement on the model and on the provider, with 95% Wilson intervals, and writes every row to `targets_check.csv`.
  - The rules were written **without looking at either sample**, so both are held-out tests. The second sample (`validation_v2_adjudicated`) is the one the paper reports.
  - If the rules are ever changed after reading the disagreements, the first sample becomes the development set, and the second sample's score is reported only from before the change, or from a new sample.

## Alternatives considered

- **An LLM to read the target from each message:** more flexible, but it costs money for 40,876 messages, cannot be rerun exactly, and would need its own validation. Rules plus a measured error rate are cheaper and reproducible. An LLM could still be used later on the commits the rules leave without a target.
- **Read the target from the diff:** more exact, but it needs one API call per commit. Step 20 fetches diffs for a sample only.
- **Mean lag instead of median:** a few repositories that move years later would dominate the mean.
- **Survival analysis of time to migration:** it needs every project that *used* a model, including those that never migrated, which a search for migration commits cannot give.

## Consequences

- RQ3 describes the commits whose message names a target. Commits that only remove the old model, or that name several possible targets, are counted as "no target" and reported as such.
- The "follows the recommendation" numbers are a lower bound for exact matches, because the provider may have recommended an older model when the commit was made.
- Tier and generation come from model names only. They are rough labels for the paper's tables, not exact capability or price comparisons.
- `targets_check.csv` lets anyone read every disagreement between the rules and the hand labels.
