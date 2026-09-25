"""Rule 6.3: nothing is invented silently.

These tests guard the three behaviours the brief names explicitly -- missing information is
either assumed with a stated basis or asked about, contradictions are flagged rather than
resolved, and nothing is fabricated without a declared convention behind it.
"""

from __future__ import annotations

import pytest

from specalive.ir.assumptions import AssumptionLog, load_register
from specalive.ir.system import SystemModel
from specalive.verify.diagnose import diagnose, record


# --------------------------------------------------------------------------- the register


def test_every_register_entry_is_reviewable():
    """A convention a reviewer cannot check or overturn is not a declared assumption."""
    register = load_register()
    assert register, "config/assumptions.yaml did not load"
    for aid, entry in register.items():
        for field in ("title", "applies_when", "rule", "basis", "challenge", "risk"):
            assert entry.get(field), f"{aid} has no {field}"
        assert entry["risk"] in {"low", "medium", "high"}


def test_unregistered_basis_is_refused():
    """The whole point of the register is that a basis cannot be invented at the call site."""
    log = AssumptionLog()
    with pytest.raises(KeyError, match="not in the register"):
        log.assume(subject="B1.x", statement="x = 1", basis="SA-made-up", what_was_missing="x")


def test_unfounded_is_allowed_but_counted():
    """Forbidding it would push people back to guessing silently, which is worse."""
    log = AssumptionLog()
    log.assume(subject="B1.x", statement="x = 1", basis=None, what_was_missing="x")
    assert len(log.unfounded) == 1

    model = SystemModel(name="t")
    log.attach(model)
    assert model.coverage()["assumptions_unfounded"] == 1


def test_assume_and_ask_links_both_records():
    log = AssumptionLog()
    a, q = log.assume_and_ask(
        subject="B1.level_start",
        statement="level_start = 1.6",
        basis="SA-02-initial-inventory",
        what_was_missing="the starting level of B1",
        question="How full is B1 at the start?",
        why_it_matters="Nothing runs without it.",
    )
    assert a.question_id == q.id
    assert a.basis_text, "the register's title should be copied onto the record"
    assert a.impact_if_wrong, "the register's challenge should be copied onto the record"


def test_attach_renumbers_across_several_logs():
    """Two logs both number from 1. Merging by id alone dropped the second log's findings.

    This is the bug that lost two blocking questions about a proved contradiction, so it gets
    a test rather than a comment.
    """
    model = SystemModel(name="t")

    first = AssumptionLog()
    first.assume_and_ask(
        subject="B1", statement="s1", basis=None, what_was_missing="m1",
        question="q1?", why_it_matters="w1",
    )
    first.attach(model)

    second = AssumptionLog()
    second.assume_and_ask(
        subject="B2", statement="s2", basis=None, what_was_missing="m2",
        question="q2?", why_it_matters="w2",
    )
    second.attach(model)

    assert len(model.questions) == 2, "the second log's question was dropped"
    assert len(model.assumptions) == 2
    assert len({q.id for q in model.questions}) == 2, "ids collided"
    # The back-reference must survive renumbering, or the report links an assumption to
    # somebody else's question -- which reads as traceable and is not.
    by_id = {q.id: q for q in model.questions}
    pairs = {(a.subject, by_id[a.question_id].question) for a in model.assumptions}
    assert pairs == {("B1", "q1?"), ("B2", "q2?")}


# --------------------------------------------------------------------------- diagnosis


class _Res:
    def __init__(self, check_id: str, passed: bool) -> None:
        self.check_id, self.passed = check_id, passed


class _Card:
    def __init__(self, results):
        self.results = results


def _model_with(checks: dict[str, str]) -> SystemModel:
    from specalive.ir.system import AcceptanceCheck, Scenario

    return SystemModel(
        name="t",
        scenarios=[
            Scenario(
                id="SCN",
                name="s",
                checks=[
                    AcceptanceCheck(id=cid, description=cid, expression=expr)
                    for cid, expr in checks.items()
                ],
            )
        ],
    )


def test_plateau_short_of_target_is_a_contradiction():
    """Travelled most of the way, then stopped: the spec asks for what its numbers forbid."""
    rise = [0.005 + 0.0014 * i for i in range(100)]          # climbs to ~0.144
    series = rise + [rise[-1]] * 60                           # then settles
    cols = {"time": list(range(len(series))), "B5.level": series}
    model = _model_with({"CHK": "crosses(B5.level, 0.18, rising)"})

    (d,) = diagnose(model, _Card([_Res("CHK", False)]), cols)
    assert d.verdict == "unreachable"
    assert 15 < d.shortfall_pct < 30

    gaps = record(model, [d])
    assert [g.severity for g in gaps] == ["blocking"]
    assert gaps[0].kind == "unreachable_guard"
    # The contradiction must be reported, not resolved.
    assert "hide a defect" in gaps[0].workaround


def test_a_signal_that_never_moved_is_a_knock_on_not_a_defect():
    """Five reds from one stall must not be reported as five contradictions."""
    flat = [293.1] * 120
    cols = {"time": list(range(120)), "B6.T": flat, "B7.T": flat}
    model = _model_with(
        {
            "CHK-A": "crosses(B6.T, 293.15, falling)",
            "CHK-B": "crosses(B7.T, 298.15, falling)",
        }
    )
    ds = diagnose(model, _Card([_Res("CHK-A", False), _Res("CHK-B", False)]), cols)
    assert {d.verdict for d in ds} == {"stalled"}

    gaps = record(model, ds)
    assert len(gaps) == 1, "one gap per root cause, not one per symptom"
    assert gaps[0].severity == "info"
    assert "consequences" in gaps[0].detail


def test_still_moving_at_the_end_blames_the_stop_time_not_the_physics():
    climbing = [0.0 + 0.001 * i for i in range(120)]
    cols = {"time": list(range(120)), "B3.level": climbing}
    model = _model_with({"CHK": "crosses(B3.level, 0.5, rising)"})
    (d,) = diagnose(model, _Card([_Res("CHK", False)]), cols)
    assert d.verdict == "unsettled"
    assert record(model, [d])[0].severity == "warn"


def test_passing_checks_are_not_diagnosed():
    cols = {"time": [0, 1], "B3.level": [0.0, 1.0]}
    model = _model_with({"CHK": "crosses(B3.level, 0.5, rising)"})
    assert diagnose(model, _Card([_Res("CHK", True)]), cols) == []


def test_a_contradiction_raises_a_blocking_question():
    rise = [0.005 + 0.0014 * i for i in range(100)]
    cols = {"time": list(range(160)), "B5.level": rise + [rise[-1]] * 60}
    model = _model_with({"CHK": "crosses(B5.level, 0.18, rising)"})
    log = AssumptionLog()
    record(model, diagnose(model, _Card([_Res("CHK", False)]), cols), log)

    assert len(log.questions) == 1
    q = log.questions[0]
    assert q.blocking
    assert "setpoint" in q.question and "sizing" in q.question
    assert "left exactly as specified" in (q.interim or "")
