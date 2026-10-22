# ADR 0029: Evaluate the scanner on snapshots taken just before real migrations

- **Status:** Accepted
- **Date:** 2026-10-22

## Context

The tool paper must say how well the scanner finds the model IDs a project depends on. The master plan asks for a labelled set of real repositories to measure precision and recall. Labelling every model dependency in 100 whole repositories by hand would take weeks, and a set we built ourselves could miss the same places the scanner misses.

We already have 400 random migration commits with their full diffs, fetched for RQ4 of Paper 1 (`research/data/files.jsonl` and its cache, [ADR 0018](0018-changed-files-sample.md)). Paper 1 is not submitted yet, so its code and numbers must not change.

## Decision

- **Snapshots:** draw 100 of those commits at random (seed 2030). Keep only commits that removed at least one line naming the old model outside documentation files. For each one, download the repository at the commit's **parent**, the state just before the migration, and keep only the files the scanner reads.
- **Recall, from ground truth the scanner never saw.** Every line the migration removed that names the old model (outside docs) is a place the project depended on that model. The scanner should report the model on that exact line of the parent snapshot. The match uses a separate exact-ID rule, not the scanner's finder. Each miss gets a reason: skipped folder, file type not scanned, file too big, or not found by the finder.
- **Precision, by hand.** A blind sheet holds a random sample of the scanner's findings, up to 50 from each of five groups: code use (call arguments and assignments), other code strings, documentation (comments and docstrings), config, and other text. The sheet shows the line, two lines before and after, and a link to it on GitHub, but not the scanner's context. The labeller answers one question per row: *is this a model dependency?* The labelling guide is in [scanner evaluation](../research/scanner-eval.md). Precision is weighted by the size of each group, and is also reported per group, which also shows what `--skip-comments` gains.
- **New code only.** The scripts live in a new package, `research/scanner_eval/`. They import existing research code but change none of it, so Paper 1's numbers stay the same. Outputs go to `research/data/scanner_eval/`, which git ignores like the rest of the data.
- **Scoring comes in its own step,** after the labels exist (`research.scanner_eval.score`).

## Alternatives considered

- **Hand-label whole repositories:** the classic design, but slow, and recall would only be as good as the labeller's search.
- **Recall on every model ID in the snapshot found by `grep`:** cheap, but it shares the scanner's notion of an ID, so it would mostly measure itself.
- **New repositories picked by GitHub code search:** not biased by our miner, but code search finds files by the same strings, and the sample would not tie to the migration dataset that the replay experiment uses.

## Consequences

- Recall is measured on lines developers actually changed, which is the kind of dependency the tool exists to warn about. It cannot see dependencies that a migration left untouched, so it is recall on known sites, not on every dependency. The paper must say so.
- Recall says nothing about IDs the migration did not remove, for example new models added elsewhere. Precision covers those.
- The same parent snapshots will be reused by the replay experiment.
- The run makes about 100 API requests plus 100 downloads, within GitHub's limit of 5,000 requests per hour.
