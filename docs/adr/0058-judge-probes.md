# ADR 0058: Test the judge with answers broken on purpose

- **Status:** Accepted
- **Date:** 2026-10-29

## Context

On the fresh blind sheet ([ADR 0056](0056-bigger-judge-and-no-invented-facts.md)), Gemma 3 12B was right on 95% of its FAILs but only 70% of its PASSes. The labeller sorted the 6 wrong PASSes into new kinds:

- the reference copied almost word for word, except where it sends the user (3);
- a hedged invention, "your email or account information" (1);
- a summary that uses the thread's words but flips the meaning, or drops the key fact (2).

Hand labels on real answers measure how often the judge is right overall. They cannot say how well it catches each kind of mistake, because each kind shows up only a few times. The ~200 corpus labels will not fix that either.

## Decision

`modelbump judge probes REPORT` makes **probes**: edits of each free-text case's reference answer, in one known way each, written by a local model (the "breaker", `ollama/qwen2.5:7b` by default, temperature 0.7, seed = sample, cached):

| Kind | The edit | Intended label |
|---|---|---|
| `changed_source` | Word for word, but one change to where it sends the reader (a link, page, section, team, contact), else one name, number or date, not in the prompt or the answer | FAIL |
| `flipped_meaning` | Mostly the same words, the meaning made wrong (who did what, the opposite, what happened) | FAIL |
| `missing_fact` | The single most important fact left out, still sounding complete | FAIL |
| `hedged_invention` | One invented detail, written vaguely or as one of several options | FAIL |
| `paraphrase` | Other words, the same meaning and facts | PASS |

The paraphrase is a control: without it, a judge that fails everything would look perfect.

- **Per kind, 2 probes per case** (`--per-kind`). An edit that is empty, the same as the reference, or the same as an earlier probe is asked again, up to 3 tries per probe. Probes the breaker never writes are counted and reported.
- **The judge grades each probe against the unchanged reference**, with the same request as in `modelbump test` (temperature 0, seed 0).
- **A person checks every probe, blind.** The breaker can fail as well: an edit that changes nothing that matters, or a paraphrase that changes the meaning. The sheet has the same columns as the judge sheet (prompt, reference, answer, `your_label`) in shuffled order (seed 2032), with no kind and no verdict. The key holds both.
- **`modelbump judge probe-check SHEET KEY`** counts, per kind, the probes the person confirmed (FAIL for a broken kind, PASS for a paraphrase) and how many of those the judge got right, with 95% Wilson intervals, plus all broken kinds together. Probes the person did not confirm measure the breaker, not the judge, and are left out of the judge's rates.

## Alternatives considered

- **Edits made by code** (swap a URL, negate a verb): exact, but most answers have no URL, and code cannot flip the meaning of a sentence or find its key fact.
- **Probes from the compared answers instead of the reference:** closer to real use, but the base answer may already be wrong (the judge passes wrong answers 30% of the time), and then a broken probe says nothing new. Starting from the reference keeps the base fixed. It is also the easiest setting for the judge, since probe and reference differ only by the edit, so a miss here is a clear miss.
- **No hand check, trusting the breaker:** much cheaper, but a 7B model does not always follow an editing instruction, and an unchecked probe set would mix the breaker's mistakes with the judge's.

## Consequences

- The paper can report the judge's catch rate per kind of mistake, next to its agreement on real answers.
- A judge change (model or instructions) can be compared on the same probes: the probes are cached, so only the judge is asked again.
- Four of the five kinds are broken, so the labeller knows most rows should fail. The labels are still blind to which rows are which, and the paraphrase rows show whether the labeller passes a correct answer.
- The probes come from one breaker model, so they share its style. Real mistakes from other models may be harder to spot.

## Results (29 October 2026)

On the Gemma demo report (4 free-text cases, 2 probes per kind), the breaker wrote 37 of 40 probes. It failed to write one flipped meaning and two missing facts. The project author labelled all 37 blind:

| Kind | Labelled | Confirmed by hand | Judge right | 95% CI |
|---|---|---|---|---|
| `changed_source` | 8 | 7 wrong | 7 of 7 FAIL | 56-100% |
| `flipped_meaning` | 7 | 6 wrong | 6 of 6 FAIL | 52-100% |
| `missing_fact` | 6 | 3 wrong | 1 of 3 FAIL | 2-87% |
| `hedged_invention` | 8 | 8 wrong | 8 of 8 FAIL | 60-100% |
| `paraphrase` (control) | 8 | 8 right | 8 of 8 PASS | 60-100% |
| All broken kinds | | 24 | 22 of 24 FAIL (92%) | 72-99% |

When one clean edit separates an answer from the reference, Gemma 3 12B catches nearly every kind of mistake, and it does not fail correct rewordings. Its one weak kind is a missing key fact. That kind was also the hardest for the breaker: only 3 of its 6 edits really dropped the fact.

On real answers, the same judge passed about 30% wrong ones (ADR 0056). So its misses there are subtler than a single clean edit: answers that differ from the reference in many places at once. The corpus labels ([ADR 0059](0059-run-the-corpus-end-to-end.md)) measure that.
