# ADR 0072: `bump-all` and the Action's `open-prs` input open one pull request per due model on a schedule, with least privilege and no duplicates

- **Status:** Accepted
- **Date:** 2026-11-01

## Context

Dependabot's value is that nobody has to remember to look: on a schedule, it opens one pull request per outdated dependency. ModelBump can now open one bump pull request ([ADR 0071](0071-pull-request-with-the-evidence-report.md)). What is left is the schedule:

- choose which models to bump;
- open one pull request each;
- never open the same one twice;
- run inside GitHub Actions with as few rights as possible.

## Decision

1. **A model is due** when:
   - the code uses it (a call, a name, a string or a config value, not only a comment or a price table);
   - it is retired, or shuts down within `--within` days (90 by default, the same window as `RETIRING_SOON`);
   - the registry suggests a replacement that is not retired itself.

   A model that is due but cannot be bumped (no suggestion, or the suggestion is retired too) is listed with the reason, never guessed.
2. **`modelbump bump-all [PATH] --within DAYS [--open-pr]`** goes through the due models, soonest shutdown first:
   - without `--open-pr`, it lists what each bump would change;
   - with it, it runs the bump and opens the pull request for each one, as `bump --open-pr` does;
   - it stops at the first real error, such as a dirty working tree or a failed push.
3. **No duplicates.** The branch of a bump is always `modelbump/OLD-to-NEW`. When that branch is there, locally or on `origin`, the model is skipped. So a weekly run does nothing until its pull request is merged (and the branch deleted) or closed. The open pull request is the state; nothing else is stored.
4. **The Action** gets three inputs:
   - `open-prs`: `"false"` (default), `"dry-run"` (list them in the job summary), or `"true"` (open them);
   - `within`;
   - `github-token`, default `github.token`.

   The token reaches `gh` as `GH_TOKEN` through the environment, never on a command line. Commits are made by `github-actions[bot]` unless the workflow set a git author.
5. **Least privilege.** The workflow grants `contents: write` (push the branch) and `pull-requests: write` (open the pull request), and nothing else. The repository must allow GitHub Actions to create pull requests (Settings → Actions → General).
6. **Scheduled runs carry no test evidence.** Running models in CI would need either paid APIs or a large local model on a CPU runner. The pull request says that no test was run and how to add it. The developer can run `modelbump test` locally and re-bump with the evidence.

## Alternatives considered

- **Store state (a JSON file or an issue) of models already bumped:** more to keep in sync. The branch name already encodes the bump, and GitHub already shows whether its pull request is open.
- **One pull request for all due models:** fewer pull requests, but one hard model change would block every easy one. Dependabot opens one per dependency for the same reason.
- **Run the test in the scheduled job with Ollama on the runner:** possible with a small model, but slow (minutes per case on 2 CPUs), and the stand-in models would say little about the real ones. It can be added to a workflow by hand.
- **`pull_request_target` or a GitHub App:** more power than this needs.

## Consequences

- A repository adds one workflow file and gets bump pull requests on a schedule.
- Pull requests opened with the default `GITHUB_TOKEN` do not start other workflows (a GitHub rule against loops), so CI does not run on them until someone pushes. A fine-grained token in `github-token` avoids that.
- Closing a bump pull request without deleting its branch stops new ones for that model, which is a way to say "not now".
