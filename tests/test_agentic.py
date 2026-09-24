"""C-AI-1 .. C-AI-5: the agentic repair path, tested without a network.

Own file: four people edit test_specalive.py and every append has cost a merge conflict.

Everything here runs offline with a fake router. The point is not to test the model -- it is
to test the machinery around it, which is what actually decides whether a free model is
sufficient: the gate, the memory, the tool answer and the keep-best invariant.
"""

from __future__ import annotations

import re
from pathlib import Path

from specalive.emit.modelica import _render_l2_body
from specalive.repair.faults import FAULTS, inject
from specalive.repair.loop import (
    HISTORY_BLOCK,
    REPAIR_PROMPT,
    REPAIR_SCHEMA,
    RepairLoop,
    fix_missing_initial_condition,
    fix_partial_type_binding,
)
from specalive.verify.omc import Diagnostic

ROOT = Path(__file__).resolve().parents[1]


class FakeRouter:
    """Records what it was asked and replies from a script. No network, no model."""

    def __init__(self, replies: list[dict]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def run(self, task, prompt, schema=None, validator=None, **kw):  # noqa: ANN001
        self.prompts.append(prompt)
        data = self.replies.pop(0) if self.replies else {"replacements": [], "explanation": "done"}

        class R:
            pass

        r = R()
        r.data = data
        return r


class FakeEntry:
    def __init__(self):
        self.params = [type("P", (), {"name": "area", "type": "Real"})()]
        self.ports = [type("Q", (), {"name": "inlet", "type": "SpecAlive.Interfaces.Inlet"})()]


class FakeIndex:
    def __init__(self, known=("SpecAlive.Vessels.Reservoir",)):
        self.known = set(known)

    def get(self, key):
        return FakeEntry() if key in self.known else None


# ------------------------------------------------------------------ C-AI-1: the simulate gate


def test_partial_type_binding_has_a_deterministic_fix():
    """C-07 proved this passes `checkModel` and dies at build. There is no local edit that
    makes a partial class instantiable, so the honest repair removes the component and
    declares a gap rather than substituting a class the evidence never named."""
    src = '  model P\n    Modelica.Thermal.HeatTransfer.Interfaces.Element1D wall "x";\n  end P;\n'
    diag = Diagnostic(kind="build", message="Component 'wall' has partial type 'Element1D'", raw="")
    out = fix_partial_type_binding(src, diag)
    assert out is not None
    patched, why = out
    assert "// GAP:" in patched
    assert "declared as a gap" in why
    # The original line is commented, not deleted: a reviewer must still see what was dropped.
    assert "// " in patched and "Element1D wall" in patched


def test_initialisation_fix_pins_a_start_value():
    src = "  Real x(start = 1) \"level\";\n"
    diag = Diagnostic(kind="initialization", message="x is not fixed; underdetermined", raw="")
    out = fix_missing_initial_condition(src, diag)
    assert out is not None and "fixed = true" in out[0]


# ------------------------------------------------------------- C-AI-2: memory and tool use


def test_the_agent_can_ask_the_catalog_instead_of_guessing():
    """Tool use. The first reply asks for a signature and offers no edit; the loop answers
    from the catalog and asks again. What matters is that the *answer* reaches the second
    prompt -- otherwise the model is still recalling an API rather than reading one."""
    router = FakeRouter([
        {"diagnosis": "unsure of the parameter name", "strategy": "look it up",
         "lookup": ["SpecAlive.Vessels.Reservoir"], "replacements": [], "explanation": ""},
        {"diagnosis": "wrong parameter", "strategy": "use `area`",
         "replacements": [{"find": "surfaceArea", "replace": "area"}], "explanation": "fixed"},
    ])
    loop = RepairLoop(runner=None, router=router, index=FakeIndex())
    src = "model P\n  R b1(surfaceArea = 1);\nend P;\n"
    diag = Diagnostic(kind="undeclared", message="surfaceArea not found", line=2, raw="")
    patched, method, _ = loop._attempt(src, diag, Path("P.mo"), "", None)

    assert method == "model" and patched is not None and "area = 1" in patched
    assert len(router.prompts) == 2, "the loop must ask again after answering the lookup"
    assert "VERIFIED SIGNATURES" in router.prompts[1]
    assert "inlet" in router.prompts[1], "the real connector list must reach the second prompt"


def test_a_lookup_for_a_class_that_does_not_exist_says_so():
    """The catalog answering 'NOT IN CATALOG' is the whole value of grounding: it is the one
    reply that stops a fabricated class from being tried."""
    loop = RepairLoop(runner=None, router=FakeRouter([]), index=FakeIndex())
    assert "NOT IN CATALOG" in loop._signature(["SpecAlive.Vessels.Resevoir"])
    assert "area" in loop._signature(["SpecAlive.Vessels.Reservoir"])


def test_rejected_attempts_are_fed_back_so_the_next_pass_is_a_refinement():
    """Multi-pass refinement is only refinement if the next pass can see the last one. Without
    this the agent re-proposes the patch the compiler already rejected and burns the budget."""
    router = FakeRouter([{"diagnosis": "d", "strategy": "s", "replacements": [], "explanation": ""}])
    loop = RepairLoop(runner=None, router=router, index=None)
    diag = Diagnostic(kind="syntax", message="boom", line=1, raw="")
    loop._attempt("model P\nend P;\n", diag, Path("P.mo"), "",
                  ["[rejected] renamed the port: errors 1 -> 3, discarded"])
    assert "PREVIOUS ATTEMPTS" in router.prompts[0]
    assert "errors 1 -> 3" in router.prompts[0]


def test_the_agent_must_diagnose_before_it_edits():
    """`diagnosis` and `strategy` are required fields, deliberately. The compiler points at
    the symptom; naming the cause first is what stops the model patching the line it was
    shown when the fault is three lines above."""
    assert "diagnosis" in REPAIR_SCHEMA["required"]
    assert "strategy" in REPAIR_SCHEMA["required"]
    assert REPAIR_SCHEMA["required"].index("diagnosis") < REPAIR_SCHEMA["required"].index("replacements")
    assert "{history}" in REPAIR_PROMPT and "{catalog_note}" in REPAIR_PROMPT
    assert "PREVIOUS ATTEMPTS" in HISTORY_BLOCK


# ------------------------------------------------------------------- C-AI-3: self-critique


def test_l2_body_renders_variables_and_equations_for_the_critic():
    body = _render_l2_body({
        "variables": [{"name": "m", "start": 0.1, "description": "mass"}],
        "equations": ["der(m) = inlet.m_flow", "outlet.m_flow = -inlet.m_flow"],
    })
    assert 'Real m(start = 0.1) "mass";' in body
    assert body.count("equation") == 1
    assert "der(m) = inlet.m_flow;" in body


# -------------------------------------------------------------- C-AI-5: fault injection


def test_every_fault_applies_to_the_reference_model_or_says_it_cannot():
    """A mutator that silently matches nothing scores as a free pass and inflates the number.
    Each one must either change the source or return None."""
    ref = (ROOT / "benchmarks" / "nacl_evaporation" / "reference" / "GeneratedPlant.mo").read_text(
        encoding="utf-8"
    )
    applied = 0
    for f in FAULTS:
        out = inject(ref, f)
        if out is not None:
            assert out != ref, f"{f.id} claimed to apply but changed nothing"
            applied += 1
    assert applied >= 5, f"only {applied} of {len(FAULTS)} faults apply to the reference model"


def test_faults_declare_where_they_surface():
    """The `build` ones are the point of C-AI-1: invisible to a loop gated on checkModel."""
    assert {f.surfaces_at for f in FAULTS} <= {"check", "build"}
    assert any(f.surfaces_at == "build" for f in FAULTS)


# ------------------------------------------------------------------ diagram annotations


def test_generated_plant_carries_a_diagram_layout():
    """Without Placement annotations OMEdit renders an empty canvas and an engineer has to
    read Modelica to see the topology -- which defeats handing them a model to review."""
    mo = (ROOT / "benchmarks" / "nacl_evaporation" / "reference" / "GeneratedPlant.mo")
    from specalive.emit.modelica import ModelicaEmitter
    from specalive.ir.system import SystemModel
    import json

    ir = SystemModel.model_validate(
        json.loads((ROOT / "benchmarks" / "nacl_evaporation" / "reference_ir.json").read_text(encoding="utf-8"))
    )
    text = ModelicaEmitter(ir).emit()
    xs = [int(m) for m in re.findall(r"Placement\(transformation\(extent=\{\{(-?\d+),", text)]
    assert len(xs) >= 10, "components are not being placed"
    assert len(set(xs)) >= 5, f"layout collapsed into {len(set(xs))} column(s): cycles not broken"
    assert "Line(points=" in text, "connections carry no route, so OMEdit draws no edges"


# ------------------------------------------------------------------ C10: gate honesty


def _csv(tmp_path, name, header, rows):
    import csv as _csv
    p = tmp_path / name
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = _csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    return p


class _Region:
    def __init__(self, region, n):
        self.region, self.n = region, n


class _SM:
    def __init__(self, spec):
        self.regions = list(spec)
        self._spec = spec

    def states_in(self, region):
        return [object()] * self._spec[region]


class _Model:
    def __init__(self, spec):
        self.state_machines = [_SM(spec)] if spec else []


def test_a_simulation_where_nothing_moves_is_not_a_pass(tmp_path):
    """The literal vacuous case: it integrated, and every variable is where it started."""
    from specalive.verify.omc import liveness

    rows = [[t, 1.0, 2.0] for t in range(10)]
    live = liveness(_csv(tmp_path, "flat.csv", ["time", "a", "b"], rows))
    assert not live.ok
    assert "nothing changed" in live.reason


def test_a_controller_that_stalls_mid_sequence_is_not_a_pass(tmp_path):
    """The case that actually bit us, and the reason a did-anything check is too weak.

    Without a reference IR the NaCl model compiled, simulated, moved 7% of its variables and
    scored 0/10 -- because the main region reached Step1 of 8 and stopped. Extraction had
    missed cmd_heater, so nothing ever evaporated. Any "did the controller move" test passes
    this; only comparing against the state count catches it.
    """
    from specalive.verify.omc import liveness

    rows = [[t, 1.0 + t * 1e-3, 1, 3, 5] for t in range(10)]
    live = liveness(
        _csv(tmp_path, "stalled.csv", ["time", "x", "ctrl.s_main", "ctrl.s_A", "ctrl.s_B"], rows),
        _Model({"main": 9, "A": 4, "B": 6}),
    )
    assert live.regions["main"] == 1 and live.expected["main"] == 8
    assert live.stalled == ["main"]
    assert not live.ok
    assert "main stopped at 1 of 8" in live.reason


def test_a_completed_sequence_passes(tmp_path):
    from specalive.verify.omc import liveness

    rows = [[t, float(t), min(t, 8), min(t, 3), min(t, 5)] for t in range(10)]
    live = liveness(
        _csv(tmp_path, "done.csv", ["time", "x", "ctrl.s_main", "ctrl.s_A", "ctrl.s_B"], rows),
        _Model({"main": 9, "A": 4, "B": 6}),
    )
    assert live.stalled == [] and live.ok


def test_a_continuous_model_with_no_controller_is_judged_on_movement_alone(tmp_path):
    """The drivetrain has no state machine. Requiring a finished sequence there would fail a
    model that is working perfectly, so the sequence test only applies when there is one."""
    from specalive.verify.omc import liveness

    rows = [[t, float(t), 2.0 * t] for t in range(10)]
    live = liveness(_csv(tmp_path, "cont.csv", ["time", "w", "tau"], rows), _Model({}))
    assert live.ok and not live.expected


def test_liveness_survives_a_result_file_it_cannot_read(tmp_path):
    """Never let a screen crash the run it is screening."""
    from specalive.verify.omc import liveness

    assert not liveness(tmp_path / "missing.csv").ok
    assert not liveness(_csv(tmp_path, "head.csv", ["time", "a"], [])).ok


# ------------------------------------------------- C5: fixes that used to cost a model call


class _Port:
    def __init__(self, name, type_):
        self.name, self.type = name, type_


class _Param:
    def __init__(self, name):
        self.name, self.type = name, "Real"


class _Cat:
    """A two-class catalog: a vessel with directional ports and the path that mates with it."""

    def __init__(self):
        self._e = {
            "SpecAlive.Vessels.Reservoir": type("E", (), {
                "key": "SpecAlive.Vessels.Reservoir",
                "params": [_Param(n) for n in ("area", "levelMax", "level_start")],
                "ports": [_Port("inlet", "SpecAlive.Interfaces.Inlet"),
                          _Port("outlet", "SpecAlive.Interfaces.Outlet")],
            })(),
            "SpecAlive.Transport.Path": type("E", (), {
                "key": "SpecAlive.Transport.Path",
                "params": [_Param("m_flow_nominal")],
                "ports": [_Port("port_a", "SpecAlive.Interfaces.Suction"),
                          _Port("port_b", "SpecAlive.Interfaces.Discharge")],
            })(),
        }
        self.entries = list(self._e.values())

    def get(self, key):
        return self._e.get(key)


# Two transfer legs, not one. The type-compatibility fixer learns which connectors mate from
# the model's own working connects, so it needs at least one intact example of the pair it is
# trying to resolve -- a real limitation, and the reason this fixture is not smaller.
_PLANT = """model Plant
  SpecAlive.Vessels.Reservoir B1(area = 0.07);
  SpecAlive.Vessels.Reservoir B3(area = 0.05);
  SpecAlive.Vessels.Reservoir B4(area = 0.055);
  SpecAlive.Transport.Path L_V8(m_flow_nominal = 0.02);
  SpecAlive.Transport.Path L_V11(m_flow_nominal = 0.06);
equation
  connect(B1.outlet[1], L_V8.port_a);
  connect(L_V8.port_b, B3.inlet[1]);
  connect(B3.outlet[1], L_V11.port_a);
  connect(L_V11.port_b, B4.inlet[1]);
end Plant;
"""


def test_a_misspelled_class_is_corrected_against_the_catalog():
    """Used to cost a model round trip. The catalog holds every class that exists, so the
    correction is a lookup and cannot invent a class we did not harvest."""
    from specalive.repair.loop import fix_unknown_class

    src = _PLANT.replace("Vessels.Reservoir B1", "Vessels.Resevoir B1")
    diag = Diagnostic(kind="undeclared",
                      message="Error: Class SpecAlive.Vessels.Resevoir not found in scope Plant.",
                      line=2, raw="")
    out = fix_unknown_class(src, diag, _Cat())
    assert out is not None
    assert "SpecAlive.Vessels.Reservoir B1" in out[0]
    assert "Resevoir" not in out[0]


def test_a_renamed_modifier_is_corrected_by_containment_not_edit_distance():
    """`surfaceArea` and `area` score 0.53 on difflib -- below any cutoff worth trusting --
    yet one name contains the other and the intent is unmistakable. Checking containment
    before the ratio is what lets the ratio cutoff stay strict."""
    from specalive.repair.loop import _closest, fix_wrong_modifier

    import difflib
    assert difflib.SequenceMatcher(None, "surfaceArea", "area").ratio() < 0.8
    assert _closest("surfaceArea", ["area", "levelMax"]) == "area"

    src = _PLANT.replace("B1(area", "B1(surfaceArea")
    diag = Diagnostic(kind="other",
                      message="Error: Modified element surfaceArea not found in class Reservoir.",
                      line=2, raw="")
    out = fix_wrong_modifier(src, diag, _Cat())
    assert out is not None and "B1(area = 0.07)" in out[0]


def test_an_unknown_connector_is_resolved_by_type_compatibility():
    """The interesting one. `nonexistent_port` resembles neither `inlet` nor `outlet`, so a
    fuzzy match would guess or give up. But the peer on the other end has a type, and the
    file's own working connects say which types mate -- leaving exactly one candidate.
    Nothing here knows what a fluid is: the compatibility relation is read off the model."""
    from specalive.repair.loop import _observed_pairs, fix_unknown_connector

    pairs = _observed_pairs(_PLANT, _Cat())
    assert "SpecAlive.Interfaces.Outlet" in pairs["SpecAlive.Interfaces.Suction"]

    src = _PLANT.replace("B1.outlet[1]", "B1.nonexistent_port[1]")
    diag = Diagnostic(kind="undeclared",
                      message="Error: Variable B1.nonexistent_port[1] not found in scope Plant.",
                      line=6, raw="")
    out = fix_unknown_connector(src, diag, _Cat())
    assert out is not None
    assert "connect(B1.outlet[1], L_V8.port_a)" in out[0], out[0]
    assert "declared by SpecAlive.Vessels.Reservoir" in out[1]


def test_a_dropped_semicolon_is_added_to_the_line_before_the_reported_token():
    """omc reports the position of the token it DID find, which starts the next statement, so
    the terminator belongs on the previous line. Getting that offset wrong is why this looked
    semantic and was going to a model."""
    from specalive.repair.loop import fix_missing_semicolon

    src = "model P\n  parameter Real a = 1 \"m\"\n  parameter Real b = 2;\nend P;\n"
    diag = Diagnostic(kind="syntax", message="Error: Missing token: SEMICOLON", line=3, raw="")
    out = fix_missing_semicolon(src, diag)
    assert out is not None
    assert 'parameter Real a = 1 "m";' in out[0]


def test_a_dropped_semicolon_is_classified_as_syntax_so_it_outranks_its_cascade():
    """It was classified `other`, which sorts LAST in the repair priority, so the loop chased
    an `undeclared` error that the missing semicolon had caused. A syntax error is always the
    root: everything after an unparseable line is a symptom."""
    from specalive.verify.omc import parse_diagnostics

    d = parse_diagnostics("[f.mo:8:5-8:5:writable] Error: Missing token: SEMICOLON")
    assert d and d[0].kind == "syntax"


def test_closest_refuses_when_nothing_is_close():
    """A fixer that always answers is worse than one that declines: a wrong rename compiles."""
    from specalive.repair.loop import _closest

    assert _closest("completelyUnrelated", ["area", "levelMax"]) is None
