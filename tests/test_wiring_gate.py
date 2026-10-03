"""Step 4: judge the wiring before emitting, wire acausal nodes and series sensors as physics
says, and grade the run on what the model actually contains."""

from __future__ import annotations

from dataclasses import dataclass, field

from specalive.emit.modelica import map_block_parameters, resolve_ports
from specalive.emit.wiring import check_wiring, insert_series_sensors, mates
from specalive.ir.system import Block, Connection, Port, SystemModel
from specalive.pipeline import PipelineResult

MAG = "Modelica.Magnetic.FluxTubes.Interfaces."
POS, NEG = MAG + "PositiveMagneticPort", MAG + "NegativeMagneticPort"
PIN = "Modelica.Electrical.Analog.Interfaces."


@dataclass
class _CPort:
    name: str
    type: str


@dataclass
class _CParam:
    name: str
    type: str = "Real"
    unit: str | None = None
    description: str = ""


@dataclass
class _Entry:
    key: str
    ports: list[_CPort] = field(default_factory=list)
    params: list[_CParam] = field(default_factory=list)
    variables: list[_CParam] = field(default_factory=list)


class _Index:
    def __init__(self, entries: list[_Entry]) -> None:
        self._by = {e.key: e for e in entries}

    def get(self, key):
        return self._by.get(key)


TUBE = _Entry("Modelica.Magnetic.FluxTubes.Shapes.FixedShape.GenericFluxTube",
              ports=[_CPort("port_p", POS), _CPort("port_n", NEG)],
              params=[_CParam("l"), _CParam("area")], variables=[_CParam("R_m"), _CParam("Phi")])
SENSOR = _Entry("Modelica.Magnetic.FluxTubes.Sensors.MagneticFluxSensor",
                ports=[_CPort("Phi", "Modelica.Blocks.Interfaces.RealOutput"),
                       _CPort("port_p", POS), _CPort("port_n", NEG)])
COIL = _Entry("Modelica.Magnetic.FluxTubes.Basic.ElectroMagneticConverter",
              ports=[_CPort("p", PIN + "PositivePin"), _CPort("n", PIN + "NegativePin"),
                     _CPort("port_p", POS), _CPort("port_n", NEG)],
              params=[_CParam("N")])
LEAK = _Entry("Modelica.Magnetic.FluxTubes.Basic.LeakageWithCoefficient",
              ports=[_CPort("R_mUsefulTot", "Modelica.Blocks.Interfaces.RealInput"),
                     _CPort("port_p", POS), _CPort("port_n", NEG)],
              params=[_CParam("c_usefulFlux")])
INDEX = _Index([TUBE, SENSOR, COIL, LEAK])


def _tube(bid: str, *ports: tuple[str, str]) -> Block:
    return Block(id=bid, name=bid, kind="flux tube", domains=["magnetic"], modelica_class=TUBE.key,
                 binding_tier="L0",
                 ports=[Port(id=i, name=i, domain="magnetic", direction=d) for i, d in ports])


def _names(m: SystemModel) -> dict[str, str]:
    return {f"{b.id}.{p.id}": p.name for b in m.blocks for p in b.ports}


# ------------------------------------------------------------------------------ connectors

def test_connectors_mate_by_physics_not_by_name():
    assert mates(PIN + "PositivePin", PIN + "NegativePin")[0]
    assert mates(POS, NEG)[0]
    assert not mates(POS, "Modelica.Magnetic.FundamentalWave.Interfaces.NegativeMagneticPort")[0]
    assert mates("Modelica.Blocks.Interfaces.RealOutput", "Modelica.Blocks.Interfaces.RealInput")[0]
    assert not mates("Modelica.Blocks.Interfaces.RealInput", "Modelica.Blocks.Interfaces.RealInput")[0]
    assert not mates("Modelica.Blocks.Interfaces.RealOutput", "Modelica.Blocks.Interfaces.BooleanInput")[0]
    assert mates("SpecAlive.Interfaces.Discharge", "SpecAlive.Interfaces.Inlet")[0]
    assert mates("SpecAlive.Interfaces.Outlet", "SpecAlive.Interfaces.Suction")[0]
    assert not mates("SpecAlive.Interfaces.Discharge", "SpecAlive.Interfaces.Suction")[0]
    assert not mates("Modelica.Blocks.Interfaces.RealOutput", "SpecAlive.Interfaces.Inlet")[0]


# --------------------------------------------------------------------------- branch nodes

def _parallel_model() -> SystemModel:
    right = _tube("CORE_R", ("p", "in"), ("node", "out"), ("node_2", "out"))
    gap = _tube("GAP", ("p", "in"), ("n", "out"))
    low = _tube("CORE_D", ("p", "in"), ("p_2", "in"), ("n", "out"))
    leak = Block(id="LEAK", name="leakage", kind="leakage", domains=["magnetic"],
                 modelica_class=LEAK.key, binding_tier="L0", description="Parallel with GAP; useful/core flux ratio = 1-sigma = 0.92",
                 ports=[Port(id="p", name="p", domain="magnetic", direction="in"),
                        Port(id="n", name="n", domain="magnetic", direction="out")])
    return SystemModel(name="m", blocks=[right, gap, low, leak], connections=[
        Connection(id="c1", source="CORE_R.node", target="GAP.p"),
        Connection(id="c2", source="CORE_R.node_2", target="LEAK.p"),
        Connection(id="c3", source="GAP.n", target="CORE_D.p"),
        Connection(id="c4", source="LEAK.n", target="CORE_D.p_2"),
    ])


def test_a_second_wire_to_an_acausal_port_is_a_branch_node_not_a_dropped_wire():
    m = _parallel_model()
    problems = resolve_ports(m, INDEX)
    n = _names(m)
    assert n["CORE_R.node"] == n["CORE_R.node_2"] == "port_n"
    assert n["CORE_D.p"] == n["CORE_D.p_2"] == "port_p"
    assert not problems
    rep = check_wiring(m, INDEX)
    assert rep.connections_ok == rep.connections_total == 4


def test_a_causal_input_is_still_never_driven_twice():
    gain = _Entry("Modelica.Blocks.Math.Gain",
                  ports=[_CPort("u", "Modelica.Blocks.Interfaces.RealInput"),
                         _CPort("y", "Modelica.Blocks.Interfaces.RealOutput")])
    g = Block(id="G", name="Gain", kind="Gain", modelica_class=gain.key, ports=[
        Port(id="a", name="a", domain="signal", direction="in"),
        Port(id="b", name="b", domain="signal", direction="in")])
    s = Block(id="S", name="s", kind="source", ports=[
        Port(id="x", name="x", domain="signal", direction="out"),
        Port(id="y", name="y", domain="signal", direction="out")])
    m = SystemModel(name="t", blocks=[g, s], connections=[
        Connection(id="c1", source="S.x", target="G.a"),
        Connection(id="c2", source="S.y", target="G.b")])
    problems = resolve_ports(m, _Index([gain]))
    assert sorted(p.name for p in g.ports) == ["", "u"]
    assert problems


def test_a_potential_source_drives_flow_out_of_its_positive_terminal():
    coil = Block(id="COIL", name="exciting coil", kind="coil", domains=["electrical", "magnetic"],
                 modelica_class=COIL.key, ports=[
                     Port(id="i_in", name="i_in", domain="electrical", direction="in"),
                     Port(id="mag", name="mag", domain="magnetic", direction="out")])
    core = _tube("CORE", ("p", "in"), ("n", "out"))
    src = Block(id="SRC", name="ramp", kind="source", domains=["electrical"], ports=[
        Port(id="o", name="o", domain="electrical", direction="out")])
    m = SystemModel(name="t", blocks=[coil, core, src], connections=[
        Connection(id="c1", source="SRC.o", target="COIL.i_in"),
        Connection(id="c2", source="COIL.mag", target="CORE.p")])
    resolve_ports(m, INDEX)
    n = _names(m)
    assert n["COIL.mag"] == "port_p"      # V_m = N*i pushes flux out of port_p
    assert n["COIL.i_in"] == "p"          # electrically it is a load: current enters p


# ------------------------------------------------------------------------- series sensors

def test_a_flux_sensor_is_moved_into_series_with_what_it_reads():
    gap = _tube("GAP", ("p", "in"), ("n", "out"), ("useful", "out"))
    low = _tube("CORE_D", ("p", "in"), ("n", "out"))
    sen = Block(id="FS", name="flux sensor", kind="sensor", domains=["magnetic"],
                modelica_class=SENSOR.key, binding_tier="L0",
                ports=[Port(id="phi", name="phi", domain="magnetic", direction="in")])
    m = SystemModel(name="t", blocks=[gap, low, sen], connections=[
        Connection(id="c1", source="GAP.n", target="CORE_D.p"),
        Connection(id="c2", source="GAP.useful", target="FS.phi")])
    resolve_ports(m, INDEX)
    notes = insert_series_sensors(m, INDEX)
    assert notes
    c1 = next(c for c in m.connections if c.id == "c1")
    assert c1.source.startswith("FS.") and m.port(c1.source).name == "port_n"
    assert m.port("FS.phi").name == "port_p" and m.port("GAP.useful").name == "port_n"
    assert check_wiring(m, INDEX).connections_ok == 2


# ------------------------------------------------------------------------ stated values

def test_a_value_stated_in_the_description_reaches_the_parameter_it_names():
    m = _parallel_model()
    leak = m.block("LEAK")
    out, notes = map_block_parameters(leak, LEAK)
    assert out.get("c_usefulFlux") in ("0.92",)
    assert notes


# --------------------------------------------------------------------------------- gate

@dataclass
class _Card:
    passed: int
    total: int


def _result(**gate) -> PipelineResult:
    r = PipelineResult()
    r.gate.update({"compiled": True, "simulated": True, "live": True})
    r.gate.update(gate)
    return r


def test_the_gate_grades_what_the_model_contains():
    assert PipelineResult().verdict[0] == "NOT_MET"
    assert _result(live=False).verdict[0] == "INERT"
    partial = {"parts_total": 5, "parts_emitted": 4, "connections_total": 6, "connections_written": 6}
    assert _result(structure=partial).verdict[0] == "INCOMPLETE"
    whole = {"parts_total": 5, "parts_emitted": 5, "connections_total": 6, "connections_written": 6}
    r = _result(structure=whole)
    assert r.verdict[0] == "UNVERIFIED"            # nothing checked
    r.scorecard = _Card(passed=2, total=3)
    assert r.verdict[0] == "UNVERIFIED"            # a check fails
    r.scorecard = _Card(passed=3, total=3)
    assert r.verdict[0] == "MET"
