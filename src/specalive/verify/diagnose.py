"""Turn failed acceptance checks into a diagnosis, not just a tally.

A red check says the model did not do what the procedure asked. It does not say why, and the
difference matters more than the count: a threshold the plant approached and fell short of is
evidence that the *specification* is self-contradictory, while a threshold on a signal that
never moved at all is a knock-on from something that stalled upstream. Reporting seven
contradictions when there is one is as misleading as reporting none.

The brief requires contradictions to be flagged rather than resolved arbitrarily. Flagging
them is the part that is not optional, so this module does it from the strongest evidence
available -- the simulation itself. Static reachability analysis missed the NaCl case because
it needed upstream geometry the extractor never found; a run that plateaus 18% short of a
setpoint needs no such inference.

This module only diagnoses. Whether to then give a dead sequence a declared fallback exit is
SA-05 in config/assumptions.yaml, and a separate decision.

Owner: D.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..ir.assumptions import AssumptionLog
from ..ir.evidence import Gap
from ..ir.system import SystemModel
# Reuse the scorer's own parser and column resolution rather than a second copy. A diagnosis
# that disagreed with the check it is explaining would be worse than no diagnosis, and the
# first version of this module did exactly that -- its private regex expected infix syntax
# and silently matched nothing, so every contradiction went unflagged while the run looked fine.
from .acceptance import _CROSSES, ExpressionError, _series

#: A signal is "flat" when its whole excursion is this small a fraction of the distance it
#: needed to travel. Deliberately generous: this separates "never started" from "tried and
#: fell short", it does not measure anything.
_FLAT_FRACTION = 0.02

#: Travelled at least this fraction of the way and then stopped: the plant is doing its best
#: and the number is out of reach, rather than merely unmet.
_NEAR_MISS = 0.60

#: The tail of the run used to decide whether a signal has settled.
_TAIL_FRACTION = 0.15


@dataclass
class Diagnosis:
    check_id: str
    signal: str
    target: float
    sense: str
    start: float
    extreme: float
    #: "unreachable" (plateaued short), "stalled" (never moved), "unsettled" (still moving
    #: when the run ended -- the stop time may simply be too short).
    verdict: str
    detail: str
    shortfall_pct: float
    #: How long the quantity spent actually moving: from the first appreciable change to the
    #: last. This is what a declared fallback dwell is derived from -- the time the plant
    #: genuinely needed to reach its limit, rather than a number somebody chose.
    rise_seconds: float = 0.0
    #: Absolute time of the last appreciable change, for the report.
    settled_at: float = 0.0


def _motion_window(times: list[float], series: list[float]) -> tuple[float, float]:
    """(first move, last move) in seconds -- the interval the quantity spent actually moving.

    Measured against where it started and where it ended up, not sample to sample. The first
    version compared consecutive samples against a fraction of the whole excursion, which on
    a smooth ramp is never exceeded by any single step: it reported a rise time of zero for a
    tank that took 600 s to fill, and a fallback dwell derived from that fired almost
    immediately and cut the fill short.
    """
    if len(series) < 2 or len(times) < len(series):
        return 0.0, (times[-1] if times else 0.0)
    span = max(series) - min(series)
    if span <= 0:
        return 0.0, times[-1]
    eps = _FLAT_FRACTION * span
    begin, final = series[0], series[-1]

    first = next((times[i] for i, v in enumerate(series) if abs(v - begin) >= eps), times[0])
    last = next(
        (times[i] for i in range(len(series) - 1, -1, -1) if abs(series[i] - final) >= eps),
        times[-1],
    )
    return first, max(first, last)


def _tail_is_flat(series: list[float], span: float) -> bool:
    """True when the last slice of the run barely moves relative to the whole excursion."""
    if len(series) < 8 or span <= 0:
        return True
    tail = series[-max(3, int(len(series) * _TAIL_FRACTION)):]
    return (max(tail) - min(tail)) <= _FLAT_FRACTION * span


def diagnose(model: SystemModel, card: Any, cols: dict[str, list[float]]) -> list[Diagnosis]:
    """Classify every failed threshold check against the trace that failed it."""
    by_expr = {chk.id: chk.expression for sc in model.scenarios for chk in sc.checks}
    out: list[Diagnosis] = []
    for res in card.results:
        if res.passed:
            continue
        m = _CROSSES.search(by_expr.get(res.check_id, ""))
        if not m:
            continue
        sig, target, sense = m.group(1), float(m.group(2)), (m.group(3) or "rising")
        try:
            series = _series(cols, sig)
        except ExpressionError:
            continue
        if not series:
            continue

        start = series[0]
        extreme = max(series) if sense == "rising" else min(series)
        needed = abs(target - start)
        travelled = abs(extreme - start)
        remaining = abs(target - extreme)
        span = max(series) - min(series)
        shortfall = 100.0 * remaining / needed if needed else 0.0
        t_first, t_last = _motion_window(cols.get("time") or [], series)

        if needed == 0 or travelled <= _FLAT_FRACTION * max(needed, 1e-12):
            verdict = "stalled"
            detail = (
                f"{sig} never moved from {start:.4g}; nothing upstream drove it, so this "
                f"check is a consequence of an earlier failure rather than a defect here"
            )
        elif not _tail_is_flat(series, span):
            verdict = "unsettled"
            detail = (
                f"{sig} reached {extreme:.4g} of the required {target:.4g} and was still "
                f"moving when the run ended; the stop time may simply be too short"
            )
        elif travelled >= _NEAR_MISS * needed:
            verdict = "unreachable"
            detail = (
                f"{sig} settled at {extreme:.4g} against a required {target:.4g}, having "
                f"travelled {travelled:.4g} of the {needed:.4g} needed ({shortfall:.1f}% "
                f"short) and then stopped changing. Under the parameters the evidence itself "
                f"supplies, this setpoint cannot be reached: the specification asks for "
                f"something its own numbers forbid"
            )
        else:
            verdict = "unreachable"
            detail = (
                f"{sig} settled at {extreme:.4g}, far short of the required {target:.4g} "
                f"({shortfall:.1f}% short), and stopped changing"
            )
        out.append(
            Diagnosis(
                res.check_id, sig, target, sense, start, extreme, verdict, detail, shortfall,
                rise_seconds=max(0.0, t_last - t_first),
                settled_at=t_last,
            )
        )
    return out


def record(
    model: SystemModel,
    diagnoses: list[Diagnosis],
    log: AssumptionLog | None = None,
    *,
    already_known: set[str] | None = None,
    pass_no: int = 1,
) -> list[Gap]:
    """File the contradictions as gaps, and ask about them. Knock-ons are noted, not shouted.

    One gap per *root cause*. Several checks can fail on the same unreachable setpoint and on
    the same stalled predecessor, and a report that lists each one separately buries the
    finding it should be leading with.

    `already_known` carries the check ids whose contradiction a previous pass already proved.
    They are skipped rather than re-diagnosed: once a declared fallback is in place the step
    exits early, so the final trace no longer contains the evidence, and re-reading it would
    downgrade a proved contradiction to "still moving when the run ended". The finding
    belongs to the pass that earned it.
    """
    known = already_known or set()
    diagnoses = [d for d in diagnoses if d.check_id not in known]
    seq = sum(1 for g in model.gaps if g.id.startswith("GAP-GUARD-"))

    def _gid() -> str:
        nonlocal seq
        seq += 1
        return f"GAP-GUARD-{seq:02d}"

    gaps: list[Gap] = []
    unreachable = [d for d in diagnoses if d.verdict == "unreachable"]
    stalled = [d for d in diagnoses if d.verdict == "stalled"]
    unsettled = [d for d in diagnoses if d.verdict == "unsettled"]

    for d in unreachable:
        subject = (
            f"{d.signal} >= {d.target:g}" if d.sense == "rising" else f"{d.signal} <= {d.target:g}"
        )
        gaps.append(
            Gap(
                id=_gid(),
                kind="unreachable_guard",
                subject=subject,
                detail=d.detail
                + (f". Proved on pass {pass_no}." if pass_no > 1 else "."),
                severity="blocking",
                workaround=(
                    "Not resolved here. Moving the setpoint to one the plant can reach would "
                    "turn the check green and hide a defect in the specification, which is "
                    "the opposite of what is wanted. Reported as found."
                ),
            )
        )
        if log is not None:
            log.ask(
                subject=d.check_id,
                question=(
                    f"The procedure requires {d.signal} to reach {d.target:g}, but under the "
                    f"parameters given elsewhere in the same packet it settles at "
                    f"{d.extreme:.4g}. Which governs, the setpoint or the sizing?"
                ),
                why_it_matters=(
                    "These two numbers come from the same evidence and cannot both hold. Any "
                    "model that satisfies one violates the other, so the step cannot be "
                    "verified either way until the customer says which is authoritative."
                ),
                blocking=True,
                searched=[d.check_id, d.signal],
                interim=(
                    "The setpoint is left exactly as specified and the check is reported as "
                    "failing, rather than retuned to produce a green result."
                ),
            )

    if stalled:
        gaps.append(
            Gap(
                id=_gid(),
                kind="unreachable_guard",
                subject=", ".join(sorted({d.check_id for d in stalled})),
                detail=(
                    f"{len(stalled)} further check(s) failed on signals that never moved at "
                    f"all: {', '.join(sorted({d.signal for d in stalled}))}. These sit "
                    f"downstream of the step(s) above; the sequence never reached them, so "
                    f"they are consequences rather than separate defects."
                ),
                severity="info",
                workaround="Re-run once the root cause above is settled.",
            )
        )
    if unsettled:
        gaps.append(
            Gap(
                id=_gid(),
                kind="unreachable_guard",
                subject=", ".join(sorted({d.check_id for d in unsettled})),
                detail=(
                    f"{len(unsettled)} check(s) failed on signals still moving towards their "
                    f"target when the run ended. The stop time, not the physics, may be the "
                    f"limit."
                ),
                severity="warn",
                workaround="Re-run with a longer stop time before reading anything into these.",
            )
        )
    return gaps
