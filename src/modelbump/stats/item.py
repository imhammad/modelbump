"""Compare two models on one test case from pass/fail scores (ADR 0041).

Each model answers the same test case k times. An oracle marks each answer as
pass or fail. From the two pass counts we build an interval for the
difference in pass rate (new minus old) and turn it into one verdict:

- EQUIVALENT: the whole interval lies inside (-margin, +margin).
- REGRESSED: the whole interval lies below 0.
- IMPROVED: the whole interval lies above 0.
- INCONCLUSIVE: none of these; more answers are needed.

The interval is Newcombe's hybrid score interval for a difference of two
proportions, built from continuity-corrected Wilson intervals (Newcombe 1998,
method 11). At level 1 - 2*alpha, each one-sided claim (REGRESSED, IMPROVED,
or each half of the equivalence test, TOST) is wrong at most about alpha of
the time. The tests check this exactly for k up to 60.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from math import sqrt
from statistics import NormalDist

DEFAULT_ALPHA = 0.05
DEFAULT_MARGIN = 0.10


class Verdict(StrEnum):
    """What one comparison says about the new model on one test case."""

    REGRESSED = "REGRESSED"
    IMPROVED = "IMPROVED"
    EQUIVALENT = "EQUIVALENT"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True)
class Interval:
    """A closed interval [low, high]."""

    low: float
    high: float

    def __post_init__(self) -> None:
        if self.low > self.high:
            raise ValueError(f"low ({self.low}) is above high ({self.high})")


@dataclass(frozen=True)
class ItemComparison:
    """The result of comparing the old and the new model on one test case."""

    old_passes: int
    old_runs: int
    new_passes: int
    new_runs: int
    alpha: float
    margin: float
    interval: Interval
    verdict: Verdict

    @property
    def old_rate(self) -> float:
        return self.old_passes / self.old_runs

    @property
    def new_rate(self) -> float:
        return self.new_passes / self.new_runs

    @property
    def difference(self) -> float:
        """New pass rate minus old pass rate. Below 0 means the new model is worse."""
        return self.new_rate - self.old_rate

    @property
    def confidence(self) -> float:
        """Two-sided level of the interval, 1 - 2 * alpha."""
        return 1 - 2 * self.alpha


def _check_counts(passes: int, runs: int, name: str) -> None:
    if runs < 1:
        raise ValueError(f"{name} needs at least 1 run, got {runs}")
    if not 0 <= passes <= runs:
        raise ValueError(f"{name} passes must be between 0 and {runs}, got {passes}")


def _check_settings(alpha: float, margin: float) -> None:
    if not 0 < alpha < 0.5:
        raise ValueError(f"alpha must be between 0 and 0.5, got {alpha}")
    if not 0 <= margin < 1:
        raise ValueError(f"margin must be at least 0 and below 1, got {margin}")


def _z(alpha: float) -> float:
    """The normal quantile for a one-sided test at level alpha."""
    return NormalDist().inv_cdf(1 - alpha)


def wilson_interval(passes: int, runs: int, alpha: float = DEFAULT_ALPHA) -> Interval:
    """Continuity-corrected Wilson interval for a pass rate, at level 1 - 2 * alpha."""
    _check_counts(passes, runs, "wilson_interval")
    _check_settings(alpha, 0)
    z = _z(alpha)
    n = runs
    p = passes / n
    q = 1 - p
    denominator = 2 * (n + z * z)
    if passes == 0:
        low = 0.0
    else:
        low = 2 * n * p + z * z - 1 - z * sqrt(z * z - 2 - 1 / n + 4 * p * (n * q + 1))
        low /= denominator
    if passes == runs:
        high = 1.0
    else:
        high = 2 * n * p + z * z + 1 + z * sqrt(z * z + 2 - 1 / n + 4 * p * (n * q - 1))
        high /= denominator
    return Interval(max(0.0, low), min(1.0, high))


def difference_interval(
    old_passes: int,
    old_runs: int,
    new_passes: int,
    new_runs: int,
    alpha: float = DEFAULT_ALPHA,
) -> Interval:
    """Newcombe interval for new rate minus old rate, at level 1 - 2 * alpha."""
    _check_counts(old_passes, old_runs, "old model")
    _check_counts(new_passes, new_runs, "new model")
    old_rate = old_passes / old_runs
    new_rate = new_passes / new_runs
    old = wilson_interval(old_passes, old_runs, alpha)
    new = wilson_interval(new_passes, new_runs, alpha)
    difference = new_rate - old_rate
    low = difference - sqrt((new_rate - new.low) ** 2 + (old.high - old_rate) ** 2)
    high = difference + sqrt((new.high - new_rate) ** 2 + (old_rate - old.low) ** 2)
    return Interval(max(-1.0, low), min(1.0, high))


def _verdict(interval: Interval, margin: float) -> Verdict:
    # Equivalence comes first: a drop smaller than the margin is not a regression,
    # even when it is clearly there.
    if -margin < interval.low and interval.high < margin:
        return Verdict.EQUIVALENT
    if interval.high < 0:
        return Verdict.REGRESSED
    if interval.low > 0:
        return Verdict.IMPROVED
    return Verdict.INCONCLUSIVE


def compare_counts(
    old_passes: int,
    old_runs: int,
    new_passes: int,
    new_runs: int,
    *,
    alpha: float = DEFAULT_ALPHA,
    margin: float = DEFAULT_MARGIN,
) -> ItemComparison:
    """Compare two pass counts, for example 9 of 10 for the old model and 4 of 10 for the new."""
    _check_settings(alpha, margin)
    interval = difference_interval(old_passes, old_runs, new_passes, new_runs, alpha)
    return ItemComparison(
        old_passes=old_passes,
        old_runs=old_runs,
        new_passes=new_passes,
        new_runs=new_runs,
        alpha=alpha,
        margin=margin,
        interval=interval,
        verdict=_verdict(interval, margin),
    )


def compare_scores(
    old: Sequence[bool],
    new: Sequence[bool],
    *,
    alpha: float = DEFAULT_ALPHA,
    margin: float = DEFAULT_MARGIN,
) -> ItemComparison:
    """Compare two lists of pass (True) / fail (False) scores, one per answer."""
    return compare_counts(sum(old), len(old), sum(new), len(new), alpha=alpha, margin=margin)
