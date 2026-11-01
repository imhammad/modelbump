# ADR 0071: `bump --open-pr` opens the pull request with plain git and gh, and its description is the evidence report, with verdicts but no answers

- **Status:** Accepted
- **Date:** 2026-11-01

## Context

The last part of `modelbump bump` is the pull request. Its description is what a reviewer reads before merging, so it must answer:

- why the model changes;
- what changed;
- what a person must still check;
- what the test found, and how to run the test again.

Opening the pull request touches the developer's repository and GitHub, so it must not leave a half-done state behind, and it must not put anything private into a public description.

## Decision

1. **The description is built from the plan and the evidence**, in this order:
   - why: the registry's shutdown date and suggested replacement;
   - what changed: places and files, variables, repaired calls, evidence files;
   - check by hand: places left alone, and repairs not written into the code;
   - the test: the models, the method, a warning when a case REGRESSED or could not run, one table row per case (verdict, oracle, old and new score, the checks the new model failed most), and the `modelbump test` command that runs it again;
   - a footer saying a person should review the change.

   When the tested models are not the bump's models (local stand-ins), the description says so.
2. **Verdicts and scores only.** The description never holds prompts, inputs or answers. Those are in `.modelbump/test.json`, which is part of the diff and reviewed like any other file.
3. **`--pr-body FILE`** writes the description without touching git, so it can be read first or pasted into another tool.
4. **`--open-pr`** does the steps a developer would do by hand, with plain `git` and `gh` commands (argument lists, no shell):
   1. check that `gh` is installed, the working tree is clean, a branch is checked out, and the branch `modelbump/OLD-to-NEW` exists neither locally nor on `origin`;
   2. write the files;
   3. `git switch --create` the branch, `git add` only the bump's files, `git commit`;
   4. `git push --set-upstream origin`;
   5. `gh pr create --base <current branch> --head <branch> --title "Bump LLM model from OLD to NEW" --body-file <temp file>`;
   6. switch back to the branch the developer was on, whatever happened.

   The checks in step 1 run before any file is written, so a refused `--open-pr` changes nothing. A failure after that says what was done, and which branch holds it.
5. **The branch name** is `modelbump/OLD-to-NEW`, with characters git does not allow (`:`, `@`, `..`) made safe. The same model change always gets the same branch, so a second run finds the first one and stops instead of opening a duplicate.

## Alternatives considered

- **The GitHub REST API through httpx:** no `gh` needed, but the tool would have to handle tokens, forks and GitHub Enterprise hosts itself. `gh` already does all of that, is installed on GitHub's runners, and reads `GH_TOKEN` in Actions.
- **A git library (GitPython, pygit2):** a new dependency for six commands. Plain `git` behaves exactly as the developer's own git, hooks and signing included.
- **Answers in a collapsed section of the description:** handy for a reviewer, but descriptions are public on public repositories and are copied into notifications and emails. A file in the diff can be reviewed, and dropped, before merging.
- **Stay on the new branch afterwards:** the developer would have to notice they changed branch. Going back to where they started is less surprising.

## Consequences

- `modelbump bump OLD --suite ... --report ... --patch ... --open-pr` goes from a clean checkout to an open pull request with one command.
- The scheduled GitHub Action in the next step can run the same command with `GH_TOKEN`.
- `.modelbump/test.json` holds every answer, so a later step checks the evidence for secrets before it is committed.
