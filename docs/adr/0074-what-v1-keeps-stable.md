# ADR 0074: What v1.0.0 keeps stable, a moving `v1` tag for the Action, and a generated command reference

- **Status:** Accepted
- **Date:** 2026-11-01

## Context

With `modelbump bump` ([ADR 0068](0068-bump-rewrites-ids-the-scanner-found.md) to [ADR 0073](0073-redact-evidence-and-scan-large-repositories-fast.md)), every stage of the plan is built. Version 1.0.0 is a promise to users, so it has to say what it promises. There are four kinds of user:

- people who type commands;
- workflows that call the Action;
- scripts that read ModelBump's files;
- a few who import it from Python.

Two things in the docs could also go stale. The docs pinned the Action to `@v0.1.0` and `@main`. And a hand-written list of options drifts from the code with every new flag.

## Decision

1. **Semantic versioning from 1.0.0.** Within 1.x, these do not break:
   - every command and option, and the exit codes (0 done, 1 something CI should fail on, 2 used wrongly);
   - the Action's inputs and outputs;
   - the file formats marked `"version": 1` (suite file, test report, patch file, repair report) and the `.modelbump/` folder;
   - a short list of Python names: the registry, scanner and bump entry points, listed in `docs/guide/python-api.md`.

   Other Python modules (runner, statistics, suite and repair internals) may change in a minor release. Their stable interface is the command line.
2. **Registry updates are not breaking changes.** A patch release can mark a model `RETIRING_SOON`, and CI that uses `--fail-within` can then fail. Warning early is the product.
3. **A moving major tag.** After a release reaches PyPI, the release workflow points the tag `v1` at it. Users write `uses: imhammad/modelbump@v1`, as with GitHub's own actions, and get fixes and new registry dates. A full tag such as `@v1.0.0` freezes the version.
4. **The command reference is generated** from the CLI (`modelbump.cli_reference`) into `docs/guide/cli.md`. A test fails when the page and the CLI differ. Other tests check that every listed Python name is exported, and that the docs pin the Action to `@v1`.
5. **A user guide** comes before the architecture pages: tutorial, how it works, the Action, the command reference, the stability promise, and an FAQ.
6. **The release:** the PR that merges this carries the commit footer `Release-As: 1.0.0`, so release-please leaves 0.x. The package classifier becomes "Production/Stable".

## Alternatives considered

- **Stay on 0.x until the papers are out:** but users judge a tool by its version. Everything 1.0 promises is built and tested, and staying on 0.x would only mean promising nothing.
- **Promise the whole Python API:** every internal refactor would become a major release. The command line is what people use.
- **mkdocstrings API pages:** generated from docstrings, but they would document internals as if they were stable. One page that lists the stable names is clearer.
- **A hand-written command reference:** reads better, but it would be wrong within weeks. The generated page uses the same help text as `--help`, which is already written for people.
- **Ask users to pin full tags only:** safe, but nobody gets new retirement dates without editing their workflow, and those dates are the point.

## Consequences

- A breaking change to a listed item now needs 2.0, an ADR, and a migration note.
- Adding an option means regenerating `docs/guide/cli.md`. The failing test says how.
- The `v1` tag is force-moved by the workflow. Anyone who needs a fixed version pins a full tag.
