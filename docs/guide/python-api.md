# Python API and what 1.x keeps stable

ModelBump follows [semantic versioning](https://semver.org/) from v1.0.0. Within 1.x, a release can add things but does not break what is listed here. A change that breaks one of them waits for 2.0.

## Stable in 1.x

- **The command line:** every command and option in the [command reference](cli.md), and the exit codes:
    - `0` means done;
    - `1` means something was found that should fail CI, such as a retired model with `--fail-within`, a REGRESSED case, a call that could not be repaired, or a failed push;
    - `2` means the command was used wrongly.
- **The GitHub Action:** its [inputs and outputs](action.md#inputs), and the `@v1` tag.
- **The file formats**, each marked with `"version": 1`: the suite file, the test report (`test --format json`), the patch file, the repair report, and the `.modelbump/` evidence folder. A 1.x release can add fields, but keeps reading version 1 files.
- **The Python names below.**

New registry dates are not breaking changes: a model can become `RETIRING_SOON` in a patch release, because that is the point of the tool.

## Python names

| Name | What it is |
|------|------------|
| `modelbump.registry.load_registry` | Load the retirement registry shipped with the package |
| `modelbump.registry.Registry` | The registry; `registry.get(model_id)` finds a model by ID or alias |
| `modelbump.registry.RetiredModel` | One model: ID, aliases, dates, suggested replacement |
| `modelbump.scanner.scan_path` | Scan a folder or file; returns a `ScanResult` |
| `modelbump.scanner.ScanResult` | Findings, files scanned, files skipped |
| `modelbump.scanner.Finding` | One model ID at one place: path, line, column, context |
| `modelbump.scanner.Context` | Where an ID sits: call argument, assignment, comment, ... |
| `modelbump.scanner.assess` | How urgent a model is on a given day; returns an `Assessment` |
| `modelbump.scanner.Assessment` | Severity, shutdown date, days left, replacement |
| `modelbump.scanner.Severity` | `RETIRED`, `RETIRING_SOON`, `DEPRECATED`, `UNKNOWN` |
| `modelbump.bump.plan_bump` | Plan a bump without writing anything; returns a `BumpPlan` |
| `modelbump.bump.BumpPlan` | The planned changes, skipped places, repairs and evidence |
| `modelbump.bump.apply_plan` | Write a plan, refusing files that changed since it was made |
| `modelbump.bump.plan_diff` | The plan as a unified diff |
| `modelbump.bump.BumpError` | Raised when a bump cannot go ahead, with a readable message |
| `modelbump.bump.load_evidence` | Read and check the suite, test report and repairs to attach |
| `modelbump.bump.Evidence` | The evidence files, redacted, ready to add |
| `modelbump.bump.due_models` | Models under a folder that are due for a bump |
| `modelbump.bump.DueModel` | One due model, with its replacement or the reason there is none |
| `modelbump.bump.pr_title` | The pull request title for a plan |
| `modelbump.bump.pr_body` | The pull request description (the evidence report) |
| `modelbump.bump.redact` | Replace secrets and email addresses in a text |

Everything else, including the runner, statistics, suite and repair modules, works and is tested, but its Python interface may change in a minor release. Use those through the command line.

## Example

```python
from datetime import date
from pathlib import Path

from modelbump.bump import plan_bump, plan_diff
from modelbump.registry import load_registry
from modelbump.scanner import Severity, assess, scan_path

registry = load_registry()
for finding in scan_path(Path("."), registry).findings:
    found = assess(finding.model_id, registry, date.today())
    if found.severity is Severity.RETIRED and found.replacement:
        plan = plan_bump(Path("."), registry, finding.model_id, found.replacement)
        print(plan_diff(plan))
```
