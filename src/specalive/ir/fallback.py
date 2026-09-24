"""Give a provably dead sequence step a declared way out (SA-05).

When a guard is proved unreachable, the sequence deadlocks and everything after it is
unverifiable -- one defect in the customer's specification costs us the whole rest of the
run. There are three things you can do about that:

  1. Retune the setpoint to one the plant can reach. The checks go green and the defect
     disappears. This is the dishonest option and we do not do it.
  2. Leave the sequence dead and report it. Honest, and what we did until now, but it tells
     a reviewer nothing about the twelve steps that were never exercised.
  3. Keep the customer's guard *exactly as written*, add a second, clearly marked fallback
     transition beside it, and flag the contradiction. The specified logic stays legible and
     intact, the rest of the sequence gets exercised, and the report leads with the defect.

This module does (3), which the brief permits: the contradiction is flagged rather than
resolved arbitrarily, and the resolution cites SA-05 in config/assumptions.yaml -- registered
before the code that spends it.

Two things keep this from being a cheat. The fallback is a *separate* transition, so the
emitted Modelica and the SysML both still contain the setpoint the customer specified, and a
reader can see what was asked for and what we did instead. And the dwell is derived from the
trace -- the time the quantity actually spent moving before it stopped -- rather than tuned
until the checks pass.

Owner: D.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .assumptions import AssumptionLog
from .system import StateMachine, SystemModel, Transition

#: Margin on the observed rise time. The plant took `rise` seconds to reach its limit from a
#: cold start; a step entered mid-batch has less to do, so this is generous rather than tight.
_DWELL_MARGIN = 1.25

#: A fallback never fires faster than this many scan periods, so it cannot pre-empt a guard
#: that was simply about to become true.
_MIN_DWELL_SCANS = 20

#: `LIS_501 >= SP_B5_BATCH` / `TIS_602 <= 293.15` -- the comparison a step waits on.
_COMPARE = re.compile(r"\b(?P<sig>[A-Za-z_]\w*)\s*(?P<op>>=|<=|>|<)\s*(?P<rhs>[A-Za-z_]\w*|[-+0-9.eE]+)")


def _resolve(token: str, model: SystemModel) -> float | None:
    """A guard's right-hand side is either a literal or a parameter id. Resolve either."""
    try:
        return float(token)
    except ValueError:
        pass
    for p in model.parameters:
        if p.id == token or p.name == token:
            if isinstance(p.quantity.value, (int, float)):
                return float(p.quantity.value)
    return None


def _sensors_reading(model: SystemModel, plant_signal: str) -> set[str]:
    """Sensor ids and names bound to a plant quantity like 'B5.level'.

    The diagnosis speaks in plant terms because that is what the result file contains; guards
    speak in instrument tags because that is what the procedure contains. This is the join
    between them, and it is the reason this matching is semantic rather than a guess from
    similar-looking ids.
    """
    want = plant_signal.replace("_", ".").lower()
    out: set[str] = set()
    for s in model.signals:
        if s.role != "sensor" or not s.binding:
            continue
        if s.binding.replace("_", ".").lower() == want:
            out.update({s.id, s.name})
    return out


def find_blocked_transition(
    model: SystemModel, sm: StateMachine, plant_signal: str, target: float
) -> Transition | None:
    """The transition whose guard waits on exactly this quantity and this threshold.

    Matching on the resolved *number* as well as the tag matters: a plant signal is usually
    watched by several steps at different setpoints, and backing up the wrong one would let
    the sequence skip a step that was working.
    """
    tags = _sensors_reading(model, plant_signal)
    if not tags:
        return None
    for t in sm.transitions:
        if t.declared_fallback:
            continue
        for m in _COMPARE.finditer(t.guard):
            if m.group("sig") not in tags:
                continue
            value = _resolve(m.group("rhs"), model)
            if value is not None and abs(value - target) <= 1e-9 * max(1.0, abs(target)):
                return t
    return None


@dataclass
class FallbackPlan:
    """What this pass did, and what it refused to judge until the next one."""

    added: list[Transition] = field(default_factory=list)
    #: Checks on steps downstream of something we are fixing now. Their verdict was measured
    #: against a trace where an upstream step was still deadlocked, so it is not evidence of
    #: anything and must not be recorded as a contradiction. The next pass re-measures.
    deferred: set[str] = field(default_factory=set)

    def __bool__(self) -> bool:
        return bool(self.added)


def apply_declared_fallbacks(
    model: SystemModel, diagnoses: list[Any], log: AssumptionLog | None = None
) -> FallbackPlan:
    """Add a fallback beside the earliest guard in each region that was proved unreachable.

    Returns what was added and what was deferred. An empty `added` is the signal the pipeline
    uses to stop repeating the build.
    """
    # Gather first, then fix the *earliest* blocked step in each region and nothing behind it.
    #
    # Fixing a whole cascade at once looks efficient and is wrong. A step downstream of a
    # deadlock is diagnosed from a trace in which it barely ran, so its dwell is derived from
    # how long it moved before something else stopped it -- not from how long the plant needs.
    # That manufactured a contradiction we then reported as the customer's: Step6 was given a
    # 172 s dwell measured while Step5 was still deadlocked, evaporation was cut short, and
    # B5.w was declared 58% short of a setpoint it reaches comfortably once Step5 can exit.
    # Reporting a defect we caused is worse than reporting none, so each pass fixes one step
    # per region and re-measures. Parallel branches are independent and may be fixed together.
    candidates: list[tuple[Any, StateMachine, Transition]] = []
    for d in diagnoses:
        if getattr(d, "verdict", None) != "unreachable":
            continue
        for sm in model.state_machines:
            blocked = find_blocked_transition(model, sm, d.signal, d.target)
            if blocked is not None:
                candidates.append((d, sm, blocked))
                break

    earliest: dict[tuple[int, str], tuple[Any, StateMachine, Transition]] = {}
    for d, sm, blocked in candidates:
        src = sm.state(blocked.source_state)
        region = src.region if src else "main"
        index = next(
            (i for i, st in enumerate(sm.states) if st.id == blocked.source_state), 0
        )
        key = (id(sm), region)
        if key not in earliest or index < earliest[key][3]:  # type: ignore[misc]
            earliest[key] = (d, sm, blocked, index)  # type: ignore[assignment]

    chosen = {id(blocked) for _, _, blocked, _ in earliest.values()}  # type: ignore[misc]
    plan = FallbackPlan(
        deferred={d.check_id for d, _, blocked in candidates if id(blocked) not in chosen}
    )
    added = plan.added
    for d, sm, blocked, _ in earliest.values():  # type: ignore[misc]
        if any(t.fallback_for == blocked.id for t in sm.transitions):
            continue  # already backed up on an earlier pass

        dwell = max(
            round(d.rise_seconds * _DWELL_MARGIN, 3),
            _MIN_DWELL_SCANS * sm.scan_period,
        )
        fb = Transition(
            id=f"{blocked.id}__FALLBACK",
            source_state=blocked.source_state,
            target_state=blocked.target_state,
            guard=f"dwell({blocked.source_state}) >= {dwell:g}",
            effect=blocked.effect,
            forks=list(blocked.forks),
            joins=list(blocked.joins),
            declared_fallback=True,
            fallback_for=blocked.id,
            dwell_timeout=dwell,
            provenance=blocked.provenance.model_copy(
                update={
                    "note": (
                        f"Declared fallback under SA-05. Not specified by the customer. "
                        f"The specified guard {blocked.guard!r} was proved unreachable: "
                        f"{d.signal} settles at {d.extreme:.4g} against a required "
                        f"{d.target:g}."
                    )
                }
            ),
        )
        sm.transitions.append(fb)
        added.append(fb)

        if log is not None:
            log.assume(
                subject=blocked.id,
                statement=(
                    f"{blocked.source_state} also exits after {dwell:g} s in the step, "
                    f"alongside the specified guard {blocked.guard!r}, which the "
                    f"simulation proves can never become true"
                ),
                basis="SA-05-unreachable-guard-fallback",
                what_was_missing=(
                    f"any exit from {blocked.source_state} that the plant can actually "
                    f"reach: the specified setpoint and the equipment sizing come from "
                    f"the same packet and contradict each other"
                ),
                value=dwell,
                unit="s",
                impact_if_wrong=(
                    f"Search the emitted .mo for FALLBACK. The specified guard is still "
                    f"there, unchanged, and is still evaluated first; removing the "
                    f"fallback restores the deadlock. The dwell is "
                    f"{_DWELL_MARGIN:g}x the {d.rise_seconds:g} s the quantity spent "
                    f"moving before it settled."
                ),
            )
    return plan
