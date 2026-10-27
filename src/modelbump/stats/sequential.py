"""Ask both models one more time until the verdict is clear (ADR 0042).

P4-1's interval is valid only if the number of answers is fixed in advance.
Checking it after every answer and stopping at the first REGRESSED raises
false alarms far above alpha (about 22% in our simulation at alpha = 0.05).

Here each round asks the old and the new model once and records
x = new_pass - old_pass, which is -1, 0 or +1 and has mean d, the true
difference in pass rate. For each claim we keep a "wealth" that grows when
the answers go against that claim's null hypothesis:

- REGRESSED: null d >= 0, bets on x being low.
- IMPROVED: null d <= 0, bets on x being high.
- EQUIVALENT: two nulls, d <= -margin and d >= +margin (the two one-sided
  tests of TOST); both wealths must win.

Each wealth is the average of 10 fixed bet sizes. Under its null it is a
nonnegative supermartingale that starts at 1, so by Ville's inequality the
chance it EVER reaches 1/alpha is at most alpha. That makes it safe to look
after every answer and stop at any time.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from modelbump.stats.item import DEFAULT_ALPHA, DEFAULT_MARGIN, Verdict

DEFAULT_MAX_RUNS = 200
BETS = 10
# Largest bet as a share of the most a round can lose; keeps every factor above 0.
_DIRECTION_CAP = 0.5
_EQUIVALENCE_CAP = 0.95


@dataclass
class _Wealth:
    """Average wealth of several fixed bets on y = sign * (x - centre) being positive."""

    sign: int
    centre: float
    cap: float
    values: list[float] = field(default_factory=lambda: [1.0] * BETS)

    def __post_init__(self) -> None:
        self._sizes = [self.cap * k / BETS for k in range(1, BETS + 1)]

    def add(self, x: int) -> None:
        y = self.sign * (x - self.centre)
        self.values = [w * (1 + size * y) for w, size in zip(self.values, self._sizes, strict=True)]

    @property
    def total(self) -> float:
        return sum(self.values) / BETS


@dataclass(frozen=True)
class Evidence:
    """How far each claim has got. A claim is proven when its number reaches 1/alpha."""

    regressed: float
    improved: float
    equivalent: float


class SequentialTest:
    """Feed in one old and one new pass/fail per round; read the verdict at any time."""

    def __init__(
        self,
        *,
        alpha: float = DEFAULT_ALPHA,
        margin: float = DEFAULT_MARGIN,
        max_runs: int = DEFAULT_MAX_RUNS,
    ) -> None:
        if not 0 < alpha < 0.5:
            raise ValueError(f"alpha must be between 0 and 0.5, got {alpha}")
        if not 0 <= margin < 1:
            raise ValueError(f"margin must be at least 0 and below 1, got {margin}")
        if max_runs < 1:
            raise ValueError(f"max_runs must be at least 1, got {max_runs}")
        self.alpha = alpha
        self.margin = margin
        self.max_runs = max_runs
        self.threshold = 1 / alpha
        self.runs = 0
        self.old_passes = 0
        self.new_passes = 0
        self.verdict = Verdict.INCONCLUSIVE
        # The worst a round can do to a bet is lose 1 (direction) or 1 - margin
        # (equivalence) per unit; caps keep each wealth factor positive.
        equivalence_cap = _EQUIVALENCE_CAP / (1 - margin)
        self._regressed = _Wealth(sign=-1, centre=0.0, cap=_DIRECTION_CAP)
        self._improved = _Wealth(sign=1, centre=0.0, cap=_DIRECTION_CAP)
        self._above_low = _Wealth(sign=1, centre=-margin, cap=equivalence_cap)
        self._below_high = _Wealth(sign=-1, centre=margin, cap=equivalence_cap)

    @property
    def done(self) -> bool:
        """True once a claim is proven or max_runs is reached."""
        return self.verdict is not Verdict.INCONCLUSIVE or self.runs >= self.max_runs

    @property
    def evidence(self) -> Evidence:
        return Evidence(
            regressed=self._regressed.total,
            improved=self._improved.total,
            equivalent=min(self._above_low.total, self._below_high.total),
        )

    def add(self, old_pass: bool, new_pass: bool) -> Verdict:
        """Record one answer from each model and return the verdict so far."""
        if self.done:
            raise ValueError("this test has already stopped; start a new SequentialTest")
        self.runs += 1
        self.old_passes += old_pass
        self.new_passes += new_pass
        x = int(new_pass) - int(old_pass)
        for wealth in (self._regressed, self._improved, self._above_low, self._below_high):
            wealth.add(x)
        evidence = self.evidence
        # Same order as P4-1: a drop smaller than the margin is not a regression.
        if evidence.equivalent >= self.threshold:
            self.verdict = Verdict.EQUIVALENT
        elif evidence.regressed >= self.threshold:
            self.verdict = Verdict.REGRESSED
        elif evidence.improved >= self.threshold:
            self.verdict = Verdict.IMPROVED
        return self.verdict


@dataclass(frozen=True)
class SequentialResult:
    verdict: Verdict
    runs: int
    old_passes: int
    new_passes: int
    evidence: Evidence

    @property
    def stopped_early(self) -> bool:
        return self.verdict is not Verdict.INCONCLUSIVE


def run_sequential(
    next_round: Callable[[], tuple[bool, bool]],
    *,
    alpha: float = DEFAULT_ALPHA,
    margin: float = DEFAULT_MARGIN,
    max_runs: int = DEFAULT_MAX_RUNS,
) -> SequentialResult:
    """Call next_round() for (old_pass, new_pass) until the verdict is clear or max_runs."""
    test = SequentialTest(alpha=alpha, margin=margin, max_runs=max_runs)
    while not test.done:
        test.add(*next_round())
    return SequentialResult(
        verdict=test.verdict,
        runs=test.runs,
        old_passes=test.old_passes,
        new_passes=test.new_passes,
        evidence=test.evidence,
    )
