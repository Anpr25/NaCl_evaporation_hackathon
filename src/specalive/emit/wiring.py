"""Decide, before any Modelica is written, whether every wire the evidence draws can exist.

The emitter used to find out at write time: a port with no connector was dropped, a part left
with nothing attached was omitted, and the neighbour it left dangling was pinned to an inert
boundary. Each step kept the model compiling, and together they let a plant compile with its
leakage branch, its flux sensor and its cooling-water header quietly removed -- and print
"HARD GATE MET" above it.

This module moves that judgement in front of emission and makes it a report, not a repair:

  * `insert_series_sensors` puts a through-variable sensor (flux, current, torque) where it
    physically belongs -- in series with the element whose flow it measures -- instead of
    hanging it off a node with its other terminal open;
  * `check_wiring` classifies every connection the evidence states: realisable, or not and
    why (an end that is unbound or architecture-only, a port the bound class has no connector
    for, or two connectors that cannot mate);
  * the pipeline's gate reads the result: a model that compiles with evidence missing is
    reported as INCOMPLETE, with the share of parts and wires that made it in.

Owner: C.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..ir.system import Port, SystemModel

#: Sensors that measure a THROUGH variable, and so belong in series with what they measure.
#: An across-variable sensor (voltage, magnetic potential difference, speed) goes in parallel
#: and is not touched.
_THROUGH_SENSOR = re.compile(r"\.Sensors\.\w*(Flux|Current|Torque|Force|HeatFlow)Sensor$")

#: SpecAlive's causal stream connectors and the one connector each mates with.
_CAUSAL_PAIRS = {
    "Outlet": "Suction", "Suction": "Outlet",
    "Discharge": "Inlet", "Inlet": "Discharge",
}


def _acausal_family(type_name: str) -> str:
    """`...FluxTubes.Interfaces.PositiveMagneticPort` -> `...FluxTubes.Interfaces.MagneticPort`.

    Positive/negative and _a/_b variants of one connector are the same connector to connect().
    """
    pkg, _, leaf = type_name.rpartition(".")
    leaf = re.sub(r"^(Positive|Negative)", "", leaf)
    leaf = re.sub(r"_[ab]$", "", leaf)
    return f"{pkg}.{leaf}"


def mates(type_a: str | None, type_b: str | None) -> tuple[bool, str]:
    """Can connect() join these two connector classes? (yes/no, and why not)."""
    from .modelica import _SIGNAL_TYPES, _is_acausal

    if not type_a or not type_b:
        return True, ""                      # unknown type: nothing to judge, omc will
    leaf_a, leaf_b = (t.rsplit(".", 1)[-1] for t in (type_a, type_b))
    sig_a, sig_b = leaf_a.lower() in _SIGNAL_TYPES, leaf_b.lower() in _SIGNAL_TYPES
    if sig_a or sig_b:
        if not (sig_a and sig_b):
            return False, f"a signal ({leaf_a if sig_a else leaf_b}) cannot carry a physical stream"
        base_a, base_b = (re.sub(r"(Input|Output)$", "", x) for x in (leaf_a, leaf_b))
        if base_a != base_b:
            return False, f"{leaf_a} and {leaf_b} carry different types"
        if leaf_a.endswith("Output") == leaf_b.endswith("Output"):
            return False, f"{leaf_a} to {leaf_b}: two {'outputs' if leaf_a.endswith('Output') else 'inputs'}"
        return True, ""
    if type_a.startswith("SpecAlive.") or type_b.startswith("SpecAlive."):
        if _CAUSAL_PAIRS.get(leaf_a) == leaf_b:
            return True, ""
        return False, f"{leaf_a} cannot feed {leaf_b} (SpecAlive pairs Outlet-Suction, Discharge-Inlet)"
    if _is_acausal(type_a) and _is_acausal(type_b):
        if _acausal_family(type_a) == _acausal_family(type_b):
            return True, ""
        return False, f"{type_a} and {type_b} are different connectors"
    return True, ""


def insert_series_sensors(model: SystemModel, index: Any) -> list[str]:
    """Move each one-wired through-variable sensor into series with the terminal it reads.

    The magnetic packet wires `GAP_1.useful_flux -> FluxSensor.phi_gap`: one wire, because a
    drawing shows a sensor reading a branch. A flux sensor has zero reluctance between its two
    ports and reports the flux passing through it, so with one port on the gap's node and the
    other open it reads nothing -- and the emitter then tied the open port to the magnetic
    ground as a "return path", shorting the lower yoke. In series it reads exactly the gap's
    flux: the gap's terminal goes to the sensor, and whatever that terminal fed is moved to
    the sensor's other port.
    """
    if index is None:
        return []
    from .modelica import _side_of, _is_acausal

    notes: list[str] = []
    emitted = {b.id for b in model.simulatable_blocks() if b.modelica_class}
    for s in model.simulatable_blocks():
        if not s.modelica_class or not _THROUGH_SENSOR.search(s.modelica_class):
            continue
        entry = index.get(s.modelica_class)
        if entry is None:
            continue
        acausal = [cp for cp in entry.ports if _is_acausal(cp.type)]
        ins = [cp for cp in acausal if _side_of(cp.name, cp.type) == "in"]
        outs = [cp for cp in acausal if _side_of(cp.name, cp.type) == "out"]
        if len(ins) != 1 or len(outs) != 1:
            continue
        mine = [(c, p) for c in model.connections for ref in (c.source, c.target)
                if ref.split(".", 1)[0] == s.id
                and (p := model.port(ref)) is not None and p.name
                and {c.source.split(".", 1)[0], c.target.split(".", 1)[0]} <= emitted]
        if len(mine) != 1:
            continue
        conn, sport = mine[0]
        used = sport.name.split("[")[0]
        free = outs[0] if used == ins[0].name else ins[0] if used == outs[0].name else None
        if free is None:
            continue
        far = conn.target if conn.source.split(".", 1)[0] == s.id else conn.source
        host_id = far.split(".", 1)[0]
        far_port = model.port(far)
        if far_port is None or not far_port.name:
            continue
        host = model.block(host_id)
        node_ids = {p.id for p in host.ports if p.name == far_port.name} if host else set()
        moved = [c for c in model.connections if c is not conn and any(
            ref.split(".", 1)[0] == host_id and ref.split(".", 1)[1] in node_ids
            for ref in (c.source, c.target))]
        if not moved:
            continue
        new = Port(id=f"{free.name}_series", name=free.name, domain=sport.domain,
                   direction="out" if sport.direction == "in" else "in",
                   connector_type=free.type,
                   description=f"series terminal: carries what {far} fed before the sensor")
        s.ports.append(new)
        for c in moved:
            if c.source.split(".", 1)[0] == host_id and c.source.split(".", 1)[1] in node_ids:
                c.source = f"{s.id}.{new.id}"
            else:
                c.target = f"{s.id}.{new.id}"
        notes.append(f"{s.id}: inserted in series at {host_id}.{far_port.name} "
                     f"(re-routed {', '.join(c.id for c in moved)} through {s.id}.{free.name}), "
                     f"so it reads the flow through that terminal")
    return notes


@dataclass
class WiringReport:
    """Every connection the evidence states, and whether the emitted model can carry it."""

    connections_total: int = 0
    connections_ok: int = 0
    issues: list[tuple[str, str]] = field(default_factory=list)   # (connection id, why)
    parts_total: int = 0
    parts_bound: int = 0
    unbound: list[str] = field(default_factory=list)
    #: Wires to a part the evidence places outside the executable model (a utility supply,
    #: an instrument whose physics is not simulated). Reported, not counted as missing:
    #: the model represents them by a boundary condition or not at all, by decision.
    at_boundary: list[tuple[str, str]] = field(default_factory=list)

    def summary(self) -> str:
        return (f"{self.parts_bound}/{self.parts_total} parts bound, "
                f"{self.connections_ok}/{self.connections_total} connections realisable")

    def as_dict(self) -> dict[str, Any]:
        return {"connections_total": self.connections_total, "connections_ok": self.connections_ok,
                "issues": [{"connection": c, "why": w} for c, w in self.issues],
                "parts_total": self.parts_total, "parts_bound": self.parts_bound,
                "unbound": self.unbound,
                "at_boundary": [{"connection": c, "why": w} for c, w in self.at_boundary]}


def check_wiring(model: SystemModel, index: Any) -> WiringReport:
    """Classify every evidenced connection between simulatable parts. Mutates nothing."""
    rep = WiringReport()
    sim = {b.id: b for b in model.simulatable_blocks()}
    bound = {bid for bid, b in sim.items() if b.modelica_class and b.binding_tier != "unbound"}
    rep.parts_total, rep.parts_bound = len(sim), len(bound)
    rep.unbound = sorted(set(sim) - bound)
    for c in model.connections:
        ends = [ref.split(".", 1)[0] for ref in (c.source, c.target)]
        if not any(e in sim for e in ends):
            continue                         # wholly outside the executable model
        outside = [e for e in ends if e not in sim]
        if outside:
            rep.at_boundary.append((c.id, f"{outside[0]} is outside the executable model"))
            continue
        rep.connections_total += 1
        why = ""
        for e in ends:
            if e not in bound:
                why = f"{e} is unbound"
            if why:
                break
        if not why:
            pa, pb = model.port(c.source), model.port(c.target)
            for ref, p in ((c.source, pa), (c.target, pb)):
                if p is None or not p.name:
                    why = f"{ref} has no connector on {sim[ref.split('.', 1)[0]].modelica_class}"
                    break
            if not why:
                ok, why = mates(pa.connector_type, pb.connector_type)
                why = "" if ok else why
        if why:
            rep.issues.append((c.id, why))
        else:
            rep.connections_ok += 1
    return rep
