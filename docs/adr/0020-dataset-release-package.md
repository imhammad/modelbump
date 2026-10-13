# ADR 0020: Publish the dataset on Zenodo as one versioned zip, without commit messages

- **Status:** Accepted
- **Date:** 2026-10-13

## Context

Paper 1 needs its data to be citable and permanent: empirical venues ask for a data availability statement, and a GitHub repository can be changed or deleted. The data files are gitignored ([dataset card](https://github.com/imhammad/modelbump/blob/main/research/data/README.md)), so they need a home of their own. Commit messages can hold names and email addresses (for example `Co-Authored-By` lines), and the dataset card already promises they will not be published.

## Decision

- **One command,** `uv run python -m research.release.export`, builds `research/data/release/modelbump-migrations-<version>/` and a zip of it.
- **Contents:** `candidates.csv` (every commit found, with every rule field and label), `migrations.csv` (each `migration_away` commit with its timing and target), `changed_files_sample.csv` and `changed_files.csv` (RQ4), the hand-label sheets of every validation sample, every step's stats file, a README and `SHA256SUMS`.
- **No commit messages.** The `message` column is dropped from every file, and the command fails if any CSV still has one. Each row keeps its commit URL, so the message can be fetched from GitHub again.
- **Plain CSV.** Lists are separated by spaces, booleans are `true` or `false`, and an empty cell means unknown, so the files open in any tool.
- **Reproducible.** The same data gives the same zip byte for byte (fixed file times and order), so its SHA-256 identifies the release.
- **Zenodo,** as a Dataset under CC BY 4.0, version 1.0.0. The DOI is reserved on a draft record first, so the paper can cite it before the record is published.

## Alternatives considered

- **Commit the data to the repository:** about 100 MB of CSV in git history, and messages would be one mistake away from being published.
- **Hugging Face Datasets:** convenient for ML users, but Zenodo gives a DOI that journals accept and is run by CERN for the long term.
- **Publish messages too:** easier to reuse, but against the dataset card's promise, and GitHub's terms leave the content with its authors.

## Consequences

- The paper can cite a DOI for the data.
- A new version of the data gets a new version on the same Zenodo record (`--version`).
- Rebuilding the message text needs a GitHub token and one request per commit.
