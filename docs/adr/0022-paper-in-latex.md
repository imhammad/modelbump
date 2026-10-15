# ADR 0022: Write Paper 1 in LaTeX in this repository, with the Springer Nature template

- **Status:** Accepted
- **Date:** 2026-10-14

## Context

Paper 1 goes to *Empirical Software Engineering*, a Springer journal that accepts LaTeX submissions with the Springer Nature template. Every number in the paper already comes from `paper/generated/` ([ADR 0019](0019-paper-numbers-from-one-script.md)), so the text must be able to use those commands directly. The paper also needs a history of changes and a check that it still builds after each one, like the code.

## Decision

- **LaTeX in `paper/`,** next to the code that makes its numbers, built with `latexmk -pdf main.tex`. `main.tex` holds the preamble and the order of the sections; each section is a file in `paper/sections/`.
- **The official template.** `sn-jnl.cls` with the `sn-basic` reference style (author and year), copied from Springer Nature's template package. The class is under the LaTeX Project Public License, so it can be kept in the repository.
- **Numbers by command only.** The text writes `\AfterLate`, never 62.2. Tables come from `generated/tables/` through `\gentable`, which shrinks a table only if it is wider than the text. The class's table caption does not allow a `tabular` inside a box after it, so `\gentable` boxes the table before the caption.
- **Checked references.** Every entry in `references.bib` is checked against its Crossref record, arXiv page or proceedings page before it is added.
- **CI.** A workflow (`paper.yml`) installs TeX Live from Ubuntu, builds the PDF on every pull request that changes `paper/`, fails on any LaTeX error or undefined reference or citation, and uploads the PDF.
- **Anonymous switch.** `\anonymoustrue` hides the author, the repository and the dataset DOI, in case the journal asks for double-anonymous review.

## Alternatives considered

- **Overleaf:** convenient for editing, but the numbers would have to be copied in by hand after every run, and the history would live outside the repository.
- **Word:** accepted by the journal, but it cannot read generated numbers.
- **One `.tex` file:** what Springer asks for at submission, but harder to review in pull requests. A single file can be produced at submission time.

## Consequences

- Rerunning `research.analysis.paper` updates every number in the paper at the next build.
- A wrong command name fails the build instead of printing a wrong number.
- At submission, the sections and generated files are merged into one `.tex` file, and the template files are not submitted.
