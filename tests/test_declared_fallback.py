"""SA-05: a provably dead step gets a declared way out, and the specification is left alone.

The risk with this feature is not that it fails to work. It is that it quietly becomes a way
of turning red checks green -- editing the customer's setpoint, backing up the wrong step, or
losing the evidence that there was a contradiction at all. These tests are aimed at that.
"""

from __future__ import annotations

from specalive.emit.modelica import ModelicaEmitter
from specalive.ir.assumptions import AssumptionLog
from specalive.ir.fallback import apply_declared_fallbacks, find_blocked_transition
from specalive.ir.system import (
    Parameter,
    Quantity,
    Signal,
    State,
    StateMachine,
    SystemModel,
    Transition,
)
from specalive.verify.diagnose import Diagnosis


def _plant() -> SystemModel:
    """Two steps waiting on the same instrument at different setpoints."""
    return SystemModel(
        name="t",
        parameters=[
            Parameter(id="SP_FILL", name="SP_FILL", quantity=Quantity(value=0.18, unit="m")),
            Parameter(id="SP_IDLE", name="SP_IDLE", quantity=Quantity(value=0.01, unit="m")),
        ],
        signals=[
            Signal(id="LIS_501", name="LIS_501", role="sensor", binding="B5.level"),
        ],
        state_machines=[
            StateMachine(
                id="ctrl",
                name="ctrl",
                scan_period=0.1,
                states=[
                    State(id="Step4", name="Step4", initial=True),
                    State(id="Step5", name="Step5"),
                    State(id="Step6", name="Step6"),
                ],
                transitions=[
                    Transition(id="T45", source_state="Step4", target_state="Step5",
                               guard="LIS_501 < SP_IDLE"),
                    Transition(id="T56", source_state="Step5", target_state="Step6",
                               guard="LIS_501 >= SP_FILL"),
                ],
            )
        ],
    )


def _unreachable(signal="B5.level", target=0.18, extreme=0.1476, rise=216.0) -> Diagnosis:
    return Diagnosis(
        check_id="CHK", signal=signal, target=target, sense="rising", start=0.005,
        extreme=extreme, verdict="unreachable", detail="settled short", shortfall_pct=18.5,
        rise_seconds=rise, settled_at=678.0,
    )


# --------------------------------------------------------------------------- matching


def test_the_right_transition_is_backed_up():
    """Both steps watch LIS_501; only the one waiting on 0.18 is blocked."""
    m = _plant()
    t = find_blocked_transition(m, m.state_machines[0], "B5.level", 0.18)
    assert t is not None and t.id == "T56"


def test_the_threshold_must_match_not_just_the_instrument():
    """Backing up a step that was working would let the sequence skip it."""
    m = _plant()
    assert find_blocked_transition(m, m.state_machines[0], "B5.level", 0.99) is None


def test_matching_is_semantic_not_by_name_similarity():
    """The join is the sensor's plant binding. Break it and nothing is backed up."""
    m = _plant()
    m.signals[0].binding = "B9.pressure"
    assert find_blocked_transition(m, m.state_machines[0], "B5.level", 0.18) is None


# --------------------------------------------------------------------------- application


def test_the_specified_guard_is_never_touched():
    """The whole defence of this feature is that the customer's logic survives intact."""
    m = _plant()
    before = {t.id: t.guard for t in m.state_machines[0].transitions}
    apply_declared_fallbacks(m, [_unreachable()], AssumptionLog())
    after = {t.id: t.guard for t in m.state_machines[0].transitions if not t.declared_fallback}
    assert after == before


def test_the_fallback_is_a_separate_marked_transition():
    m = _plant()
    (fb,) = apply_declared_fallbacks(m, [_unreachable()], AssumptionLog())
    assert fb.declared_fallback and fb.fallback_for == "T56"
    assert (fb.source_state, fb.target_state) == ("Step5", "Step6")
    assert "SA-05" in (fb.provenance.note or "")


def test_the_dwell_comes_from_the_observed_rise_not_a_constant():
    m = _plant()
    (fb,) = apply_declared_fallbacks(m, [_unreachable(rise=216.0)], AssumptionLog())
    assert fb.dwell_timeout == 270.0  # 216 * 1.25

    m2 = _plant()
    (fb2,) = apply_declared_fallbacks(m2, [_unreachable(rise=400.0)], AssumptionLog())
    assert fb2.dwell_timeout == 500.0


def test_a_fast_signal_still_gets_a_floor():
    """A dwell of nearly zero would pre-empt a guard that was about to become true."""
    m = _plant()
    (fb,) = apply_declared_fallbacks(m, [_unreachable(rise=0.1)], AssumptionLog())
    assert fb.dwell_timeout == 2.0  # 20 scans of 0.1 s


def test_only_unreachable_verdicts_get_a_fallback():
    """A step that merely stalled is somebody else's fault; backing it up hides that."""
    m = _plant()
    d = _unreachable()
    d.verdict = "stalled"
    assert apply_declared_fallbacks(m, [d], AssumptionLog()) == []


def test_applying_twice_adds_one_fallback():
    """The second build pass must not stack a fallback on top of a fallback."""
    m = _plant()
    apply_declared_fallbacks(m, [_unreachable()], AssumptionLog())
    assert apply_declared_fallbacks(m, [_unreachable()], AssumptionLog()) == []
    assert sum(t.declared_fallback for t in m.state_machines[0].transitions) == 1


def test_the_assumption_is_declared_against_the_register():
    m = _plant()
    log = AssumptionLog()
    apply_declared_fallbacks(m, [_unreachable()], log)
    (a,) = log.assumptions
    assert a.basis == "SA-05-unreachable-guard-fallback"
    assert "LIS_501 >= SP_FILL" in a.statement, "the specified guard must be quoted verbatim"
    assert "FALLBACK" in (a.impact_if_wrong or ""), "must say how to find and undo it"


# --------------------------------------------------------------------------- emission


def test_emitted_modelica_keeps_both_exits_and_evaluates_the_specified_one_first():
    m = _plant()
    apply_declared_fallbacks(m, [_unreachable()], AssumptionLog())
    text = ModelicaEmitter(m, "P").emit()

    assert "LIS_501 >= SP_FILL" in text, "the customer's guard must still be in the model"
    assert "FALLBACK (SA-05)" in text, "and the addition must be findable"
    assert "tEnter_main" in text, "a dwell fallback needs an entry clock"
    assert "(time - pre(tEnter_main)) >= 270" in text
    # Order is what makes the specified guard authoritative when both are true in one scan.
    assert text.index("LIS_501 >= SP_FILL") < text.index("FALLBACK (SA-05)")


def test_no_dwell_clock_when_nothing_needs_one():
    """An unused discrete variable is noise in a model a judge is going to read."""
    assert "tEnter_" not in ModelicaEmitter(_plant(), "P").emit()
