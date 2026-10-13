"""Package the migration dataset for publication on Zenodo (ADR 0020).

Reads research/data and writes one folder and one zip file:

    research/data/release/modelbump-migrations-<version>/
    research/data/release/modelbump-migrations-<version>.zip

The package holds commit SHAs, repositories, URLs, dates, every rule field
and label, the derived timing, target and changed-file fields, and the hand
labels, but no commit messages: they can contain names and email addresses,
and anyone can fetch them again from GitHub with the URL (dataset card,
"Ethics and licence"). Every file is listed in SHA256SUMS, and the zip is the
same byte for byte when it is built again from the same data.

Run from the repo root:
    uv run python -m research.release.export
"""

import argparse
import csv
import hashlib
import shutil
import sys
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from research.filtering.filter import read_jsonl

VERSION = "1.0.0"
NAME = "modelbump-migrations"
REPO_URL = "https://github.com/imhammad/modelbump"

CANDIDATE_FIELDS = (
    "sha",
    "repo",
    "repos",
    "url",
    "committed_at",
    "matched_ids",
    "providers",
    "migration_word",
    "direction",
    "after_notice_start",
    "bot",
    "ai_trailer",
    "ai_style",
    "migration",
    "migration_strict",
    "migration_with_ai",
    "migration_away",
)
TIMING_FIELDS = (
    "sha",
    "repo",
    "url",
    "committed",
    "model_id",
    "provider",
    "notice",
    "shutdown",
    "shutdown_is_earliest",
    "phase",
    "days_from_shutdown",
    "in_kim_window",
)
TARGET_FIELDS = (
    "target",
    "target_method",
    "target_provider",
    "same_provider",
    "recommended",
    "follows",
    "target_retired_list",
    "target_announced_before",
    "target_shut_down_before",
    "ai_assisted",
    "tier_change",
    "generation_change",
)
SAMPLE_FIELDS = (
    "sha",
    "repo",
    "url",
    "model_id",
    "target",
    "ai_assisted",
    "found",
    "http_status",
    "file_count",
    "truncated",
    "touches_test",
    "adds_test",
    "test_mentions_model",
    "touches_eval",
    "adds_eval",
    "touches_prompt",
    "touches_code",
    "id_swap_only",
)
FILE_FIELDS = ("sha", "path", "status", "kind", "additions", "deletions")
STATS = ("candidates", "labeled", "timing", "timing_90d", "lag", "targets", "files")
VALIDATION_DIRS = (
    "validation",
    "validation_adjudicated",
    "validation_v2",
    "validation_v2_adjudicated",
    "validation_files",
)
# Columns never published: the commit message, in any of the sheets.
PRIVATE = {"message"}
# A fixed time for every file in the zip, so the same data gives the same zip.
ZIP_TIME = (2026, 1, 1, 0, 0, 0)


class MissingInputs(Exception):
    """Some input files are not there yet."""


def cell(value: Any) -> str:
    """One CSV cell: lists joined by spaces, None as empty, booleans as true/false."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return " ".join(str(v) for v in value)
    return str(value)


def write_csv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> int:
    """Write ``rows`` with exactly ``fields``; return how many rows were written."""
    count = 0
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(fields)
        for row in rows:
            writer.writerow([cell(row.get(name)) for name in fields])
            count += 1
    return count


def migrations(
    timing: Iterable[Mapping[str, Any]], targets: Iterable[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """One row per migration: its timing joined with its target, by SHA."""
    by_sha = {row["sha"]: row for row in targets}
    out = []
    for row in timing:
        target = by_sha.get(row["sha"], {})
        out.append(
            {**{k: row.get(k) for k in TIMING_FIELDS}, **{k: target.get(k) for k in TARGET_FIELDS}}
        )
    return out


def changed_files(sample: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """One row per changed file of the fetched sample commits."""
    return [{"sha": row["sha"], **f} for row in sample if row.get("found") for f in row["files"]]


def copy_without_private(source: Path, target: Path) -> None:
    """Copy a CSV sheet, leaving out the PRIVATE columns."""
    with source.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fields = [name for name in reader.fieldnames or [] if name not in PRIVATE]
        rows = list(reader)
    write_csv(target, fields, rows)


def header(path: Path) -> list[str]:
    """The column names of a CSV file."""
    with path.open(newline="", encoding="utf-8") as f:
        return next(csv.reader(f), [])


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


# The package's files, for its README: name, row-count key (or None), contents.
FILES = (
    (
        "candidates.csv",
        "candidates",
        "Every commit found: SHA, repository, URL, commit time, the retired model IDs it "
        "names, one field per filter rule, and the labels. `migration_away` is the main label",
    ),
    (
        "migrations.csv",
        "migrations",
        "Every `migration_away` commit: the model it leaves, that model's notice and shutdown "
        "dates, the phase and days from the shutdown, and the model it moves to",
    ),
    (
        "changed_files_sample.csv",
        "sample",
        "A random sample of migrations (seed 2028): whether each touches tests, evaluations "
        "or prompts, and whether it only swaps a model ID",
    ),
    (
        "changed_files.csv",
        "files",
        "The changed files of those sample commits, each with its kind",
    ),
    ("validation*/", None, "The hand labels behind the quality numbers, without commit messages"),
    ("stats/", None, "The counts printed by each step, as JSON"),
    ("SHA256SUMS", None, "A checksum for every file"),
)


def files_table(counts: Mapping[str, int]) -> str:
    """The README's table of files, with row counts."""
    lines = ["| File | Rows | Contents |", "|------|------|----------|"]
    for name, key, text in FILES:
        rows = f"{counts[key]:,}" if key else ""
        lines.append(f"| `{name}` | {rows} | {text} |")
    return "\n".join(lines)


def readme(version: str, counts: Mapping[str, int]) -> str:
    """The README that travels with the package."""
    return f"""# LLM model migrations on GitHub, version {version}

Commits from public GitHub repositories whose message names an LLM model that
its provider (OpenAI, Anthropic or Google) has retired or plans to retire,
labelled by whether the commit moves the project away from that model, with
when it happened relative to the model's shutdown, which model it moved to,
and, for a random sample, which files it changed.

Built with the code at {REPO_URL} (research/), which follows the method of
H. L. Kim, "When the Model Retires: An Empirical Study of LLM Migration in
Open-Source Applications", arXiv:2609.31288, 2026. The full dataset card,
with how the data was built, its quality and its limits, is
research/data/README.md in that repository.

## Files

{files_table(counts)}

Lists in a cell (such as `matched_ids`) are separated by spaces. Booleans are
`true` or `false`; an empty cell means unknown or not applicable.

## Commit messages

No commit message is included, because messages can contain names and email
addresses. Each row has the commit URL, so the message can be fetched again
from GitHub's API (`GET /repos/{{owner}}/{{repo}}/commits/{{sha}}`).

## Licence

The labels and derived fields are released under CC BY 4.0
(https://creativecommons.org/licenses/by/4.0/). The commits themselves belong
to their authors and repositories.

## Cite

Please cite this dataset with its Zenodo DOI, and Kim (2026) for the method.
"""


def build(data: Path, out: Path, version: str) -> tuple[Path, Path, dict[str, int]]:
    """Write the package folder and its zip; return both paths and the row counts."""
    needed = [
        data / "labeled.jsonl",
        data / "timing.jsonl",
        data / "targets.jsonl",
        data / "files.jsonl",
        *(data / f"{name}.stats.json" for name in STATS),
        *(data / name for name in VALIDATION_DIRS),
    ]
    missing = [str(path) for path in needed if not path.exists()]
    if missing:
        raise MissingInputs("\n".join(f"  {path}" for path in missing))

    folder = out / f"{NAME}-{version}"
    if folder.exists():
        shutil.rmtree(folder)
    (folder / "stats").mkdir(parents=True)
    counts = {
        "candidates": write_csv(
            folder / "candidates.csv", CANDIDATE_FIELDS, read_jsonl(data / "labeled.jsonl")
        ),
        "migrations": write_csv(
            folder / "migrations.csv",
            (*TIMING_FIELDS, *TARGET_FIELDS),
            migrations(read_jsonl(data / "timing.jsonl"), read_jsonl(data / "targets.jsonl")),
        ),
    }
    sample = list(read_jsonl(data / "files.jsonl"))
    counts["sample"] = write_csv(folder / "changed_files_sample.csv", SAMPLE_FIELDS, sample)
    counts["files"] = write_csv(folder / "changed_files.csv", FILE_FIELDS, changed_files(sample))
    for name in STATS:
        shutil.copyfile(data / f"{name}.stats.json", folder / "stats" / f"{name}.stats.json")
    for name in VALIDATION_DIRS:
        (folder / name).mkdir()
        for source in sorted((data / name).iterdir()):
            if source.suffix == ".csv":
                copy_without_private(source, folder / name / source.name)
            elif source.suffix == ".json":
                shutil.copyfile(source, folder / name / source.name)
    (folder / "README.md").write_text(readme(version, counts), encoding="utf-8")

    files = sorted(p for p in folder.rglob("*") if p.is_file())
    sums = "".join(f"{sha256(p)}  {p.relative_to(folder).as_posix()}\n" for p in files)
    (folder / "SHA256SUMS").write_text(sums, encoding="utf-8")

    archive = out / f"{NAME}-{version}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(p for p in folder.rglob("*") if p.is_file()):
            info = zipfile.ZipInfo(f"{folder.name}/{path.relative_to(folder).as_posix()}", ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, path.read_bytes())
    return folder, archive, counts


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=Path, default=Path("research/data"))
    parser.add_argument("--out", type=Path, default=Path("research/data/release"))
    parser.add_argument("--version", default=VERSION)
    args = parser.parse_args(argv)
    try:
        folder, archive, counts = build(args.data, args.out, args.version)
    except MissingInputs as missing:
        print(f"Missing inputs:\n{missing}", file=sys.stderr)
        return 1
    print(f"Written: {folder}/")
    for name, count in counts.items():
        print(f"  {name:<12}{count:>9,} rows")
    size = archive.stat().st_size / 1e6
    print(f"Zip: {archive} ({size:.1f} MB)")
    print(f"SHA-256 of the zip: {sha256(archive)}")
    leaked = [str(p) for p in sorted(folder.rglob("*.csv")) if PRIVATE & set(header(p))]
    if leaked:
        print(f"ERROR: a private column is still in {', '.join(leaked)}", file=sys.stderr)
        return 1
    print("Checked: no file has a commit message column.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
