"""An independent second opinion on a formalised criterion: the mechanical checks in
`works()` only prove an expression is valid and computable, never that it means the same
thing as the criterion it was translated from. This is the only check on that."""

from __future__ import annotations

from specalive.ir.system import AcceptanceCheck, Scenario, SystemModel
from specalive.verify.criteria import formalise


class _TaskRouter:
    """Routes by task name, like the real Router, so a translate call and a review call
    can be scripted independently of each other."""

    def __init__(self, replies: dict[str, list[dict]]) -> None:
        self.replies = {k: list(v) for k, v in replies.items()}
        self.calls: list[tuple[str, str]] = []

    def run(self, task, prompt, schema=None, validator=None, **kw):
        self.calls.append((task, prompt))
        queue = self.replies.get(task, [])
        data = queue.pop(0) if queue else {}

        class R:
            pass

        r = R()
        r.data = data
        r.tier, r.model = "t_test", "test-model"
        return r


def _model(criterion: str) -> SystemModel:
    chk = AcceptanceCheck(id="AC-01", description=criterion, kind="procedure",
                          criterion=criterion, expression="")
    sc = Scenario(id="SCN-01", name="Run", checks=[chk])
    return SystemModel(name="t", scenarios=[sc])


def _cols():
    return {"time": [0.0, 1.0, 2.0], "B5.level": [0.0, 0.5, 1.0]}


def test_a_confirmed_translation_is_kept_and_notes_the_second_opinion():
    router = _TaskRouter({
        "formalise_criterion": [{"checkable": True, "expression": "final(B5.level) >= 0.9",
                                 "reason": "end-state threshold"}],
        "verify_criterion": [{"agrees": True, "reason": "matches the criterion exactly"}],
    })
    model = _model("B5 level shall reach at least 0.9 by the end of the run.")
    notes = formalise(model, _cols(), router=router)

    chk = model.scenarios[0].checks[0]
    assert chk.expression == "final(B5.level) >= 0.9"
    assert "independently confirmed" in chk.provenance.note
    assert [t for t, _ in router.calls] == ["formalise_criterion", "verify_criterion"]
    assert any("1/1 procedure criteria formalised" in n for n in notes)


def test_a_disagreeing_review_reverts_the_translation_to_not_machine_checkable():
    router = _TaskRouter({
        "formalise_criterion": [{"checkable": True, "expression": "final(B5.level) >= 0.1",
                                 "reason": "a much weaker bound than stated"}],
        "verify_criterion": [{"agrees": False,
                              "reason": "the criterion says 0.9, the expression checks 0.1"}],
    })
    model = _model("B5 level shall reach at least 0.9 by the end of the run.")
    notes = formalise(model, _cols(), router=router)

    chk = model.scenarios[0].checks[0]
    assert chk.expression == "", "a disagreed-upon translation must not be used to score anything"
    assert "not machine-checkable" in chk.provenance.note
    assert "independent review disagreed" in chk.provenance.note
    assert any("0/1 procedure criteria formalised" in n for n in notes)
    assert any("1 rejected on independent review" in n for n in notes)


def test_a_disagreed_translation_is_never_written_to_memory():
    """Memory is replayed by future offline runs with no reviewer available at all -- a
    rejected translation must never reach it, or a bad check would outlive the run that
    produced it and run unreviewed forever after."""
    router = _TaskRouter({
        "formalise_criterion": [{"checkable": True, "expression": "final(B5.level) >= 0.1",
                                 "reason": "weak"}],
        "verify_criterion": [{"agrees": False, "reason": "wrong bound"}],
    })

    class Memory:
        criteria: dict = {}

    model = _model("B5 level shall reach at least 0.9 by the end of the run.")
    formalise(model, _cols(), router=router, memory=Memory())
    assert Memory.criteria == {}


def test_a_review_that_cannot_be_reached_leaves_the_translation_unreviewed_not_rejected():
    """The router has no verify_criterion tier available (NoTierSucceeded, a quota error,
    anything) -- the original, unreviewed translation must stand exactly as it did before
    this feature existed, not be silently dropped because a second call failed."""

    class FlakyRouter(_TaskRouter):
        def run(self, task, prompt, schema=None, validator=None, **kw):
            if task == "verify_criterion":
                raise RuntimeError("no tier available")
            return super().run(task, prompt, schema=schema, validator=validator, **kw)

    router = FlakyRouter({
        "formalise_criterion": [{"checkable": True, "expression": "final(B5.level) >= 0.9",
                                 "reason": "end-state threshold"}],
    })
    model = _model("B5 level shall reach at least 0.9 by the end of the run.")
    notes = formalise(model, _cols(), router=router)

    chk = model.scenarios[0].checks[0]
    assert chk.expression == "final(B5.level) >= 0.9"
    assert "independently confirmed" not in chk.provenance.note
    assert any("1/1 procedure criteria formalised" in n for n in notes)


def test_a_malformed_review_reply_is_treated_the_same_as_unreachable():
    router = _TaskRouter({
        "formalise_criterion": [{"checkable": True, "expression": "final(B5.level) >= 0.9",
                                 "reason": "end-state threshold"}],
        "verify_criterion": [{}],  # no "agrees" key at all
    })
    model = _model("B5 level shall reach at least 0.9 by the end of the run.")
    formalise(model, _cols(), router=router)
    chk = model.scenarios[0].checks[0]
    assert chk.expression == "final(B5.level) >= 0.9"
