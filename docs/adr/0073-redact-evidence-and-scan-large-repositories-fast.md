# ADR 0073: Redact secrets and email addresses from the evidence, and scan large repositories fast

- **Status:** Accepted
- **Date:** 2026-11-01

## Context

Before v1.0.0, ModelBump had a hardening pass on two risks.

**What gets committed.** A bump commits the test evidence to `.modelbump/` ([ADR 0070](0070-bump-adds-evidence-and-writes-repairs-into-the-code.md)). `test.json` holds every prompt, every answer and every error message. Three paths can carry private data into a public repository:

- a prompt that quotes a document, which the answers then repeat;
- an answer that invents or repeats an email address;
- an error message that quotes a key. ModelBump's runner sends keys in a header, never in a URL, but a server or proxy can still echo one back, and other tools that write these reports may put keys in URLs (Google's native API does).

The pull request description also shows each error message in its table ([ADR 0071](0071-pull-request-with-the-evidence-report.md)), so a key could reach the description too.

**Speed.** On a synthetic repository of 24,000 files (95 MB, 20,000 Python files, 40 using a model):

- `modelbump scan` took 19 s;
- `bump-all` took 34 s, because it scanned once to find the due models and again for each model.

Profiling showed where the time went:

- about 60% in the ID finder, which tried every word of every line;
- about 20% in tree-sitter, which parsed every Python file even when it held no ID;
- the rest in path handling for `--exclude`, which ran even when no pattern was given.

## Decision

1. **Redact before committing.** Every evidence file (`suite.json`, `test.json`, `repair.json`) is scanned, and each match is replaced with `[REDACTED:kind]`. The kinds are:
   - keys in the published formats of OpenAI, Anthropic, Google, GitHub, AWS, Groq, Hugging Face and Slack;
   - private key blocks, bearer tokens and JSON web tokens;
   - email addresses, except the reserved `example.com`, `example.org` and `example.net`.

   The bump prints what it replaced ("Redacted from the evidence: 1 OpenAI key, 2 email addresses"), and so does the pull request description.
2. **The redaction is safe for JSON.** It works on the file's text, so the layout stays as `modelbump test` wrote it. A match never starts right after a backslash, so it cannot split an escape such as `\n`. The result is parsed again to check it.
3. **The description is built from the redacted report**, and error messages in its table are cut to one line of at most 120 characters.
4. **A patch that holds a secret is refused**, because it would be written into the source code. Email addresses in patches are allowed, since a prompt may name a support address.
5. **Names, street addresses and phone numbers are not looked for.** A pattern cannot tell them from ordinary text without many false matches. The description always asks the reviewer to read `.modelbump/test.json` before merging.
6. **Scan faster, with the same results:**
   - The finder first checks whether a text, then a line, holds any registry ID or provider prefix (`gpt-`, `claude-`, `gemini-`, `text-embedding-`, `o` + digit). Every ID it can accept contains one of these, so skipping the rest changes nothing.
   - A file with no ID is not parsed.
   - Paths are matched against `--exclude` only when patterns were given.
   - `bump-all` scans once and passes the result to each model's plan (`due_models(result=)`, `plan_bump(result=)`).

## Results

On the same 24,000-file repository, with byte-identical scan reports before and after (also checked on this repository: 1,335 findings):

| Command | Before | After |
|---|---|---|
| `modelbump scan` | 19.0 s | 2.9 s |
| `modelbump bump-all` (dry run) | 34.4 s | 3.2 s |

A test compares the finder with the check turned off against the finder with it on, for every registry ID.

## Alternatives considered

- **Do not commit answers, only verdicts:** safer, but the evidence would no longer show *why* a case regressed, and a reviewer could not check the judge.
- **Redact by parsing and re-writing the JSON:** simpler escapes, but the file would no longer be byte for byte what `modelbump test` wrote, and the layout could change between versions.
- **A secret-scanning library (detect-secrets, gitleaks):** wider coverage, but a new dependency, or a binary, for a handful of patterns. GitHub's own secret scanning still runs on the pushed branch as a second net.
- **Look for names and phone numbers with a language model:** not free in CI, and not reliable enough to promise.
- **Parallel scanning with processes:** faster on many cores, but the single-process scan is now fast enough, and processes make errors and tests harder.

## Consequences

- `.modelbump/suite.json` is redacted too. When a prompt itself held a secret, `modelbump test .modelbump/suite.json` reruns with `[REDACTED:...]` in its place. Such a prompt should not hold a secret anyway.
- If an accepted patch searches for text that held an email address, `.modelbump/repairs.json` no longer fits the redacted suite. This needs a prompt that names an email address and a repair of exactly that sentence, which is rare.
- A key in a format not on the list is not caught. The list lives in one place (`modelbump.bump.redact`), and the reviewer is asked to read the file.
