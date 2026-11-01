# ADR 0068: `modelbump bump` changes the model ID only where the scanner found it used, and shows a diff first

- **Status:** Accepted
- **Date:** 2026-10-31

## Context

Phase 7 ends in `modelbump bump`, which moves a repository from a retiring model to a new one and opens a pull request with the evidence. Its first job is the plainest one: change the model ID in the code. That sounds like find-and-replace, but a plain replace goes wrong in ways the scanner already knows about:

- **Not every mention is a use.** A comment such as `# claude-3-haiku is cheap` or a help string describes a model. The scanner marks these as documentation ([ADR 0031](0031-describing-contexts-and-test-files.md)).
- **Price and limit tables must keep the old key.** `PRICES = {"claude-3-haiku-20240307": (0.25, 1.25)}` lists the old model's prices. Renaming the key would give the new model the old model's prices.
- **Cloud platforms write their own IDs.** Bedrock's `anthropic.claude-3-haiku-20240307-v1:0` and Vertex AI's `claude-3-5-sonnet@20240620` are not the provider's ID. The new model's Bedrock or Vertex ID cannot be worked out from its provider ID (versions and dates differ), so a guess would be a broken ID.
- **Substring replace hits other models.** Replacing `gpt-4o` as text also changes `gpt-4o-mini`.

## Decision

1. **Edit only the characters the scanner found.** A bump plan runs the scanner, keeps findings that are the old model, and changes exactly those spans. The finder matches whole IDs ([ADR 0023](0023-scanner-finds-ids-as-text-first.md)), so `gpt-4o` never touches `gpt-4o-mini`, and a prefix such as `openai/` stays.
2. **The old model means its registry entry.** When the old ID is in the registry, its main ID and every alias are changed (`gpt-3.5-turbo` and `gpt-3.5-turbo-0125`). An ID not in the registry is matched exactly.
3. **What is changed and what is left alone:**

   | Place | Changed? |
   |-------|----------|
   | Call arguments, assignments, other strings, config values, files the scanner does not parse | Yes |
   | Comments, docstrings, sentences | Only with `--include-docs` |
   | Keys of price or limit tables | Never |
   | Bedrock and Vertex AI forms | Never |
   | Files that are not valid UTF-8 | Never |

   Every place left alone is printed with its reason and what to do, so nothing is skipped silently.
4. **A dry run by default.** `modelbump bump OLD [PATH] --to NEW` prints a unified diff and changes nothing. `--write` changes the files. Before writing, every file is checked against the text the plan was made from, and the bump stops if one changed.
5. **Files keep their bytes.** Files are read and written as UTF-8 bytes, so line endings (`\r\n`) and a byte-order mark stay as they were.
6. **The new model is checked.** Without `--to`, the registry's suggested replacement is used, and the command stops when there is none. A new model that is already retired is refused; one that is deprecated gets a warning. The new ID must look like a model ID (letters, digits and `._:/@-`), so a bump can never write quotes or code into a file.

## Alternatives considered

- **Plain text replace (`sed`):** simple, but changes comments, price tables, platform IDs and longer IDs that start with the old one.
- **Rewrite through the syntax tree:** precise for Python and TypeScript, but not for YAML, `.env`, Go or HTML, which the scanner handles as text. The scanner's spans are already exact in every file type, and the tree is already used to decide the context.
- **Write by default, like `git` tools that change files:** a bump touches many files, and the first run on a repository should show what it would do. `--write` is one flag away.
- **Map platform IDs with a table:** possible later, but Bedrock and Vertex IDs change on their own schedule. A wrong platform ID fails at runtime, so leaving it for a person is safer for now.

## Consequences

- `modelbump bump` is useful on its own today: the diff is the change a developer would make by hand.
- Tests that assert the model ID are changed too, since they are strings in code. `--exclude` keeps a folder out.
- Moving IDs into one config place, adding the suite, applying repairs and opening the pull request build on this plan in the next Phase 7 steps.
- Platform IDs and price tables always need a person; the output says where.
