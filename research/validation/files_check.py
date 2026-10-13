"""Check the file kinds by hand: does the commit really touch tests or evaluations?

With no option, draws 100 of the commits fetched by research.enrichment.files
and writes a blind sheet, ``sample.csv``, that lists each commit's changed
files but not what the code decided. The code's answers go to
``sample_key.csv``, to be opened only after labelling (ADR 0018).

With ``--score``, compares the hand labels with the code's answers: agreement,
Cohen's kappa, and how many of the code's "yes" and "no" answers were right.
The code's answers come from ``sample_key.csv``, frozen when the sheet was
drawn. Add ``--current`` to take them from ``files.jsonl`` instead, after the
file rules changed and research.enrichment.files was run again. Report both:
the frozen score is the one measured before the rules saw the labels.

Run from the repo root:
    uv run python -m research.validation.files_check
    uv run python -m research.validation.files_check --score
    uv run python -m research.validation.files_check --score --current
"""

import argparse
import csv
import random
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from research.filtering.filter import read_jsonl
from research.validation.score import ANSWERS, cohen_kappa, wilson

SIZE = 100
SEED = 2029
MAX_FILES = 80  # files listed per commit; the URL shows the rest
QUESTIONS = {"has_test": "touches_test", "has_eval": "touches_eval"}


def file_list(row: Mapping[str, Any]) -> str:
    """The changed files as "A path; M path; ...", with the status letter first."""
    letters = {"added": "A", "removed": "D", "renamed": "R", "modified": "M"}
    files = row["files"][:MAX_FILES]
    text = "; ".join(f"{letters.get(f['status'], '?')} {f['path']}" for f in files)
    extra = len(row["files"]) - len(files)
    return text + (f"; ... and {extra} more" if extra > 0 else "")


def draw(rows: Sequence[dict[str, Any]], size: int, seed: int) -> list[dict[str, Any]]:
    """A random sample of the fetched commits, the same for the same data and seed."""
    found = sorted((r for r in rows if r["found"]), key=lambda r: r["sha"])
    return found if size >= len(found) else random.Random(seed).sample(found, size)


def write_sheet(picked: Sequence[dict[str, Any]], out_dir: Path) -> None:
    """Write the blind sheet and the key."""
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "sample.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["n", "url", "files", *QUESTIONS, "note"])
        for n, row in enumerate(picked, start=1):
            writer.writerow([n, row["url"], file_list(row), "", "", ""])
    with (out_dir / "sample_key.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["n", "sha", *QUESTIONS.values()])
        for n, row in enumerate(picked, start=1):
            writer.writerow([n, row["sha"], *(row[k] for k in QUESTIONS.values())])


def read_hand(path: Path) -> dict[str, dict[int, str]]:
    """{question: {n: "yes" | "no"}} for every recognised answer."""
    answers: dict[str, dict[int, str]] = {q: {} for q in QUESTIONS}
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            for q in QUESTIONS:
                answer = ANSWERS.get(row.get(q, "").strip().lower())
                if answer in ("yes", "no"):
                    answers[q][int(row["n"])] = answer
    return answers


def read_key(path: Path) -> dict[str, dict[int, str]]:
    """The code's answers, in the same shape as read_hand."""
    key: dict[str, dict[int, str]] = {q: {} for q in QUESTIONS}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            for q, column in QUESTIONS.items():
                key[q][int(row["n"])] = "yes" if row[column] == "True" else "no"
    return key


def read_current(files: Path, key_path: Path) -> dict[str, dict[int, str]]:
    """The code's answers from files.jsonl as it is now, for the sheet's commits."""
    with key_path.open(newline="", encoding="utf-8") as f:
        shas = {int(row["n"]): row["sha"] for row in csv.DictReader(f)}
    rows = {r["sha"]: r for r in read_jsonl(files) if r.get("found")}
    current: dict[str, dict[int, str]] = {q: {} for q in QUESTIONS}
    for n, sha in shas.items():
        if sha in rows:
            for q, column in QUESTIONS.items():
                current[q][n] = "yes" if rows[sha][column] else "no"
    return current


def compare(hand: Mapping[int, str], code: Mapping[int, str]) -> dict[str, Any]:
    """Agreement, kappa, and the confusion counts for one question."""
    shared = sorted(set(hand) & set(code))
    cells = {(h, c): 0 for h in ("yes", "no") for c in ("yes", "no")}
    for n in shared:
        cells[(hand[n], code[n])] += 1
    kappa, _ = cohen_kappa({n: hand[n] for n in shared}, {n: code[n] for n in shared})
    return {
        "n": len(shared),
        "agree": cells[("yes", "yes")] + cells[("no", "no")],
        "kappa": kappa,
        "both_yes": cells[("yes", "yes")],
        "code_only": cells[("no", "yes")],
        "hand_only": cells[("yes", "no")],
        "both_no": cells[("no", "no")],
    }


def score(out_dir: Path, files: Path | None = None) -> int:
    """Print how the code's answers compare with the hand labels.

    The code's answers come from the key, or from ``files`` when it is given.
    """
    sheet, key_path = out_dir / "sample.csv", out_dir / "sample_key.csv"
    if not sheet.exists() or not key_path.exists():
        print(f"{sheet} or {key_path} not found. Draw the sheet first.", file=sys.stderr)
        return 1
    if files is not None and not files.exists():
        print(f"{files} not found. Run research.enrichment.files first.", file=sys.stderr)
        return 1
    hand = read_hand(sheet)
    if not any(hand.values()):
        print(f"No answers in {sheet} yet (has_test and has_eval: yes or no).", file=sys.stderr)
        return 1
    if files is None:
        code = read_key(key_path)
        print(f"Code answers from {key_path} (the rules when the sheet was drawn).")
    else:
        code = read_current(files, key_path)
        print(f"Code answers from {files} (the rules as they are now).")
    for q in QUESTIONS:
        c = compare(hand[q], code[q])
        if not c["n"]:
            print(f"\n{q}: no answers")
            continue
        low, high = wilson(c["agree"], c["n"])
        print(f"\n{q} ({c['n']} commits labelled):")
        print(
            f"  agreement      {c['agree']} of {c['n']} = {100 * c['agree'] / c['n']:.1f}%"
            f"  (95% CI {100 * low:.1f} to {100 * high:.1f})"
        )
        print(f"  Cohen's kappa  {c['kappa']:.2f}")
        print(
            f"  both yes {c['both_yes']}, both no {c['both_no']}, "
            f"code only {c['code_only']}, hand only {c['hand_only']}"
        )
        hand_yes = c["both_yes"] + c["hand_only"]
        print(f"  hand says yes: {hand_yes}; code finds {c['both_yes']} of them")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--files", type=Path, default=Path("research/data/files.jsonl"))
    parser.add_argument("--dir", type=Path, default=Path("research/data/validation_files"))
    parser.add_argument("--score", action="store_true", help="Score the labelled sheet.")
    parser.add_argument(
        "--current", action="store_true", help="With --score: the code's answers from --files."
    )
    parser.add_argument("--size", type=int, default=SIZE)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args(argv)
    if args.score:
        return score(args.dir, args.files if args.current else None)
    if not args.files.exists():
        print(f"{args.files} not found. Run research.enrichment.files first.", file=sys.stderr)
        return 1
    if (args.dir / "sample.csv").exists():
        print(
            f"{args.dir / 'sample.csv'} already exists. It may hold your labels, so it is "
            "not overwritten.",
            file=sys.stderr,
        )
        return 1
    picked = draw(list(read_jsonl(args.files)), args.size, args.seed)
    write_sheet(picked, args.dir)
    print(f"Wrote {len(picked)} commits to {args.dir / 'sample.csv'} (seed {args.seed}).")
    print(f"Do not open {args.dir / 'sample_key.csv'} until you have labelled them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
