# Releasing the dataset

**Code:** `research/release/export.py` · **Decision:** [ADR 0020](../adr/0020-dataset-release-package.md) · **Output:** `research/data/release/`

The data files are not in git. This step packages them into one zip, without commit messages, ready to upload to Zenodo.

## Building the package

Run it after every earlier step, from the repo root:

```
uv run python -m research.release.export
```

It writes `research/data/release/modelbump-migrations-1.0.0/` and `modelbump-migrations-1.0.0.zip`, prints the rows in each file and the zip's SHA-256, and checks that no file has a `message` column. Use `--version` for a later release.

| File | Contents |
|------|----------|
| `candidates.csv` | Every commit found, with one field per filter rule and the labels |
| `migrations.csv` | Every `migration_away` commit, with its timing ([timing](timing.md)) and target ([targets](targets.md)) |
| `changed_files_sample.csv`, `changed_files.csv` | The RQ4 sample ([changed files](files.md)) |
| `validation*/` | The hand-label sheets, without the message column |
| `stats/` | Every step's stats file |
| `README.md`, `SHA256SUMS` | What the files are, and a checksum for each |

## Publishing on Zenodo

1. Sign in at [zenodo.org](https://zenodo.org) with GitHub, then choose **New upload**.
2. Upload the zip. Resource type: **Dataset**. Version: `1.0.0`. Licence: **CC BY 4.0**.
3. Fill in the title, the authors and the description from the package's README. Add the GitHub repository and Kim's arXiv paper as related works.
4. Click **Get a DOI now!** to reserve the DOI, then **Save** the draft. Do not publish yet: a published record cannot be deleted.
5. Put the reserved DOI in the dataset card's "Cite" section.

The record is published when the paper is submitted.
