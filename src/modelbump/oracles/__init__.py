"""Oracles: decide whether an answer still does the job (ADR 0052)."""

from modelbump.oracles.choose import OracleChoice, OutputKind, choose_oracle, normalize_label
from modelbump.oracles.score import (
    Check,
    Reference,
    Score,
    build_reference,
    find_label,
    parse_json,
    score,
)

__all__ = [
    "Check",
    "OracleChoice",
    "OutputKind",
    "Reference",
    "Score",
    "build_reference",
    "choose_oracle",
    "find_label",
    "normalize_label",
    "parse_json",
    "score",
]
