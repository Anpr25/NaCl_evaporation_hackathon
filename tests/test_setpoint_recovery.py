"""Recovering values the evidence supplies but nothing wires up.

Both mechanisms here replaced an assumption with a fact, and both were worth more than they
look. Binding `K1.cw_flow` to zero instead of to its stated 0.1 kg/s, and leaving `FIS_801`
dangling, cost five of the ten acceptance checks between them -- not because the physics was
wrong but because a number sitting in the register never reached the model.
"""

from __future__ import annotations

from specalive.ir.complete import bind_sensors_to_resolved_setpoints, find_setpoint_for_input
from specalive.ir.system import (
    Interlock,
    Parameter,
    Quantity,
    Signal,
    SystemModel,
)


class _Port:
    def __init__(self, name: str, type_: str) -> None:
        self.name, self.type = name, type_


class _Entry:
    def __init__(self, ports) -> None:
        self.ports = ports
        self.params: list = []


class _Index:
    """The catalog entries the emitter would consult, reduced to what these tests need."""

    def __init__(self, mapping) -> None:
        self._m = mapping

    def get(self, cls):
        return self._m.get(cls)


def _model() -> SystemModel:
    from specalive.ir.system import Block

    return SystemModel(
        name="t",
        parameters=[
            Parameter(
                id="SP-K1-CW", name="SP_K1_CW",
                quantity=Quantity(value=0.1, unit="kg/s"), scope="global",
                description="Minimum cooling-water flow for heater permissive; applies to K1",
            ),
            Parameter(
                id="SP-B3-COMP", name="SP_B3_COMP",
                quantity=Quantity(value=0.08, unit="kg/kg"), scope="global",
                description="B3 target composition",
            ),
        ],
        blocks=[
            Block(id="K1", name="K1", kind="condenser", binding_tier="L1",
                  modelica_class="SpecAlive.Transport.Condenser"),
        ],
        signals=[
            Signal(id="FIS_801", name="FIS_801", role="sensor", unit="kg/s"),
            Signal(id="PIS_901", name="PIS_901", role="sensor", unit="Pa"),
        ],
        interlocks=[
            Interlock(id="IL1", actuator="cmd_heater",
                      condition="FIS_801 >= SP_K1_CW", sense="permissive"),
        ],
    )


def _index() -> _Index:
    return _Index({
        "SpecAlive.Transport.Condenser": _Entry([
            _Port("cw_flow", "Modelica.Blocks.Interfaces.RealInput"),
            _Port("enable", "Modelica.Blocks.Interfaces.BooleanInput"),
        ])
    })


# --------------------------------------------------------------- setpoint -> input


def test_a_stated_setpoint_is_found_for_an_undriven_input():
    m = _model()
    p = find_setpoint_for_input(m, "K1", "cw_flow")
    assert p is not None and p.id == "SP-K1-CW"


def test_an_unrelated_setpoint_is_not_borrowed():
    """The parameter must name this block and overlap this quantity, not merely exist."""
    m = _model()
    assert find_setpoint_for_input(m, "K1", "speed") is None


def test_a_setpoint_for_another_block_is_not_borrowed():
    m = _model()
    assert find_setpoint_for_input(m, "B3", "cw_flow") is None


def test_an_ambiguous_match_is_refused():
    """Two candidates means we do not know; the inert default and its assumption is honest."""
    m = _model()
    m.parameters.append(
        Parameter(id="SP-K1-CW-ALT", name="SP_K1_CW_ALT",
                  quantity=Quantity(value=0.2, unit="kg/s"), scope="global",
                  description="Alternative cooling-water flow for K1")
    )
    assert find_setpoint_for_input(m, "K1", "cw_flow") is None


# --------------------------------------------------------------- setpoint -> sensor


def test_a_dangling_sensor_is_bound_through_its_own_setpoint():
    """FIS_801 >= SP_K1_CW, and SP_K1_CW was matched to K1.cw_flow, so FIS_801 reads it."""
    m = _model()
    notes = bind_sensors_to_resolved_setpoints(m, _index())
    assert m.signal("FIS_801").binding == "K1.cw_flow"
    assert len(notes) == 1 and notes[0].severity == "info"
    assert "no assumption" in (notes[0].workaround or "").lower()


def test_a_sensor_with_no_resolvable_setpoint_is_left_alone():
    """Better an undriven input with a declared assumption than an invented binding."""
    m = _model()
    bind_sensors_to_resolved_setpoints(m, _index())
    assert m.signal("PIS_901").binding is None


def test_an_already_bound_sensor_is_not_rebound():
    m = _model()
    m.signal("FIS_801").binding = "B9.flow"
    bind_sensors_to_resolved_setpoints(m, _index())
    assert m.signal("FIS_801").binding == "B9.flow"


def test_nothing_happens_without_a_catalog():
    """No index means no connectors to match against, so no inference is available."""
    m = _model()
    assert bind_sensors_to_resolved_setpoints(m, None) == []
    assert m.signal("FIS_801").binding is None
