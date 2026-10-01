"""Step 2: what a test procedure says the run must be, and checking that it was."""

from __future__ import annotations

import pytest

from specalive.extract.claims import _row_status
from specalive.ingest.base import DocBlock, Document
from specalive.ir.evidence import EvidenceClaim, Locator, Source
from specalive.ir.system import Parameter, Quantity, Signal
from specalive.reconcile import procedure as P
from specalive.reconcile.behaviour import GuardParser, Parsed
from specalive.verify.acceptance import ExpressionError, evaluate
from specalive.verify.criteria import _with_reaction_grace


# --------------------------------------------------------------------- row status

@pytest.mark.parametrize("cells,expected", [
    (["Superseded", "No"], "superseded"),
    (["Approved", "Yes"], "effective"),
    (["Approved", "No"], "superseded"),     # superseded wins: not in force
    (["Current"], "effective"),
    (["", ""], None),
    (["As-built test only"], None),
])
def test_a_row_says_whether_it_is_in_force(cells, expected):
    assert _row_status(cells) == expected


def test_an_effective_row_beats_a_superseded_row_of_the_same_register():
    from specalive.reconcile.builder import resolve_all
    from specalive.reconcile.precedence import PrecedenceEngine

    def claim(i, value, status):
        return EvidenceClaim(id=f"C{i}", source_id="SRC-02", kind="parameter",
                             subject="High level limit", predicate="value", value=value,
                             locator=Locator(sheet="Params", cell=f"C{i}"), row_status=status)

    src = Source(id="SRC-02", filename="register.xlsx", media_type="xlsx")
    winners, decisions = resolve_all(
        [claim(5, 0.78, "superseded"), claim(6, 0.8, "effective")],
        {"SRC-02": src}, PrecedenceEngine("config/precedence.yaml"))
    assert winners[("highlevellimit", "value")].value == 0.8
    assert any(d.rule_id == "P1b-row-status" for d in decisions)


# ------------------------------------------------------------------ the procedure

def _doc(name: str, title: str, tables: list[list[list[str]]], text: str = "") -> Document:
    blocks = [DocBlock(kind="paragraph", text=title, locator=Locator())]
    for rows in tables:
        blocks.append(DocBlock(kind="table", text="\n".join(" | ".join(r) for r in rows),
                               rows=rows, locator=Locator()))
    if text:
        blocks.append(DocBlock(kind="paragraph", text=text, locator=Locator()))
    return Document(source=Source(id="SRC-09", filename=name, media_type="pdf"), blocks=blocks)


TP = _doc(
    "09_test_procedure_TP17.pdf", "Test Procedure TP-17 - Controller Demonstration",
    [[["Item", "Value"], ["Simulation duration", "900 s"], ["Logging interval", "1 s"]],
     [["Time (s)", "Command", "Expected immediate controller response"],
      ["20", "START", "Begin fill."], ["220", "STOP", "Close all valves."]]],
    "4. Acceptance Criteria AC-01 - T1 shall reach 0.80 m before the first transfer begins. "
    "AC-02 - All valves shall be closed throughout the STOP interval.",
)


def test_the_procedure_sets_duration_interval_and_commands():
    rs = P.run_settings([TP])
    assert (rs.stop_time, rs.interval) == (900.0, 1.0)
    assert [(c.time, c.command) for c in P.command_schedule([TP])] == [(20.0, "START"), (220.0, "STOP")]


def test_criteria_come_from_the_procedure_and_the_command_table_is_not_one():
    ids = [c.id for c in P.acceptance_criteria([TP])]
    assert ids == ["AC-01", "AC-02"]


def test_a_design_note_that_mentions_a_procedure_is_not_one():
    note = _doc("06_design_review_minutes.md", "Design review minutes",
                [[["Item", "Value"], ["Simulation duration", "15 s"]]],
                "Agreed to rerun CP-23 next week.")
    assert P.procedure_docs([note]) == []
    assert P.run_settings([note]).stop_time is None


def test_a_ramp_profile_is_read_as_amplitude_start_and_duration():
    av = _doc("09_analytic_verification_procedure.pdf", "Analytic Verification AV-11",
              [[["Parameter", "Value"],
                ["Current ramp", "0 A before 0.10 s; linear to 2.0 A RMS at 0.50 s; hold through 1.0 s"]]])
    (p,) = P.profiles([av])[:1]
    assert (p.unit, p.amplitude, p.start, p.end, p.hold) == ("A", 2.0, 0.1, 0.5, 1.0)


def test_a_day_long_commissioning_run_is_24_hours():
    cp = _doc("09_commissioning_test_procedure_CP23.pdf", "Commissioning Procedure CP-23", [],
              "Start at 00:00 with zero occupants. Execute the schedule through 24:00. Log at 60 s intervals.")
    rs = P.run_settings([cp])
    assert (rs.stop_time, rs.interval) == (86400.0, 60.0)


# ----------------------------------------------------------------------- guards

def _parser() -> GuardParser:
    sigs = [Signal(id="LT_101", name="LT_101", role="sensor", binding="TK_101.level"),
            Signal(id="PB_START", name="PB_START", role="sensor", datatype="boolean", owner="manual")]
    params = [
        Parameter(id="High level limit", name="High_level_limit", quantity=Quantity(value=0.8, unit="m"),
                  description="applies to TK-101"),
        Parameter(id="T1_high", name="T1_high", quantity=Quantity(value=0.78, unit="m"), evidence="model"),
    ]
    return GuardParser(sigs, params, param_scope={}, signal_block={"LT_101": "TK_101"})


def test_a_named_setpoint_resolves_to_the_register_not_to_a_model_read_spelling():
    out = Parsed(expr="")
    expr = _parser()._clause("LT-101 >= T1_High", out, prose=False, join_regions=False)
    assert expr == "LT_101 >= High_level_limit"
    assert any("register states" in n for n in out.notes)


def test_an_operator_command_reads_its_push_button():
    out = Parsed(expr="")
    assert _parser()._clause("START edge", out, prose=False, join_regions=False) == "PB_START"


# ------------------------------------------------------------------- evaluator

COLS = {"time": [0, 1, 2, 3, 4], "a": [0, 0, 1, 1, 0], "b": [0, 1, 0, 0, 0], "s": [0, 1, 1, 3, 3]}


def test_every_conjunct_must_hold():
    ok, detail, _ = evaluate("during(a <= 0.5, 0, 1) && during(b <= 0.5, 0, 1)", COLS)
    assert not ok and "one of 2" in detail


def test_trailing_text_is_an_error_not_a_pass():
    with pytest.raises(ExpressionError):
        evaluate("during(a <= 0.5, 0, 1) garbage", COLS)


def test_state_is_held_not_interpolated_and_entries_are_counted():
    assert evaluate("state(s, 2.5) == 1", COLS)[0]
    assert evaluate("elapsed(enters(s, 1), enters(s, 3)) == 2", COLS)[0]
    assert not evaluate("exclusive(a, b) && state(s, 4) == 1", COLS)[0]


def test_equality_is_to_six_significant_figures():
    assert evaluate("final(x) == 1909859", {"time": [0, 1], "x": [0, 1.9098592e6]})[0]


def test_magnitude_agreement_ignores_sign():
    assert evaluate("approx(abs(final(x)), 4.83e-4, 0.03)", {"time": [0, 1], "x": [0, -4.92e-4]})[0]


def test_a_check_at_a_commanded_instant_waits_for_the_controller():
    out = _with_reaction_grace("during(a <= 0.5, 220, 280) && state(b, 300) == 1", [220.0], 0.3)
    assert out == "during(a <= 0.5, 220.3, 280) && state(b, 300) == 1"
