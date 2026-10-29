# ADR 0055: Check the judge against blind hand labels drawn by verdict, and correct pass rates for it

- **Status:** Accepted
- **Date:** 2026-10-29

## Context

[ADR 0054](0054-llm-judge-for-free-text.md) lets a local judge (Llama 3.1 8B) decide free-text scores. On the demo suite it failed 14% of Qwen 2.5's answers to one FAQ question and 22% of Qwen 3's, and the case came out INCONCLUSIVE. Whether those FAILs are real, or the judge being harsh, is unknown until people check. The master plan asks for about 200 hand labels, agreement with people, and a correction for judge bias. Three things shape the design:

- **FAILs are rare.** On the demo the judge passed most answers. A simple random sample of 200 would hold few FAILs, so the judge's errors on FAIL would be poorly measured.
- **Labels must be blind.** A person who sees the model name or the judge's verdict tends to agree with it.
- **No money, and Numbers on a Mac.** The labeller edits a CSV in a spreadsheet app and exports it back.

## Decision

- **`modelbump judge sheet REPORT.json`** reads a `modelbump test --format json` report. The report now also holds each case's messages and the reference answer the judge saw. The command draws `--size` judged answers (default 200, seed 2030), half where the judge said PASS and half where it said FAIL. When one verdict runs short, the other fills the rest. It writes:
  - a **sheet** (CSV): `item, prompt, reference, answer, your_label, note`, in shuffled order, with no model name and no judge verdict. Equal answers to the same case share one row.
  - a **key** (JSON): for each row, the case and every answer it stands for (model, sample, judge verdict), plus how many answers of each model the judge PASSed and FAILed in the whole report.
- **The person fills in `your_label`** with PASS or FAIL (also p/f, yes/no, 1/0, any case; blank rows are skipped), using the same definition as the judge's prompt.
- **`modelbump judge agreement SHEET KEY`** reports:
  - the share of judge PASSes the person also passed, and of judge FAILs the person also failed, each with a 95% Wilson interval, overall and per model;
  - agreement on the report's answers, weighted back from the sample (the sheet itself is half PASS and half FAIL);
  - Cohen's kappa on the sheet, marked as a sheet number;
  - **each model's corrected pass rate**: `P(judge PASS) × agree-on-PASS + P(judge FAIL) × (1 − agree-on-FAIL)`, with a range from the two intervals.
- **Assumption, stated in the report's docs:** given its verdict, the judge is as likely to be wrong on old answers as on new ones. The per-model agreement lines let a reader check it.
- **First a pilot, then the full set.** The demo suite has only 4 free-text prompts. So the first run is a 40-answer pilot on the demo to test the sheet and the workflow. The 200 labels for the paper come from the benchmark corpus (the next step), where the prompts are real and varied.

## Alternatives considered

- **Simple random sample:** unbiased for every number at once, but with few judge FAILs the error rate on FAIL, which drives the correction, would have a very wide interval.
- **Sampling by the person's label:** impossible, since the label is what is being collected.
- **Showing the judge's verdict to speed up labelling:** faster, but it anchors the labeller and inflates agreement.
- **Correcting with sensitivity and specificity (the Rogan-Gladen form):** equivalent in principle, but those need the person's labels as the sampling frame. With a sample drawn by judge verdict, agreement per verdict is what the sample estimates directly.
- **Two labellers and inter-rater agreement:** better, and Paper 1 had a second rater. It is left for the corpus labels if a second person is available.

## Consequences

- The judge's agreement with a person, and how much it moves each model's pass rate, can be reported with intervals.
- A verdict on a free-text case can be read against a measured judge, not an unmeasured one.
- Labels come from one person, so they measure agreement with that person. The paper must say who labelled and how.
- The correction is on pass rates per model, not on each case's verdict. Re-deciding single cases with a corrected judge is left for later.
