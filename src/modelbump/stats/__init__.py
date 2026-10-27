"""Stats engine: decide whether a new model is worse than the old one (ADRs 0041-0043)."""

from modelbump.stats.item import (
    DEFAULT_ALPHA,
    DEFAULT_MARGIN,
    Interval,
    ItemComparison,
    Verdict,
    compare_counts,
    compare_scores,
    difference_interval,
    wilson_interval,
)
from modelbump.stats.sequential import (
    DEFAULT_MAX_RUNS,
    Evidence,
    SequentialResult,
    SequentialTest,
    run_sequential,
)
from modelbump.stats.suite import (
    DEFAULT_FDR,
    SimulatedSuite,
    SuiteItem,
    SuiteResult,
    benjamini_hochberg,
    decide_suite,
    e_benjamini_hochberg,
    run_suite,
    simulated_suite,
)

__all__ = [
    "DEFAULT_ALPHA",
    "DEFAULT_FDR",
    "DEFAULT_MARGIN",
    "DEFAULT_MAX_RUNS",
    "Evidence",
    "Interval",
    "ItemComparison",
    "SequentialResult",
    "SequentialTest",
    "SimulatedSuite",
    "SuiteItem",
    "SuiteResult",
    "Verdict",
    "benjamini_hochberg",
    "compare_counts",
    "compare_scores",
    "decide_suite",
    "difference_interval",
    "e_benjamini_hochberg",
    "run_sequential",
    "run_suite",
    "simulated_suite",
    "wilson_interval",
]
