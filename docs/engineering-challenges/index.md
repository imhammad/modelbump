# Engineering challenges

Problems that took real effort to solve, written up so the lesson is not lost. One file per challenge: `NNN-short-title.md`.

## Template

```markdown
# NNN: Short title

- **Date:** YYYY-MM-DD
- **Area:** scanner / runner / stats / CI / ...

## Symptom
What we saw going wrong.

## Investigation
What we checked, in order, and what each step ruled out.

## Root cause
The actual reason.

## Options considered
The possible fixes and their trade-offs.

## Fix
What we did (link the PR).

## Lesson
What we'd do differently from now on.
```

## Challenges

| # | Challenge | Area |
|---|-----------|------|
| [001](001-release-pr-ci-never-runs.md) | Release PRs would never pass CI | CI / releases |
| [002](002-one-model-two-shutdown-dates.md) | One model, two shutdown dates | Registry data |
