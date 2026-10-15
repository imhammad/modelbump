# Paper 1

The LaTeX source of Paper 1, written for *Empirical Software Engineering* with the Springer Nature template ([ADR 0022](../docs/adr/0022-paper-in-latex.md)).

| Path | Contents |
|------|----------|
| `main.tex` | Preamble, title, authors and the order of the sections |
| `sections/` | One file per section; the abstract is `sections/abstract.tex` |
| `references.bib` | References. Add one only after checking it against the publisher's record |
| `generated/` | Every number, table and figure, written by `uv run python -m research.analysis.paper`. Never edit by hand |
| `sn-jnl.cls`, `sn-basic.bst` | The Springer Nature template's class and reference style, copied from the official template |
| `latexmkrc` | Build settings |

## Writing

- Write every number as its command from `generated/numbers.tex`, such as `\AfterLate\%`. Never type a number that the data produces.
- Put a table in with `\gentable{name}{tab:label}{Caption.}`, which reads `generated/tables/name.tex`.
- Mark open points with `\todo{...}`; they show in red, and CI lists each one as a warning on the pull request. The submitted PDF must have none:
  `grep -rn '\\todo{' paper --include='*.tex' | grep -v newcommand` must print nothing.
- Set `\anonymoustrue` in `main.tex` to hide the author, the repository and the DOI for double-anonymous review.

## Building

GitHub Actions builds the PDF on every pull request that changes `paper/` and keeps it as the `paper` artifact. To download it, find the run's ID, then download that run's artifact outside the repository:

```
gh run list --workflow paper.yml --limit 1
gh run download <run ID> --name paper --dir ~/Downloads/modelbump-paper
```

To build on your own computer, install a TeX distribution and run, from this folder:

```
latexmk -pdf main.tex
```
