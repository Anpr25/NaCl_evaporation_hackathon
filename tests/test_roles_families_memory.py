"""Part roles, connector families and the binding memory -- the three things that decide
what a part IS and what it binds to before any Modelica is written."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from specalive.catalog.memory import BindingMemory, signature
from specalive.emit.families import plan_families
from specalive.ir.evidence import EvidenceClaim
from specalive.ir.system import Block, SystemModel
from specalive.reconcile.entities import Entity, norm
from specalive.reconcile.roles import classify_roles


# --------------------------------------------------------------------------- helpers

def _entity(subject: str, **facts: str) -> Entity:
    e = Entity(key=norm(subject), subject=subject)
    for i, (pred, value) in enumerate(facts.items()):
        e.facts[norm(pred)] = EvidenceClaim(
            id=f"C-{subject}-{i}", source_id="SRC-01", kind="note",
            subject=subject, predicate=pred, value=value,
        )
    return e


def _roles(ents: list[Entity], edges: list[tuple[str, str]] = ()):
    entities = {e.key: e for e in ents}
    neighbours: dict[str, set[str]] = {}
    for a, z in edges:
        neighbours.setdefault(norm(a), set()).add(norm(z))
        neighbours.setdefault(norm(z), set()).add(norm(a))
    known = {e.key: e.subject for e in ents}
    return classify_roles(entities, [e.key for e in ents], neighbours, known)


# ----------------------------------------------------------------------------- roles

def test_a_transmitter_is_a_reading_of_the_part_whose_row_names_it():
    tank = _entity("TK-101", type="Tank", signal_sensor="LT-101")
    lt = _entity("LT-101", type="Level transmitter")
    plc = _entity("PLC-101", type="Controller")
    d = _roles([tank, lt, plc], edges=[("LT-101", "PLC-101")])
    assert d[lt.key].role == "instrument"
    assert d[lt.key].host == "TK-101"
    assert d[lt.key].variable == "level"
    assert d[plc.key].role == "controller"
    assert d[tank.key].role == "component"


def test_a_sensor_feeding_a_block_is_a_component_not_an_instrument():
    """What decides it is what the part is used as: a CO2 sensor feeding a gain in a block
    diagram is a component with an output, not a value the controller reads."""
    sen = _entity("SEN-CO2-201", type="CO2 trace sensor")
    gain = _entity("GAIN-NORM-201", type="Gain")
    d = _roles([sen, gain], edges=[("SEN-CO2-201", "GAIN-NORM-201")])
    assert d[sen.key].role == "component"


def test_a_pushbutton_is_an_operator_input():
    pb = _entity("PB-START", type="Momentary pushbutton")
    assert _roles([pb])[pb.key].role == "operator"


def test_a_pid_block_is_a_component_even_though_it_is_called_a_controller():
    ctl = _entity("CTL-CO2-201", type="PID/P controller")
    gain = _entity("GAIN-AIR-201", type="Gain")
    d = _roles([ctl, gain], edges=[("CTL-CO2-201", "GAIN-AIR-201")])
    assert d[ctl.key].role == "component"


def test_a_valve_serving_a_drain_is_not_a_boundary():
    """Boundary is decided by what the part IS, never by what it serves."""
    xv = _entity("XV-103", type="On-off valve", service="TK-102 to drain")
    assert _roles([xv])[xv.key].role == "component"


def test_isa_loop_numbering_is_the_last_resort_for_a_host():
    tank = _entity("TK-201", type="Tank")
    tt = _entity("TT-201", type="Temperature transmitter")
    d = _roles([tank, tt])
    assert d[tt.key].host == "TK-201"
    assert "ISA loop numbering" in d[tt.key].basis
    assert d[tt.key].variable == "T"


# ----------------------------------------------------------------------------- families

@dataclass
class _Port:
    name: str
    type: str


@dataclass
class _Entry:
    key: str
    ports: list[_Port] = field(default_factory=list)
    params: list = field(default_factory=list)


class _Index:
    def __init__(self, entries: list[_Entry]) -> None:
        self.entries = entries
        self._by = {e.key: e for e in entries}

    def get(self, key):
        return self._by.get(key)


class _Binder:
    """Stands in for the real one: fixed candidate lists per block."""

    def __init__(self, cands: dict[str, list[tuple[str, float, str]]]) -> None:
        self.cands = cands
        self._require: set[str] = set()

    def candidates(self, block):
        return self.cands.get(block.id, [])

    def _try_declared(self, block):
        """A declaration resolves when the stub index would verify it."""
        return block.declared_class or None


def test_a_declaration_that_does_not_resolve_does_not_exempt_its_part():
    """A declared class the binder rejects decides nothing, so its part must still be held
    to the plant's family -- otherwise it binds to whatever retrieval likes best."""
    idx = _Index([_mag("Lib.Mag.Tube"), _mag("Lib.Mag.Ground"), _qs("Lib.QS.Ground")])
    m = SystemModel(name="M", blocks=[
        Block(id="C1", name="c", kind="t", declared_class="Lib.Mag.Tube"),
        Block(id="C2", name="c", kind="t", declared_class="Lib.Mag.Tube"),
        Block(id="G", name="ground", kind="ground", declared_class="Lib.Fluid.Nowhere"),
    ])

    class Rejecting(_Binder):
        def _try_declared(self, block):
            return None if block.declared_class == "Lib.Fluid.Nowhere" else block.declared_class

    binder = Rejecting({
        "C1": [("Lib.Mag.Tube", 6.0, "declared")],
        "C2": [("Lib.Mag.Tube", 6.0, "declared")],
        "G": [("Lib.QS.Ground", 3.0, "retrieval"), ("Lib.Mag.Ground", 2.9, "retrieval")],
    })
    required, _ = plan_families(m, idx, binder)
    assert required["G"] == {"Lib.Mag.Interfaces"}


def _mag(key: str) -> _Entry:
    return _Entry(key, [_Port("port_p", "Lib.Mag.Interfaces.PositivePort"),
                        _Port("port_n", "Lib.Mag.Interfaces.NegativePort")])


def _qs(key: str) -> _Entry:
    return _Entry(key, [_Port("port_p", "Lib.QS.Interfaces.PositivePort"),
                        _Port("port_n", "Lib.QS.Interfaces.NegativePort")])


def test_the_plant_is_pulled_into_the_library_its_declared_parts_use():
    """Three flux tubes are declared in the transient library; a ground whose best retrieval
    hit is the quasi-static variant must still be required into the transient one."""
    idx = _Index([_mag("Lib.Mag.Tube"), _mag("Lib.Mag.Ground"), _qs("Lib.QS.Ground")])
    m = SystemModel(name="M", blocks=[
        Block(id="C1", name="c", kind="t", declared_class="Lib.Mag.Tube"),
        Block(id="C2", name="c", kind="t", declared_class="Lib.Mag.Tube"),
        Block(id="C3", name="c", kind="t", declared_class="Lib.Mag.Tube"),
        Block(id="G", name="ground", kind="ground"),
    ])
    binder = _Binder({
        "C1": [("Lib.Mag.Tube", 6.0, "declared")],
        "C2": [("Lib.Mag.Tube", 6.0, "declared")],
        "C3": [("Lib.Mag.Tube", 6.0, "declared")],
        "G": [("Lib.QS.Ground", 3.0, "retrieval"), ("Lib.Mag.Ground", 2.8, "retrieval")],
    })
    required, notes = plan_families(m, idx, binder)
    assert required["G"] == {"Lib.Mag.Interfaces"}
    # Declared parts are never constrained -- the packet has already decided.
    assert "C1" not in required
    assert notes and "Lib.Mag" in notes[0]


def test_a_weak_candidate_does_not_let_a_family_claim_a_part():
    """A family covers a part only through one of the part's GOOD candidates."""
    elec = _Entry("Lib.El.Ground", [_Port("p", "Lib.El.Interfaces.PositivePin")])
    idx = _Index([_mag("Lib.Mag.Tube"), _mag("Lib.Mag.Ground"), elec])
    m = SystemModel(name="M", blocks=[
        Block(id="C1", name="c", kind="t", declared_class="Lib.Mag.Tube"),
        Block(id="C2", name="c", kind="t", declared_class="Lib.Mag.Tube"),
        Block(id="EG", name="electric ground", kind="ground"),
    ])
    binder = _Binder({
        "C1": [("Lib.Mag.Tube", 6.0, "declared")],
        "C2": [("Lib.Mag.Tube", 6.0, "declared")],
        "EG": [("Lib.El.Ground", 3.0, "retrieval"), ("Lib.Mag.Ground", 1.0, "retrieval")],
    })
    required, _ = plan_families(m, idx, binder)
    assert required["EG"] == {"Lib.El.Interfaces"}


# ----------------------------------------------------------------------------- memory

def test_signature_ignores_tags_word_order_and_role():
    a = signature("component", ["fluid"], "On-off valve", "XV-101")
    b = signature("boundary", ["fluid"], "valve on-off", "V-7")
    assert a == b == "fluid|off valve"


def test_memory_needs_success_to_outweigh_failure_twice(tmp_path: Path):
    mem = BindingMemory.load(tmp_path / "m.json")
    sig = "electrical|coil exciting"
    mem.record_success(sig, "Lib.Converter", "p1")
    assert mem.suggest(sig)[0] == "Lib.Converter"
    mem.record_failure(sig, "Lib.Converter", "p2")
    assert mem.suggest(sig) is None, "1 ok against 1 bad is not yet trustworthy"
    for _ in range(3):
        mem.record_success(sig, "Lib.Converter", "p3")
    assert mem.suggest(sig)[0] == "Lib.Converter"


def test_a_class_that_only_ever_failed_is_kept_out(tmp_path: Path):
    mem = BindingMemory.load(tmp_path / "m.json")
    mem.record_failure("fluid|tank", "Lib.Wrong", "p")
    mem.record_failure("fluid|tank", "Lib.Wrong", "p")
    assert mem.discredited("fluid|tank") == {"Lib.Wrong"}


def test_memory_survives_a_round_trip_and_a_corrupt_file(tmp_path: Path):
    path = tmp_path / "m.json"
    mem = BindingMemory.load(path)
    mem.record_success("fluid|tank", "Lib.Tank", "p")
    mem.record_family("fluid", "Lib.Interfaces", ok=True)
    mem.save()
    again = BindingMemory.load(path)
    assert again.suggest("fluid|tank")[0] == "Lib.Tank"
    assert again.family_weight("fluid", "Lib.Interfaces") == 1.0
    path.write_text("{not json", encoding="utf-8")
    assert BindingMemory.load(path).bindings == {}


def test_a_remembered_class_the_catalog_no_longer_has_is_not_suggested(tmp_path: Path):
    mem = BindingMemory.load(tmp_path / "m.json")
    mem.record_success("fluid|tank", "Lib.Gone", "p")
    assert mem.suggest("fluid|tank", catalog_keys={"Lib.Other"}) is None
