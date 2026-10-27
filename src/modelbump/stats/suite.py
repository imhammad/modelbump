"""Control false alarms across a whole test suite (ADR 0043).

Testing 300 test cases at alpha = 0.05 each gives about 15 false alarms when
nothing changed. Instead we control the false discovery rate (FDR): among the
test cases we call REGRESSED, the expected share that did not really regress
is at most q.

- `benjamini_hochberg` is the classic BH procedure for p-values (Benjamini and
  Hochberg, JRSS-B 57(1), 1995). It is here for fixed-k baselines.
- `e_benjamini_hochberg` is e-BH for e-values (Wang and Ramdas, JRSS-B 84(3),
  2022). It controls FDR under any dependence between test cases, and the
  wealths of ADR 0042 are e-values at whatever time a test case stops.

`run_suite` runs one sequential test per test case, each stopping as soon as
its wealth reaches m/q (enough for e-BH on its own), then applies e-BH to each
claim (REGRESSED, IMPROVED, EQUIVALENT) at level q.
"""

import random
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from modelbump.stats.item import DEFAULT_MARGIN, Verdict
from modelbump.stats.sequential import DEFAULT_MAX_RUNS, Evidence, SequentialTest

DEFAULT_FDR = 0.05


def _check_q(q: float) -> None:
    if not 0 < q < 1:
        raise ValueError(f"q must be between 0 and 1, got {q}")


def benjamini_hochberg(p_values: Sequence[float], q: float = DEFAULT_FDR) -> list[bool]:
    """Which hypotheses to reject so that the false discovery rate is at most q."""
    _check_q(q)
    m = len(p_values)
    if any(not 0 <= p <= 1 for p in p_values):
        raise ValueError("p-values must be between 0 and 1")
    order = sorted(range(m), key=lambda i: p_values[i])
    cutoff = 0
    for rank, index in enumerate(order, start=1):
        if p_values[index] <= q * rank / m:
            cutoff = rank
    rejected = set(order[:cutoff])
    return [i in rejected for i in range(m)]


def e_benjamini_hochberg(e_values: Sequence[float], q: float = DEFAULT_FDR) -> list[bool]:
    """e-BH: reject the k largest e-values, for the largest k with k-th largest >= m/(q*k)."""
    _check_q(q)
    m = len(e_values)
    if any(e < 0 for e in e_values):
        raise ValueError("e-values cannot be negative")
    order = sorted(range(m), key=lambda i: e_values[i], reverse=True)
    cutoff = 0
    for rank, index in enumerate(order, start=1):
        if e_values[index] >= m / (q * rank):
            cutoff = rank
    rejected = set(order[:cutoff])
    return [i in rejected for i in range(m)]


@dataclass(frozen=True)
class SuiteItem:
    """One test case after the suite has been decided."""

    name: str
    verdict: Verdict
    runs: int
    old_passes: int
    new_passes: int
    evidence: Evidence


@dataclass(frozen=True)
class SuiteResult:
    items: tuple[SuiteItem, ...]
    q: float
    margin: float

    @property
    def counts(self) -> Counter[Verdict]:
        return Counter(item.verdict for item in self.items)

    @property
    def total_runs(self) -> int:
        """Answers asked of each model, summed over test cases."""
        return sum(item.runs for item in self.items)

    def named(self, verdict: Verdict) -> list[str]:
        return [item.name for item in self.items if item.verdict is verdict]


def decide_suite(evidence: Sequence[Evidence], q: float = DEFAULT_FDR) -> list[Verdict]:
    """Turn each test case's evidence into a verdict, with e-BH for each claim."""
    equivalent = e_benjamini_hochberg([e.equivalent for e in evidence], q)
    regressed = e_benjamini_hochberg([e.regressed for e in evidence], q)
    improved = e_benjamini_hochberg([e.improved for e in evidence], q)
    verdicts = []
    for is_equivalent, is_regressed, is_improved in zip(
        equivalent, regressed, improved, strict=True
    ):
        # Same order as ADRs 0041 and 0042.
        if is_equivalent:
            verdicts.append(Verdict.EQUIVALENT)
        elif is_regressed:
            verdicts.append(Verdict.REGRESSED)
        elif is_improved:
            verdicts.append(Verdict.IMPROVED)
        else:
            verdicts.append(Verdict.INCONCLUSIVE)
    return verdicts


def run_suite(
    items: Mapping[str, Callable[[], tuple[bool, bool]]],
    *,
    q: float = DEFAULT_FDR,
    margin: float = DEFAULT_MARGIN,
    max_runs: int = DEFAULT_MAX_RUNS,
) -> SuiteResult:
    """Run every test case until its verdict is clear, then control FDR at q per claim.

    `items` maps a test case's name to a function that returns one fresh
    (old_pass, new_pass) pair each time it is called.
    """
    _check_q(q)
    if not items:
        raise ValueError("the suite has no test cases")
    m = len(items)
    tests = []
    for next_round in items.values():
        # Stopping at m/q is enough for e-BH to reject this test case on its own.
        test = SequentialTest(alpha=q / m, margin=margin, max_runs=max_runs)
        while not test.done:
            test.add(*next_round())
        tests.append(test)
    verdicts = decide_suite([test.evidence for test in tests], q)
    return SuiteResult(
        items=tuple(
            SuiteItem(
                name=name,
                verdict=verdict,
                runs=test.runs,
                old_passes=test.old_passes,
                new_passes=test.new_passes,
                evidence=test.evidence,
            )
            for name, test, verdict in zip(items, tests, verdicts, strict=True)
        ),
        q=q,
        margin=margin,
    )


SIMULATED_PASS_RATES = (0.6, 0.8, 0.9, 1.0)


@dataclass(frozen=True)
class SimulatedSuite:
    """Made-up test cases with known true pass rates, for checking the engine."""

    items: dict[str, Callable[[], tuple[bool, bool]]]
    true_rates: dict[str, tuple[float, float]]

    def really_worse(self, name: str) -> bool:
        old, new = self.true_rates[name]
        return new < old


def simulated_suite(size: int, regressed: int, drop: float, seed: int) -> SimulatedSuite:
    """A suite of `size` test cases; the first `regressed` lose `drop` of pass rate."""
    if not 0 <= regressed <= size:
        raise ValueError(f"regressed must be between 0 and {size}, got {regressed}")
    if not 0 < drop <= 1:
        raise ValueError(f"drop must be above 0 and at most 1, got {drop}")
    picker = random.Random(seed)
    items: dict[str, Callable[[], tuple[bool, bool]]] = {}
    true_rates: dict[str, tuple[float, float]] = {}
    for index in range(size):
        name = f"case-{index + 1:03d}"
        old = picker.choice(SIMULATED_PASS_RATES)
        new = max(0.0, old - drop) if index < regressed else old
        answers = random.Random(f"{seed}-{index}")

        def next_round(
            answers: random.Random = answers, old: float = old, new: float = new
        ) -> tuple[bool, bool]:
            return answers.random() < old, answers.random() < new

        items[name] = next_round
        true_rates[name] = (old, new)
    return SimulatedSuite(items=items, true_rates=true_rates)
