# ADR 0056: Use Gemma 3 12B as the judge, fail invented facts, and test the change on fresh labels

- **Status:** Accepted
- **Date:** 2026-10-29

## Context

The first check of the judge ([ADR 0055](0055-check-the-judge-against-hand-labels.md)) was a blind 40-answer pilot on the demo suite, labelled by the project author. Llama 3.1 8B ([ADR 0054](0054-llm-judge-for-free-text.md)) did this:

- Every judge FAIL was also a FAIL by hand (20 of 20).
- Only 14 of 20 judge PASSes were PASSes by hand (70%, 95% CI 46-87%), the same for both models.
- The judge passed 94% of answers. Corrected to the hand labels, the pass rate was about 66% (43-83%) for both Qwen 2.5 and Qwen 3.

All 6 wrong PASSes failed for the same reason: the answer **states facts that are in neither the prompt nor the reference**. Examples are "industry-standard encryption", a reset link sent by email, and "problem resolved" when the support thread never says so. None failed on length. The judge also gave opposite verdicts on near-identical answers (sheet rows 4 vs 28, 9 vs 20, 7 vs 8). So it can see the problem but is not consistent, which points to the model's size more than to the instructions.

## Decision

- **Default judge `ollama/gemma3:12b`.** It is larger, from a third family (neither Qwen nor Llama), and about 8 GB, so it fits a 16 GB laptop. `--judge` still picks any other model.
- **One rule added to the judge's instructions**, in the labeller's words: *FAIL if the answer states any fact that isn't in the source text (the app's prompt) or the reference, even if it sounds plausible.*
- **The pilot labels are a development set, not the test.** They shaped this change, so measuring the new judge on them would overstate it. The procedure:
  1. Re-judge the same run (the answers come from the cache; only the judge is asked).
  2. `modelbump judge agreement SHEET KEY --report NEW_REPORT` compares the pilot labels with the new verdicts, as a check only. The pilot sheet was drawn by the old judge's verdicts, so this mode does not correct pass rates and says so.
  3. `modelbump judge sheet NEW_REPORT --exclude-key OLD_KEY` draws a fresh blind sheet that leaves out every answer already labelled. Its agreement is the measurement to report.

## Alternatives considered

- **Only the stricter instruction, keeping Llama 3.1 8B:** cheap, but it does not address the inconsistency on near-identical answers.
- **Asking the judge several times and taking the majority:** reduces noise, at three times the calls, and does not fix a judge that misses the problem a third of the time.
- **A list of claims checked one by one (fact extraction):** more precise, but many calls per answer and much more code. It can be tried if the larger judge is not enough.
- **Re-using the pilot labels as the test set:** fewer labels to make, but the result would be tuned to them.

## Consequences

- Judging is slower: a 12B model on a laptop takes several seconds per answer.
- Changing the judge's model or instructions changes the cache key, so every free-text answer is judged again once. The compared answers are not asked again.
- The judge used in each report is named in it, so results from the two judges are never mixed.
- The pilot showed a judge with no false FAILs and many false PASSes. The fresh sheet will show whether the new judge trades some false PASSes for false FAILs.
