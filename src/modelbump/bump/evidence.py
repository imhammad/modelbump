"""The evidence a bump adds to the repository, in ``.modelbump/`` (ADR 0070).

The bump does not call any model. The test and the repair are run before it,
with the models the developer picks (``modelbump test``, ``modelbump repair
run``), and the bump takes their files:

- ``.modelbump/suite.json``: the suite that was run;
- ``.modelbump/test.json``: the test report, every answer and verdict;
- ``.modelbump/repair.json``: the repair report, when there was one;
- ``.modelbump/repairs.json``: the accepted patches as one patch file, so
  ``modelbump test .modelbump/suite.json --patch .modelbump/repairs.json``
  reproduces the repaired run.

The files are copied as they are, so the evidence is exactly what was run,
except that secrets and email addresses are replaced with ``[REDACTED:kind]``
first (ADR 0073, :mod:`modelbump.bump.redact`). The pull request summary is
read from the redacted report too, so an error message cannot leak a key.
"""

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from modelbump.bump.redact import redact_json, secrets_in, total
from modelbump.repair import PromptPatch, apply_patches, patches_to_json, read_patches
from modelbump.repair.patch import PatchError
from modelbump.suite import Suite, read_suite

EVIDENCE_DIR = ".modelbump"


@dataclass(frozen=True, slots=True)
class Evidence:
    """The files a bump adds, read and checked."""

    suite: Suite | None = None
    suite_text: str | None = None
    test_text: str | None = None
    tested: tuple[str, str] | None = None
    """``(old, new)`` as the test report names them, e.g. ``ollama/qwen2.5:7b``."""
    repair_text: str | None = None
    accepted: tuple[PromptPatch, ...] = ()
    test_data: dict[str, Any] | None = None
    """The test report, redacted and parsed, for the pull request's summary."""
    redacted: dict[str, Counter[str]] = field(default_factory=dict)
    """Evidence file -> how many of each kind of secret was replaced in it."""

    @property
    def redacted_total(self) -> Counter[str]:
        """Everything replaced, over all the evidence files."""
        return total(self.redacted.values())

    def files(self) -> dict[str, str]:
        """Path in the repository -> text, for every evidence file."""
        out: dict[str, str] = {}
        if self.suite_text is not None:
            out[f"{EVIDENCE_DIR}/suite.json"] = self.suite_text
        if self.test_text is not None:
            out[f"{EVIDENCE_DIR}/test.json"] = self.test_text
        if self.repair_text is not None:
            out[f"{EVIDENCE_DIR}/repair.json"] = self.repair_text
        if self.accepted:
            out[f"{EVIDENCE_DIR}/repairs.json"] = patches_to_json(self.accepted)
        return out


def load_evidence(
    suite_file: Path | None = None,
    test_file: Path | None = None,
    repair_file: Path | None = None,
    proposals: Path | None = None,
    patch_file: Path | None = None,
) -> Evidence:
    """Read and check the files from ``modelbump suite``, ``test`` and ``repair run``.

    ``patch_file`` is a patch file to write into the code instead of the
    accepted repairs, such as a fix written by hand and checked with
    ``modelbump test --patch``. Raises ValueError with a readable message when
    a file is wrong or a needed one is missing.
    """
    if repair_file is not None and patch_file is not None:
        raise ValueError("give --repairs or --patch, not both")
    if suite_file is None and any(f is not None for f in (test_file, repair_file, patch_file)):
        raise ValueError("--report, --repairs and --patch need --suite, the suite that was run")
    if repair_file is not None and proposals is None:
        raise ValueError("--repairs needs --proposals, the folder from `modelbump repair propose`")
    suite = read_suite(suite_file) if suite_file is not None else None
    redacted: dict[str, Counter[str]] = {}
    suite_text = _redacted(suite_file, "suite.json", redacted)
    test_text = _redacted(test_file, "test.json", redacted)
    tested = None
    data: dict[str, Any] | None = None
    if test_file is not None and test_text is not None:
        data = _json(test_file, test_text)
        if data.get("version") != 1 or not isinstance(data.get("cases"), list):
            raise ValueError(
                f"{test_file} is not a JSON report from `modelbump test --format json`"
            )
        tested = (str(data.get("old")), str(data.get("new")))
    repair_text = _redacted(repair_file, "repair.json", redacted)
    accepted: tuple[PromptPatch, ...] = ()
    if repair_file is not None and repair_text is not None and proposals and suite is not None:
        accepted = _accepted(repair_file, repair_text, proposals, suite)
    if patch_file is not None and suite is not None:
        try:
            accepted = read_patches(patch_file)
            apply_patches(suite, accepted)
        except PatchError as error:
            raise ValueError(f"{patch_file} does not fit the suite: {error}") from error
    _check_patches(accepted)
    return Evidence(suite, suite_text, test_text, tested, repair_text, accepted, data, redacted)


def _check_patches(patches: tuple[PromptPatch, ...]) -> None:
    """Refuse a patch that would write a secret into the code (ADR 0073)."""
    for patch in patches:
        kinds = secrets_in(patches_to_json((patch,)))
        if kinds:
            raise ValueError(
                f"the patch for {patch.call} contains what looks like a secret "
                f"({', '.join(kinds)}); remove it from the patch and test again"
            )


def _redacted(path: Path | None, name: str, redacted: dict[str, Counter[str]]) -> str | None:
    text = _text(path)
    if text is None:
        return None
    result = redact_json(text, name)
    if result.found:
        redacted[f"{EVIDENCE_DIR}/{name}"] = result.found
    return result.text


def _accepted(path: Path, text: str, proposals: Path, suite: Suite) -> tuple[PromptPatch, ...]:
    data = _json(path, text)
    if data.get("version") != 1 or not isinstance(data.get("calls"), list):
        raise ValueError(f"{path} is not a JSON report from `modelbump repair run`")
    patches: list[PromptPatch] = []
    for call in data["calls"]:
        name = call.get("accepted")
        if name is None:
            continue
        file = proposals / str(name)
        if not file.is_file():
            raise ValueError(f"{path} accepts {name}, but {proposals} has no such file")
        try:
            (patch,) = read_patches(file)
        except ValueError as error:
            raise ValueError(f"{file} cannot be used: {error}") from error
        patches.append(patch)
    try:
        apply_patches(suite, tuple(patches))
    except PatchError as error:
        raise ValueError(f"the accepted patches do not fit the suite: {error}") from error
    return tuple(patches)


def _text(path: Path | None) -> str | None:
    if path is None:
        return None
    text = path.read_text(encoding="utf-8")
    return text if text.endswith("\n") else text + "\n"


def _json(path: Path, text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(f"{path} is not valid JSON: {error}") from error
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a ModelBump report")
    return data
