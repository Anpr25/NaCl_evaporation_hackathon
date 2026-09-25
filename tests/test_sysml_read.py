"""C-08: the Modelica is derived from the SysML, and the derivation is measured.

Own file rather than appended to test_specalive.py: four people are editing that module and
every append has produced a merge conflict so far.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from specalive.emit.modelica import ModelicaEmitter
from specalive.emit.sysml import SysMLEmitter
from specalive.emit.sysml_read import (
    SimulationProfile,
    _modelica_literal,
    read_sysml,
    to_system_model,
    unsanitise_connector,
)
from specalive.ir.system import SystemModel

ROOT = Path(__file__).resolve().parents[1]
REF_IR = ROOT / "benchmarks" / "nacl_evaporation" / "reference_ir.json"


def _reference() -> SystemModel:
    return SystemModel.model_validate(json.loads(REF_IR.read_text(encoding="utf-8")))


def _structure(modelica: str) -> list[str]:
    """Modelica with every string literal blanked: structure, not prose.

    Docstrings legitimately differ -- SysML shares one `doc` per part def, so B4 inherits
    B1's "Charging tank" -- and none of it reaches the compiler.
    """
    return [re.sub(r'"[^"]*"', '""', ln).strip() for ln in modelica.splitlines() if ln.strip()]


def test_sysml_is_a_lossless_carrier_for_the_modelica():
    """The headline C-08 claim, as a measurement rather than an assertion.

    Emit SysML from the IR, read it back with no access to the IR, emit Modelica from what
    came back, and compare against the Modelica the IR produces directly. Both go through
    the SAME emitter on purpose: any difference can then only be something the reader failed
    to recover from the text.
    """
    ir = _reference()
    sysml_text = SysMLEmitter(ir).emit()

    parsed = read_sysml(sysml_text)
    assert parsed.unparsed == [], f"reader does not understand: {parsed.unparsed[:3]}"

    rebuilt = to_system_model(parsed, SimulationProfile.from_ir(ir), name=ir.name)

    from_ir = _structure(ModelicaEmitter(ir).emit())
    from_sysml = _structure(ModelicaEmitter(rebuilt).emit())
    assert from_sysml == from_ir, "\n".join(
        f"{a!r} != {b!r}" for a, b in zip(from_ir, from_sysml) if a != b
    )[:2000]


def test_parallel_fork_survives_the_round_trip():
    """The fork rides in a trailing comment (`// fork -> Step12, Step7`), and `_code()` in
    the emitter's own parser discards trailing comments. Dropping it costs nothing at compile
    time and everything at run time: the split never fires and the batch deadlocks after
    evaporation, which is the one behaviour L4 exists to test."""
    ir = _reference()
    parsed = read_sysml(SysMLEmitter(ir).emit())

    forking = [t for t in parsed.transitions if t.forks]
    assert forking, "no transition carried a fork out of the SysML"

    rebuilt = to_system_model(parsed, SimulationProfile.from_ir(ir))
    emitted = ModelicaEmitter(rebuilt).emit()
    for t in forking:
        for target in t.forks:
            assert target in {s.id for s in parsed.states}, f"fork to unknown state {target}"
    # The lowered FSM must actually assign the forked regions inside the scan.
    assert emitted.count("s_A :=") >= 2 and emitted.count("s_B :=") >= 2


def test_connector_subscripts_are_recovered_only_when_the_catalog_agrees():
    """`_ident("inlet[1]")` -> `inlet_1_`, which is not reversible on its own: a class could
    legitimately own a connector called `inlet_1_`. So we propose the un-sanitised form and
    accept it only against the harvested port list -- the same replace-a-guess-with-a-lookup
    move as C-07."""
    assert unsanitise_connector("inlet_1_", {"inlet", "outlet"}) == "inlet[1]"
    assert unsanitise_connector("outlet_2_", {"inlet", "outlet"}) == "outlet[2]"
    # The catalog says there is no `inlet`, so leave the name alone rather than invent one.
    assert unsanitise_connector("inlet_1_", {"port_a", "port_b"}) == "inlet_1_"
    # Nothing to un-sanitise.
    assert unsanitise_connector("port_a", {"port_a"}) == "port_a"
    # No catalog: fall back to the structural guess rather than refuse to read.
    assert unsanitise_connector("inlet_1_", None) == "inlet[1]"


def test_python_bool_repr_in_the_sysml_is_normalised():
    """D-3. The SysML emitter interpolates the IR value into an f-string, so a Python bool
    lands as `False` -- valid in neither SysML v2 nor Modelica. It is why the drivetrain
    failed to compile on the SysML path (`useSupport = False`) while the IR path was fine.
    Normalising here keeps the reader robust; the real fix belongs in the emitter."""
    assert _modelica_literal("False") == "false"
    assert _modelica_literal("True") == "true"
    assert _modelica_literal("false") == "false"
    assert _modelica_literal("0.07") == "0.07"


def test_an_unknown_construct_refuses_rather_than_dropping_it():
    """Silence is the dangerous failure here. If the emitter grows a construct the reader
    does not know, the element would vanish from the Modelica and the model would still
    compile -- quietly missing a component. Refuse instead, and let the pipeline fall back."""
    ir = _reference()
    text = SysMLEmitter(ir).emit() + "\n    flow def MysteryConstruct {\n    }\n"
    parsed = read_sysml(text)
    assert parsed.unparsed, "a construct the reader cannot read must be reported"
    with pytest.raises(ValueError, match="not understood"):
        to_system_model(parsed, SimulationProfile.from_ir(ir))
