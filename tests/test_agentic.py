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
