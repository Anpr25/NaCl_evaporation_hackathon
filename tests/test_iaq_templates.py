"""Step 3: what a ventilation (IAQ) packet needs to bind and wire -- zone/source/sensor
templates, ports matched by name across physical and signal connectors, the flow-sign
convention the register states, and one-value constants."""

from __future__ import annotations

from dataclasses import dataclass, field

from specalive.emit.modelica import apply_flow_sign, map_block_parameters, resolve_ports
from specalive.extract.claims import normalise_header
from specalive.ir.system import Block, Connection, Parameter, Port, Quantity, SystemModel


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


class _Index:
    def __init__(self, entries: list[_Entry]) -> None:
        self._by = {e.key: e for e in entries}

    def get(self, key):
        return self._by.get(key)


ZONE = _Entry("SpecAlive.Zones.WellMixedZone",
              ports=[_CPort("inlet", "SpecAlive.Interfaces.Inlet"),
                     _CPort("outlet", "SpecAlive.Interfaces.Discharge"),
                     _CPort("C", "Modelica.Blocks.Interfaces.RealOutput")],
              params=[_CParam("V"), _CParam("nIn", "Integer"), _CParam("nOut", "Integer")])
SUPPLY = _Entry("SpecAlive.Sources.CommandedSupply",
                ports=[_CPort("m_flow_in", "Modelica.Blocks.Interfaces.RealInput"),
                       _CPort("C_in", "Modelica.Blocks.Interfaces.RealInput"),
                       _CPort("outlet", "SpecAlive.Interfaces.Discharge")],
                params=[_CParam("flowSign"), _CParam("T")])
SENSOR = _Entry("SpecAlive.Sensors.IdealSensor",
                ports=[_CPort("u", "Modelica.Blocks.Interfaces.RealInput"),
                       _CPort("y", "Modelica.Blocks.Interfaces.RealOutput")])


def _model() -> SystemModel:
    zone = Block(id="ROOM", name="Room", kind="zone", modelica_class=ZONE.key, ports=[
        Port(id="supply_in", name="supply_in", domain="fluid", direction="in"),
        Port(id="exhaust", name="exhaust", domain="fluid", direction="out"),
        Port(id="c_room", name="c_room", domain="fluid", direction="out")])
    oa = Block(id="OA", name="Outdoor air", kind="source", modelica_class=SUPPLY.key,
               description="Simulation source sign is negative for inflow.", ports=[
        Port(id="m_flow", name="m_flow", domain="fluid", direction="in"),
        Port(id="c", name="c", domain="fluid", direction="in"),
        Port(id="air", name="air", domain="fluid", direction="out")])
    sen = Block(id="SEN", name="CO2 sensor", kind="sensor", modelica_class=SENSOR.key, ports=[
        Port(id="meas", name="meas", domain="fluid", direction="in"),
        Port(id="sig", name="sig", domain="signal", direction="out")])
    ctl = Block(id="CTL", name="Controller", kind="controller", ports=[
        Port(id="ach_cmd", name="ach_cmd", domain="signal", direction="out")])
    amb = Block(id="AMB", name="Ambient", kind="source", ports=[
        Port(id="co2", name="co2", domain="signal", direction="out")])
    return SystemModel(name="iaq", blocks=[zone, oa, sen, ctl, amb], connections=[
        Connection(id="c1", source="OA.air", target="ROOM.supply_in"),
        Connection(id="c2", source="ROOM.c_room", target="SEN.meas"),
        Connection(id="c3", source="CTL.ach_cmd", target="OA.m_flow"),
        Connection(id="c4", source="AMB.co2", target="OA.c"),
        Connection(id="c5", source="ROOM.exhaust", target="SEN.sig"),
    ])


def test_header_ending_in_value_is_the_value_column():
    assert normalise_header("Input Value") == "value"
    assert normalise_header("Value") == "value"


def test_ports_resolve_by_name_across_physical_and_signal_connectors():
    m = _model()
    resolve_ports(m, _Index([ZONE, SUPPLY, SENSOR]))
    names = {f"{b.id}.{p.id}": p.name for b in m.blocks for p in b.ports}
    # the zone's concentration port is its C output, not a second fluid outlet
    assert names["ROOM.c_room"] == "C"
    assert names["ROOM.supply_in"] == "inlet[1]"
    assert names["ROOM.exhaust"] == "outlet[1]"
    # the commanded source's flow and concentration are its signal inputs
    assert names["OA.m_flow"] == "m_flow_in"
    assert names["OA.c"] == "C_in"
    assert names["OA.air"] == "outlet"
    # a fluid stream into a signal-only sensor lands on its input
    assert names["SEN.meas"] == "u"


def test_negative_inflow_sign_in_the_evidence_sets_flow_sign():
    m = _model()
    apply_flow_sign(m, _Index([ZONE, SUPPLY, SENSOR]))
    oa = next(b for b in m.blocks if b.id == "OA")
    assert oa.modelica_modifiers["flowSign"] == "-1"


def test_flow_sign_is_left_alone_without_evidence():
    m = _model()
    for b in m.blocks:
        b.description = None
    apply_flow_sign(m, _Index([ZONE, SUPPLY, SENSOR]))
    assert all("flowSign" not in b.modelica_modifiers for b in m.blocks)


def test_a_one_parameter_class_takes_the_one_stated_value():
    blk = Block(id="SP", name="Setpoint", kind="source", parameters=[
        Parameter(id="SP.setpoint", name="Setpoint", quantity=Quantity(value=1000.0, unit="ppm"))])
    const = _Entry("Modelica.Blocks.Sources.Constant", params=[_CParam("k")])
    out, notes = map_block_parameters(blk, const)
    assert out == {"k": "1000.0"} or out == {"k": "1000"}
    assert notes


def test_two_stated_values_are_not_guessed_into_one_parameter():
    blk = Block(id="SP", name="Setpoint", kind="source", parameters=[
        Parameter(id="SP.a", name="Alpha", quantity=Quantity(value=1.0)),
        Parameter(id="SP.b", name="Beta", quantity=Quantity(value=2.0))])
    const = _Entry("Modelica.Blocks.Sources.Constant", params=[_CParam("k")])
    out, _ = map_block_parameters(blk, const)
    assert "k" not in out


def test_controller_inputs_resolve_by_role_not_declaration_order():
    pi = _Entry("SpecAlive.Controllers.BiasedProportional",
                ports=[_CPort("u_s", "Modelica.Blocks.Interfaces.RealInput"),
                       _CPort("u_m", "Modelica.Blocks.Interfaces.RealInput"),
                       _CPort("y", "Modelica.Blocks.Interfaces.RealOutput")],
                params=[_CParam("k"), _CParam("bias")])
    ctl = Block(id="CTL", name="Controller", kind="controller", modelica_class=pi.key, ports=[
        Port(id="measurement", name="measurement", domain="signal", direction="in"),
        Port(id="setpoint", name="setpoint", domain="signal", direction="in"),
        Port(id="ach_cmd", name="ach_cmd", domain="signal", direction="out")])
    src = Block(id="S", name="s", kind="source", ports=[
        Port(id="a", name="a", domain="signal", direction="out"),
        Port(id="b", name="b", domain="signal", direction="out")])
    snk = Block(id="K", name="k", kind="sink", ports=[
        Port(id="u", name="u", domain="signal", direction="in")])
    m = SystemModel(name="t", blocks=[ctl, src, snk], connections=[
        Connection(id="c1", source="S.a", target="CTL.measurement"),
        Connection(id="c2", source="S.b", target="CTL.setpoint"),
        Connection(id="c3", source="CTL.ach_cmd", target="K.u")])
    resolve_ports(m, _Index([pi]))
    names = {p.id: p.name for p in ctl.ports}
    assert names == {"measurement": "u_m", "setpoint": "u_s", "ach_cmd": "y"}


def test_memory_cannot_pull_a_signal_block_into_a_fluid_family():
    from specalive.emit.families import plan_families

    gain = _Entry("Modelica.Blocks.Math.Gain",
                  ports=[_CPort("u", "Modelica.Blocks.Interfaces.RealInput"),
                         _CPort("y", "Modelica.Blocks.Interfaces.RealOutput")])

    class Binder:
        _require: set = set()

        def candidates(self, block):
            return [("Modelica.Blocks.Math.Gain", 4.0, "template"),
                    ("SpecAlive.Sources.CommandedSupply", 3.0, "retrieval")]

        def _try_declared(self, block):
            return None

    class Memory:
        def family_weight(self, domain, fam):
            return 10.0 if fam == "SpecAlive.Interfaces" else 0.0

    blk = Block(id="G", name="Gain", kind="Gain", domains=["fluid", "signal"])
    required, _ = plan_families(SystemModel(name="t", blocks=[blk]),
                                _Index([gain, SUPPLY]), Binder(), Memory())
    assert "G" not in required


def test_a_threshold_in_an_unconverted_unit_is_not_a_check():
    from specalive.verify.criteria import scale_mismatch

    cols = {"time": [0.0, 1.0], "ZON.C": [0.0, 1.5e-3], "LT.level": [0.0, 1e-3]}
    assert scale_mismatch("max(ZON.C) <= 1000", cols)            # ppm against kg/kg
    assert not scale_mismatch("max(ZON.C) <= 1.519e-3", cols)    # converted
    assert not scale_mismatch("max(LT.level) <= 2.5", cols)      # a nearly empty tank is fine
