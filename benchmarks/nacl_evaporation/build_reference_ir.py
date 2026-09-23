"""Build the NaCl reference IR: the oracle for extraction and the input for emission.

This file is hand-authored from the evidence packet, on purpose. It serves three jobs:

  1. it unblocks B, C and D on day one -- they can build emitters, the repair loop and the
     report against a real IR without waiting for A's extractor;
  2. it is the *target* for A's extractor -- `specalive ir-diff` scores the extracted IR
     against this one, which turns "did extraction work?" into a number;
  3. it documents, in executable form, what the correct answer to this packet is, including
     every trap resolution.

Run:  python benchmarks/nacl_evaporation/build_reference_ir.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from specalive.ir.evidence import DecisionRecord, Gap  # noqa: E402
from specalive.ir.system import (  # noqa: E402
    AcceptanceCheck,
    Block,
    Connection,
    Interlock,
    Parameter,
    Port,
    Provenance,
    Quantity,
    Requirement,
    Scenario,
    Signal,
    State,
    StateMachine,
    SystemModel,
    Transition,
)

P = Provenance


def q(v, u=None):
    return Quantity(value=v, unit=u)


# --------------------------------------------------------------------------- parameters
SETPOINTS = [
    ("SP-B3-LVL-WATER", "B3 water prefill level", 0.13, "m", "effective"),
    ("SP-B3-COMP", "B3 NaCl target after mixing", 0.08, "kg/kg", "effective"),
    ("SP-B3-EMPTY", "B3 nearly-empty threshold", 0.01, "m", "effective"),
    ("SP-B5-IDLE", "B5 idle level threshold", 0.01, "m", "effective"),
    ("SP-B5-BATCH", "B5 batch fill level", 0.18, "m", "effective"),
    ("SP-B5-COMP", "B5 NaCl target after evaporation", 0.18, "kg/kg", "effective"),
    ("SP-B6-COOL", "B6 cooling complete temperature", 293.15, "K", "effective"),
    ("SP-B7-COOL-OLD", "B7 cooling complete temperature (legacy)", 293.15, "K", "superseded"),
    ("SP-B7-COOL", "B7 cooling complete temperature", 298.15, "K", "effective"),
    ("SP-K1-CW", "Minimum cooling-water flow for heater permissive", 0.10, "kg/s", "effective"),
    ("SP-B5-Q", "Heater duty", 20000.0, "W", "effective"),
    ("SP-B6-Q", "B6 nominal cooling duty", 6500.0, "W", "effective"),
    ("SP-B7-Q", "B7 nominal cooling duty", 4500.0, "W", "effective"),
    ("SP-RESTART", "Minimum cycle restart time", 2500.0, "s", "effective"),
    ("SP-HEATER-LVL", "Heater minimum level permissive", 0.05, "m", "effective"),
    ("SP-PUMP-LVL", "Pump dry-run inhibit level", 0.02, "m", "effective"),
]

# --------------------------------------------------------------------------- vessels
#           id  name                 kind                area  levelMax lvl0   w0     class
VESSELS = [
    ("B1", "Charging tank",   "tank",            0.070, 0.50, 0.45, 0.000, "SpecAlive.Vessels.Reservoir"),
    ("B2", "Charging tank",   "tank",            0.070, 0.50, 0.30, 0.250, "SpecAlive.Vessels.Reservoir"),
    ("B3", "Mixing tank",     "tank",            0.050, 0.38, 0.005, 0.000, "SpecAlive.Vessels.Reservoir"),
    ("B4", "Buffer tank",     "tank",            0.055, 0.40, 0.005, 0.000, "SpecAlive.Vessels.Reservoir"),
    ("B5", "Evaporator",      "evaporator vessel", 0.060, 0.40, 0.005, 0.000, "SpecAlive.Vessels.Evaporator"),
    ("B6", "Condensate cooler", "cooling tank",  0.050, 0.35, 0.005, 0.000, "SpecAlive.Vessels.CooledVessel"),
    ("B7", "Concentrate cooler", "cooling tank", 0.050, 0.35, 0.005, 0.000, "SpecAlive.Vessels.CooledVessel"),
]

PATHS = [
    # id      name                 from      to        flow    valves in series
    ("L_V8",  "B1 to B3 transfer", "B1.out", "B3.in1", 0.040, ["V8"]),
    ("L_V9",  "B2 to B3 transfer", "B2.out", "B3.in2", 0.020, ["V9"]),
    ("L_V11", "B3 to B4 transfer", "B3.out", "B4.in1", 0.060, ["V11"]),
    ("L_V12", "B4 to B5 transfer", "B4.out", "B5.in1", 0.060, ["V12"]),
    ("L_V15", "B5 to B7 transfer", "B5.out", "B7.in1", 0.060, ["V15"]),
]

# CR-017: condensate B6 -> B1 via P2; concentrate B7 -> B2 via P1. The pump-side valve group
# follows its pump, the destination-side group follows the destination. Getting this backwards
# is trap F2 and is what the legacy .puml and the legacy .mo both do.
RETURNS = [
    ("RET_A", "Condensate return B6 to B1", "B6.out", "B1.in1", 0.30,
     ["P2", "V20", "V24", "V25", "V1", "V3"], "REQ-ROU-003"),
    ("RET_B", "Concentrate return B7 to B2", "B7.out", "B2.in1", 0.30,
     ["P1", "V18", "V22", "V23", "V5", "V6"], "REQ-ROU-004"),
]

AUTOMATED_VALVES = ["V1", "V3", "V5", "V6", "V8", "V9", "V11", "V12", "V15",
                    "V18", "V20", "V22", "V23", "V24", "V25"]
MANUAL_VALVES = ["V2", "V4", "V7", "V10", "V13", "V14", "V16", "V17", "V19",
                 "V21", "V26", "V27", "V29"]

SENSORS = [
    ("LIS_301", "B3.level", "m"), ("QI_302", "B3.w", "kg/kg"),
    ("LIS_401", "B4.level", "m"), ("LIS_501", "B5.level", "m"),
    ("QIS_502", "B5.w", "kg/kg"), ("TI_503", "B5.T", "K"),
    ("LIS_601", "B6.level", "m"), ("TIS_602", "B6.T", "K"),
    ("LIS_701", "B7.level", "m"), ("TIS_702", "B7.T", "K"),
    ("FIS_801", "cw.y", "kg/s"),
]

# state id, name, region, initial, actions
STATES = [
    ("Initial", "Idle / reset", "main", True, {}),
    ("Step1", "Water charge to B3", "main", False, {"cmd_V8": "true"}),
    ("Step2", "Brine charge and mix", "main", False, {"cmd_V9": "true"}),
    ("Step3", "B3 to B4", "main", False, {"cmd_V11": "true"}),
    ("Step4", "Wait for B5 idle", "main", False, {}),
    ("Step5", "B4 to B5", "main", False, {"cmd_V12": "true"}),
    ("Step6", "Heat and evaporate B5", "main", False, {"cmd_heater": "true"}),
    ("Split", "Parallel branches active", "main", False, {}),
    ("Join", "Wait for both branches", "main", False, {}),
    ("IdleA", "Branch A inactive", "A", True, {}),
    ("Step12", "Cool condensate in B6", "A", False, {"cmd_coolB6": "true"}),
    ("Step13", "Return condensate to B1", "A", False,
     {"cmd_P2": "true", "cmd_V20": "true", "cmd_V24": "true", "cmd_V25": "true",
      "cmd_V1": "true", "cmd_V3": "true"}),
    ("DoneA", "Branch A complete", "A", False, {}),
    ("IdleB", "Branch B inactive", "B", True, {}),
    ("Step7", "Wait for B7 idle", "B", False, {}),
    ("Step8", "B5 concentrate to B7", "B", False, {"cmd_V15": "true"}),
    ("Step9", "Cool concentrate in B7", "B", False, {"cmd_coolB7": "true"}),
    ("Step10", "Return concentrate to B2", "B", False,
     {"cmd_P1": "true", "cmd_V18": "true", "cmd_V22": "true", "cmd_V23": "true",
      "cmd_V5": "true", "cmd_V6": "true"}),
    ("DoneB", "Branch B complete", "B", False, {}),
]

TRANSITIONS = [
    ("T0", "Initial", "Step1", "time >= 20", [], [], ["REQ-FUN-001"]),
    ("T1", "Step1", "Step2", "LIS_301 >= SP_B3_LVL_WATER", [], [], ["REQ-FUN-002"]),
    ("T2", "Step2", "Step3", "QI_302 >= SP_B3_COMP", [], [], ["REQ-FUN-003", "REQ-PER-001"]),
    ("T3", "Step3", "Step4", "LIS_301 < SP_B3_EMPTY", [], [], ["REQ-FUN-004"]),
    ("T4", "Step4", "Step5", "LIS_501 < SP_B5_IDLE", [], [], ["REQ-FUN-005"]),
    ("T5", "Step5", "Step6", "LIS_501 >= SP_B5_BATCH or LIS_401 < SP_B3_EMPTY", [], [], ["REQ-FUN-006"]),
    ("T6", "Step6", "Split", "QIS_502 >= SP_B5_COMP", ["Step12", "Step7"], [], ["REQ-FUN-007", "REQ-FUN-008"]),
    ("T7", "Split", "Join", "in(DoneA) and in(DoneB)", [], ["DoneA", "DoneB"], ["REQ-FUN-008"]),
    ("T8", "Join", "Initial", "time > SP_RESTART", [], [], ["REQ-CTL-001"]),
    ("TA1", "Step12", "Step13", "TIS_602 <= SP_B6_COOL", [], [], ["REQ-FUN-009"]),
    ("TA2", "Step13", "DoneA", "LIS_601 <= SP_PUMP_LVL", [], [], ["REQ-ROU-003"]),
    ("TB1", "Step7", "Step8", "LIS_701 < SP_B5_IDLE", [], [], []),
    ("TB2", "Step8", "Step9", "LIS_501 < SP_B5_IDLE", [], [], []),
    ("TB3", "Step9", "Step10", "TIS_702 <= SP_B7_COOL", [], [], ["REQ-FUN-010"]),
    ("TB4", "Step10", "DoneB", "LIS_701 <= SP_PUMP_LVL", [], [], ["REQ-ROU-004"]),
]

CHECKS = [
    ("BAT09-01", "Step1 exits at LIS-301 >= 0.13 m", "crosses(B3.level, 0.13, rising)", ["REQ-FUN-002"]),
    ("BAT09-02", "Step2 exits at QI-302 >= 0.080 kg/kg", "crosses(B3.w, 0.08, rising)", ["REQ-PER-001"]),
    ("BAT09-03", "Step3 empties B3 below 0.01 m", "crosses(B3.level, 0.01, falling)", ["REQ-FUN-004"]),
    ("BAT09-04", "B5 charge reaches 0.18 m", "crosses(B5.level, 0.18, rising)", ["REQ-FUN-006"]),
    ("BAT09-05", "Evaporation reaches QIS-502 >= 0.180 kg/kg", "crosses(B5.w, 0.18, rising)", ["REQ-PER-002"]),
    ("BAT09-06", "B6 cools to 20 degC or below", "crosses(B6.T, 293.15, falling)", ["REQ-FUN-009"]),
    ("BAT09-07", "B7 cools to 25 degC or below (CR-017)", "crosses(B7.T, 298.15, falling)", ["REQ-FUN-010"]),
    ("BAT09-08", "B6 cooling completes before B7 return starts",
     "before(crosses(B6.T, 293.15, falling), crosses(B7.level, 0.02, falling))", ["REQ-FUN-008"]),
    ("BAT09-09", "Condensate reaches B1, raising its inventory after the return",
     "final(B1.level) >= 0.30", ["REQ-ROU-003"]),
    ("BAT09-10", "Concentrate reaches B2, diluting it below its 0.25 initial charge",
     "final(B2.w) <= 0.25", ["REQ-ROU-004"]),
    ("BAT09-11", "Cycle restarts only after 2500 s", "crosses(B3.level, 0.13, rising)", ["REQ-CTL-001"]),
    ("BAT09-12", "B5 level never goes negative", "always(B5.level >= 0.0)", []),
]


def build() -> SystemModel:
    m = SystemModel(
        name="NaClEvaporationPlant",
        description="Laboratory NaCl evaporation bench: charge, mix, buffer, evaporate, cool, return",
        domains=["fluid", "thermal", "control"],
    )

    m.parameters = [
        Parameter(
            id=pid, name=pid.replace("-", "_"), quantity=q(val, unit), scope="global",
            description=desc, status=status,
            provenance=P(note=f"Setpoint register row {pid}"),
        )
        for pid, desc, val, unit, status in SETPOINTS
    ]

    # ---- vessels -----------------------------------------------------------------
    for vid, name, kind, area, lmax, l0, w0, cls in VESSELS:
        ports = [Port(id="in1", name="inlet[1]", domain="fluid", direction="in")]
        if vid == "B3":
            ports.append(Port(id="in2", name="inlet[2]", domain="fluid", direction="in"))
        ports.append(Port(id="out", name="outlet[1]", domain="fluid", direction="out"))
        if vid == "B5":
            ports.append(Port(id="vapor", name="vapor", domain="fluid", direction="out"))
        params = [
            Parameter(id=f"{vid}.area", name="area", quantity=q(area, "m2")),
            Parameter(id=f"{vid}.levelMax", name="levelMax", quantity=q(lmax, "m")),
            Parameter(id=f"{vid}.level_start", name="level_start", quantity=q(l0, "m")),
            Parameter(id=f"{vid}.w_start", name="w_start", quantity=q(w0, "kg/kg")),
            Parameter(id=f"{vid}.nIn", name="nIn", quantity=q(2 if vid == "B3" else 1)),
            Parameter(id=f"{vid}.nOut", name="nOut", quantity=q(1)),
        ]
        reqs: list[str] = []
        if vid == "B5":
            params.append(Parameter(id="B5.Q_heater", name="Q_heater", quantity=q(20000.0, "W")))
            reqs = ["REQ-THM-001"]
        if vid == "B6":
            params += [Parameter(id="B6.Q_cool", name="Q_cool", quantity=q(6500.0, "W")),
                       Parameter(id="B6.T_floor", name="T_floor", quantity=q(288.15, "K"))]
            reqs = ["REQ-FUN-009"]
        if vid == "B7":
            params += [Parameter(id="B7.Q_cool", name="Q_cool", quantity=q(4500.0, "W")),
                       Parameter(id="B7.T_floor", name="T_floor", quantity=q(288.15, "K"))]
            reqs = ["REQ-FUN-010"]
        m.blocks.append(
            Block(id=vid, name=name, kind=kind, domains=["fluid", "thermal"], ports=ports,
                  parameters=params, description=name, binding_tier="L1", modelica_class=cls,
                  modelica_modifiers={p.name: repr(p.quantity.value) for p in params},
                  binding_rationale="matched L1 template from the equipment schedule",
                  provenance=P(requirement_ids=reqs))
        )

    # ---- condenser: physically distinct even though the legacy model merges it (DR-07 #5) --
    m.blocks.append(
        Block(id="K1", name="Condenser", kind="condenser", domains=["fluid", "thermal"],
              ports=[Port(id="port_a", name="port_a", domain="fluid", direction="in"),
                     Port(id="port_b", name="port_b", domain="fluid", direction="out"),
                     Port(id="cw_flow", name="cw_flow", domain="signal", direction="in")],
              parameters=[Parameter(id="K1.T_out", name="T_out", quantity=q(368.15, "K"))],
              description="Total condenser; retained as a distinct part per DR-07 decision 5",
              binding_tier="L1", modelica_class="SpecAlive.Transport.Condenser",
              modelica_modifiers={"T_out": "368.15"},
              binding_rationale="physical part kept distinct; the legacy merge into B5 is a "
                                "simulation abstraction only",
              provenance=P(note="DR-07 decision 5; trap F3"))
    )

    # ---- transfer paths and returns ------------------------------------------------
    for pid, name, src, tgt, flow, series in PATHS:
        _add_path(m, pid, name, src, tgt, flow, series, "SpecAlive.Transport.Path", [])
    for pid, name, src, tgt, flow, series, req in RETURNS:
        _add_path(m, pid, name, src, tgt, flow, series, "SpecAlive.Transport.Pump", [req])

    # ---- vapour path through the physically distinct condenser -----------------------
    m.connections.append(
        Connection(id="C_B5_K1", source="B5.vapor", target="K1.port_a", domain="fluid",
                   medium="water vapour",
                   provenance=P(requirement_ids=["REQ-THM-001"], note="IF-PROC-09"))
    )
    m.connections.append(
        Connection(id="C_K1_B6", source="K1.port_b", target="B6.in1", domain="fluid",
                   medium="condensate", provenance=P(note="IF-PROC-10"))
    )
    m.connections.append(
        Connection(id="C_CW_K1", source="cw.y", target="K1.cw_flow", domain="signal",
                   medium="cooling-water flow proof",
                   provenance=P(requirement_ids=["REQ-SAF-001"], note="IF-UTIL-01"))
    )

    # ---- utility source -------------------------------------------------------------
    m.blocks.append(
        Block(id="cw", name="Cooling water flow proof", kind="signal source", domains=["signal"],
              ports=[Port(id="y", name="y", domain="signal", direction="out")],
              parameters=[Parameter(id="cw.k", name="k", quantity=q(0.12, "kg/s"))],
              binding_tier="L0", modelica_class="Modelica.Blocks.Sources.Constant",
              modelica_modifiers={"k": "0.12"},
              binding_rationale="unambiguous catalog match",
              provenance=P(requirement_ids=["REQ-SAF-001"]))
    )

    # ---- manual valves: architecture only, never controller outputs (trap F5) ---------
    for v in MANUAL_VALVES:
        m.blocks.append(
            Block(id=v, name=f"Manual valve {v}", kind="manual isolation valve", domains=["fluid"],
                  physical_only=True,
                  description="Shown on the P&ID but not in the controller actuator bundle",
                  provenance=P(requirement_ids=["REQ-DAT-002"], note="trap F5: drawing completeness"))
        )

    # ---- signals ----------------------------------------------------------------------
    for sid, binding, unit in SENSORS:
        m.signals.append(
            Signal(id=sid, name=sid, role="sensor", datatype="real", unit=unit,
                   binding=binding, owner="controller",
                   provenance=P(requirement_ids=["REQ-DAT-001"]))
        )
    for v in AUTOMATED_VALVES:
        m.signals.append(
            Signal(id=f"cmd_{v}", name=f"cmd_{v}", role="actuator", datatype="boolean",
                   owner="controller", provenance=P(requirement_ids=["REQ-DAT-002", "REQ-CTL-002"]))
        )
    for aid, binding in (("cmd_P1", None), ("cmd_P2", None), ("cmd_heater", "B5.heater"),
                         ("cmd_coolB6", "B6.cooler"), ("cmd_coolB7", "B7.cooler")):
        m.signals.append(
            Signal(id=aid, name=aid, role="actuator", datatype="boolean", binding=binding,
                   owner="controller", provenance=P(requirement_ids=["REQ-DAT-002"]))
        )

    m.interlocks = [
        Interlock(id="IL-HEATER", actuator="cmd_heater",
                  condition="LIS_501 >= SP_HEATER_LVL and FIS_801 >= SP_K1_CW",
                  sense="permissive", provenance=P(requirement_ids=["REQ-SAF-001", "REQ-SAF-005"])),
        Interlock(id="IL-P1", actuator="cmd_P1", condition="LIS_701 > SP_PUMP_LVL",
                  sense="permissive", provenance=P(requirement_ids=["REQ-SAF-003"])),
        Interlock(id="IL-P2", actuator="cmd_P2", condition="LIS_601 > SP_PUMP_LVL",
                  sense="permissive", provenance=P(requirement_ids=["REQ-SAF-004"])),
    ]

    # ---- behaviour ----------------------------------------------------------------------
    m.state_machines = [
        StateMachine(
            id="ctrl", name="BatchController", regions=["main", "A", "B"], scan_period=0.1,
            states=[State(id=s, name=n, region=r, initial=i, actions=a, description=n)
                    for s, n, r, i, a in STATES],
            transitions=[Transition(id=t, source_state=s, target_state=g, guard=gu,
                                    forks=f, joins=j, provenance=P(requirement_ids=rq))
                         for t, s, g, gu, f, j, rq in TRANSITIONS],
            provenance=P(requirement_ids=["REQ-FUN-008", "REQ-CTL-001"]),
        )
    ]

    m.scenarios = [
        Scenario(id="BAT-09", name="BAT09", stop_time=3000.0, interval=5.0, tolerance=1e-6,
                 solver="dassl",
                 checks=[AcceptanceCheck(id=c, description=d, expression=e, requirement_ids=r)
                         for c, d, e, r in CHECKS],
                 provenance=P(requirement_ids=["REQ-VV-001", "REQ-VV-002"]))
    ]

    m.requirements = _requirements()
    _link_satisfaction(m)
    m.decisions = _decisions()
    m.gaps = _gaps()
    return m


def _add_path(m, pid, name, src, tgt, flow, series, cls, reqs):
    m.blocks.append(
        Block(id=pid, name=name, kind="transfer path", domains=["fluid"],
              ports=[Port(id="port_a", name="port_a", domain="fluid", direction="in"),
                     Port(id="port_b", name="port_b", domain="fluid", direction="out")],
              parameters=[Parameter(id=f"{pid}.m_flow_nominal", name="m_flow_nominal",
                                    quantity=q(flow, "kg/s"))],
              description=f"{name} (series group: {', '.join(series)})",
              binding_tier="L1", modelica_class=cls,
              modelica_modifiers={"m_flow_nominal": repr(flow)},
              binding_rationale=f"series valve group {series} lowered to one commanded Path",
              provenance=P(requirement_ids=reqs))
    )
    sb, sp = src.split(".")
    tb, tp = tgt.split(".")
    m.connections.append(
        Connection(id=f"C_{pid}_a", source=f"{sb}.{sp}", target=f"{pid}.port_a",
                   domain="fluid", medium="process liquid",
                   provenance=P(requirement_ids=reqs))
    )
    m.connections.append(
        Connection(id=f"C_{pid}_b", source=f"{pid}.port_b", target=f"{tb}.{tp}",
                   domain="fluid", medium="process liquid", series_elements=series,
                   provenance=P(requirement_ids=reqs))
    )


def _requirements() -> list[Requirement]:
    rows = [
        ("REQ-FUN-001", "The plant shall prepare a mixed water/NaCl batch in B3 using liquid from B1 and B2.", "active", None),
        ("REQ-FUN-002", "The controller shall open V8 to transfer B1 liquid to B3 until LIS-301 is at least 0.13 m.", "active", None),
        ("REQ-FUN-003", "After the B1 fill portion, the controller shall open V9 and continue charging B3 until QI-302 reaches the batch concentration target.", "active", None),
        ("REQ-PER-001", "The B3 target NaCl mass fraction shall be 0.080 kg/kg.", "active", None),
        ("REQ-FUN-004", "V11 shall transfer the mixed batch from B3 to B4 until LIS-301 is below 0.01 m.", "active", None),
        ("REQ-FUN-005", "The controller shall not charge B5 unless B5 is idle, defined by LIS-501 < 0.01 m and V15 closed.", "active", None),
        ("REQ-FUN-006", "V12 shall transfer B4 contents to B5 until LIS-501 reaches 0.18 m.", "active", None),
        ("REQ-THM-001", "B5 heating demand shall be 20,000 W when the heater actuator is enabled.", "active", None),
        ("REQ-SAF-001", "B5 heating shall be inhibited unless FIS-801 proves condenser cooling-water flow of at least 0.10 kg/s.", "active", None),
        ("REQ-FUN-007", "B5 heating/evaporation shall continue until QIS-502 reaches the evaporation concentration target.", "active", None),
        ("REQ-PER-002", "The B5 evaporation concentration target shall be 0.180 kg/kg NaCl mass fraction.", "active", None),
        ("REQ-FUN-008", "After evaporation completes, the sequence shall split into parallel condensate and concentrate branches.", "active", None),
        ("REQ-FUN-009", "The condensate branch shall cool B6 to 20 degC or below before return pumping.", "active", None),
        ("REQ-FUN-010", "The concentrate branch shall cool B7 to 25 degC or below before return pumping.", "active", None),
        ("REQ-ROU-001", "The B7/P1 return branch opens V18,V23,V22,V1,V3.", "superseded", "CR-017"),
        ("REQ-ROU-002", "The B6/P2 return branch opens V20,V24,V25,V5,V6.", "superseded", "CR-017"),
        ("REQ-ROU-003", "The recovered condensate stream from B6 shall be returned to B1 using P2 and the B1 return valve group.", "active", None),
        ("REQ-ROU-004", "The cooled concentrated stream from B7 shall be returned to B2 using P1 and the B2 return valve group.", "active", None),
        ("REQ-CTL-001", "The cycle shall not restart until both parallel return branches are complete and process time exceeds 2500 s.", "active", None),
        ("REQ-CTL-002", "All automated process valves shall be Boolean, discrete open/closed actuators.", "active", None),
        ("REQ-SAF-002", "All automated process valves shall fail closed on loss of actuator power.", "active", None),
        ("REQ-SAF-003", "P1 shall be inhibited when LIS-701 <= 0.02 m.", "active", None),
        ("REQ-SAF-004", "P2 shall be inhibited when LIS-601 <= 0.02 m.", "active", None),
        ("REQ-SAF-005", "The heater shall be inhibited when LIS-501 < 0.05 m.", "active", None),
        ("REQ-MOD-001", "The baseline integration test shall use a single-component water medium to validate plant topology and control sequence.", "active", None),
        ("REQ-MOD-002", "The intended physical medium model shall represent a water-NaCl mixture with composition-dependent properties.", "active", None),
        ("REQ-MOD-003", "The WaterNaCl implementation shall document the known unresolved pump-start convergence issue separately from plant functional requirements.", "active", None),
        ("REQ-MOD-004", "Tank ports that can cross the liquid level shall use a regularized asymmetric loss-factor approach with hysteresis.", "active", None),
        ("REQ-MOD-005", "Small junction volumes shall be inserted wherever multiple pressure-drop-only elements can be isolated simultaneously.", "active", None),
        ("REQ-MOD-006", "Non-horizontal pipes shall include gravity pressure drop based on relative elevation.", "active", None),
        ("REQ-DAT-001", "Controller sensor inputs shall include LIS-301, QI-302, LIS-501, QIS-502, TIS-602, TIS-702 and FIS-801.", "active", None),
        ("REQ-DAT-002", "Controller actuator outputs shall include the 15 automated valve commands, P1, P2, B5 heater, B6 cooler and B7 cooler.", "active", None),
        ("REQ-VV-001", "A complete acceptance simulation shall run through at least one parallel-branch split and rejoin and continue beyond 2500 s.", "active", None),
        ("REQ-VV-002", "The acceptance run shall demonstrate B3 target concentration, B5 target concentration, B6 cooling target, B7 cooling target and correct return routing.", "active", None),
    ]
    return [
        Requirement(id=r, text=t, status=s, superseded_by=sb, priority="must",
                    provenance=P(note="Requirement register"))
        for r, t, s, sb in rows
    ]


def _link_satisfaction(m: SystemModel) -> None:
    """Populate Requirement.satisfied_by from the provenance already attached to elements."""
    index: dict[str, list[str]] = {}
    for coll in (m.blocks, m.connections, m.signals, m.interlocks, m.state_machines):
        for el in coll:
            for rid in el.provenance.requirement_ids:
                index.setdefault(rid, []).append(el.id)
    for sm in m.state_machines:
        for t in sm.transitions:
            for rid in t.provenance.requirement_ids:
                index.setdefault(rid, []).append(f"{sm.id}.{t.id}")
    for r in m.requirements:
        r.satisfied_by = sorted(set(index.get(r.id, [])))


def _decisions() -> list[DecisionRecord]:
    return [
        DecisionRecord(
            id="DEC-0001", subject="B7", predicate="cooling_target",
            winner_claim_id="CLM-SP-B7-COOL", loser_claim_ids=["CLM-SP-B7-COOL-OLD"],
            rule_id="P1-explicit-supersession",
            rationale="CR-017 (approved change record, 2026-03-05) sets B7 cooling completion to "
                      "25 degC and explicitly supersedes the 20 degC value carried in the legacy "
                      "Modelica file, the lab notebook and a handwritten commissioning sheet.",
            failure_mode="F1-recency-bias",
        ),
        DecisionRecord(
            id="DEC-0002", subject="B6", predicate="return_destination",
            winner_claim_id="CLM-REQ-ROU-003", loser_claim_ids=["CLM-REQ-ROU-002"],
            rule_id="P1-explicit-supersession",
            rationale="CR-017 corrects the stream-identity semantics: recovered condensate from "
                      "B6 returns to B1. The legacy StateGraph extract and the draft PlantUML "
                      "both state the opposite and are marked superseded.",
            failure_mode="F2-physical-layout-implies-function",
        ),
        DecisionRecord(
            id="DEC-0003", subject="B7", predicate="return_destination",
            winner_claim_id="CLM-REQ-ROU-004", loser_claim_ids=["CLM-REQ-ROU-001"],
            rule_id="P1-explicit-supersession",
            rationale="CR-017: cooled concentrate from B7 returns to B2 via P1. P1 is drawn "
                      "beside B1 on the P&ID, but the datasheet states the discharge headers are "
                      "cross-connected, so pump location does not determine destination.",
            failure_mode="F2-physical-layout-implies-function",
        ),
        DecisionRecord(
            id="DEC-0004", subject="K1", predicate="exists_as_part",
            winner_claim_id="CLM-DR07-5", loser_claim_ids=["CLM-LEGACY-MERGE"],
            rule_id="P3-authority-class",
            rationale="DR-07 decision 5 (approved review) states K1 remains a physical condenser "
                      "even though the legacy Modelica component combines evaporator and "
                      "condenser equations. The merge is a simulation abstraction, not an "
                      "architectural fact, so K1 stays a distinct part.",
            failure_mode="F3-simulation-abstraction-as-architecture",
        ),
        DecisionRecord(
            id="DEC-0005", subject="valves", predicate="controller_ownership",
            winner_claim_id="CLM-VALVE-REGISTER", loser_claim_ids=["CLM-PID-DRAWING"],
            rule_id="P3-authority-class",
            rationale="The valve register and the supplier datasheet both name exactly 15 "
                      "automated tags. The P&ID shows 28 devices, but a drawing does not assign "
                      "controller ownership; the 13 remaining valves are manual/local and are "
                      "modelled as architecture-only parts.",
            failure_mode="F5-drawing-completeness",
        ),
        DecisionRecord(
            id="DEC-0006", subject="medium", predicate="intended_model",
            winner_claim_id="CLM-REQ-MOD-002", loser_claim_ids=["CLM-REQ-MOD-001"],
            rule_id="P5-specificity",
            rationale="A single-component water medium is described as an integration baseline "
                      "for topology and sequence debugging, not as the intended physical medium. "
                      "The composition-dependent mixture remains the target; the baseline is "
                      "shipped as Tier 1 and the mixture as Tier 2.",
            failure_mode="F4-baseline-mistaken-for-intent",
        ),
        DecisionRecord(
            id="DEC-0007", subject="P1,P2", predicate="retain_in_model",
            winner_claim_id="CLM-REQ-MOD-003", loser_claim_ids=["CLM-NOTEBOOK-DELETE"],
            rule_id="P2-approval-status",
            rationale="A documented convergence failure at pump start is a numerical defect to "
                      "be recorded, not grounds to delete the pumps. Both return pumps are "
                      "retained and the defect is declared as a gap.",
            failure_mode="F6-known-defect-as-requirement",
        ),
    ]


def _gaps() -> list[Gap]:
    return [
        Gap(id="OPEN-ISSUE-01", kind="unreachable_guard", subject="REQ-FUN-006",
            detail="The guard 'LIS-501 >= 0.18 m' cannot be met from a single B3 batch under a "
                   "mass-consistent balance. B3 holds at most ~0.0091 m3 once it reaches the "
                   "0.080 kg/kg recipe target from a 0.13 m water prefill, which fills B5 to "
                   "about 0.145 m against a required 0.18 m. The two setpoints are mutually "
                   "unsatisfiable as written.",
            requirement_ids=["REQ-FUN-006", "REQ-PER-001", "REQ-FUN-002"], severity="warn",
            workaround="A derived fallback exit on B4 exhaustion was added so the sequence "
                       "cannot deadlock. Raise with the customer as a source-data defect."),
        Gap(id="OPEN-ISSUE-02", kind="inconsistent_reference_data", subject="10_batch_run_3000s.csv",
            detail="The supplied reference trace is not mass-consistent: across the B5 "
                   "evaporation phase the solute inventory (level x concentration) rises 44% "
                   "while concentration rises 0.080 -> 0.180, so NaCl is created. Signal-level "
                   "agreement with this trace is therefore not evidence of correctness.",
            severity="info",
            workaround="Score against BAT-09 event criteria; report signal RMSE as informational "
                       "only, and only after the conservation screen passes."),
        Gap(id="OPEN-ISSUE-03", kind="unimplemented_requirement", subject="REQ-MOD-002",
            detail="Tier 1 uses a linear composition-dependent property set (density, specific "
                   "heat, boiling-point elevation), not a full two-phase mixture medium with "
                   "saturation pressure and viscosity.",
            requirement_ids=["REQ-MOD-002"], severity="warn",
            workaround="Tier 2 WaterNaCl medium; the viscosity correlation coefficients are "
                       "supplied in the medium note, the remaining correlations are not."),
        Gap(id="OPEN-ISSUE-04", kind="deviation", subject="REQ-MOD-004/005/006",
            detail="Tier 1 uses a causal directed-flow abstraction, so there is no pressure "
                   "network: regularized asymmetric port losses, junction volumes and gravity "
                   "head have no numerical effect. Junction volumes and elevation deltas are "
                   "carried in the architecture and as parameters, but are documentation only.",
            requirement_ids=["REQ-MOD-004", "REQ-MOD-005", "REQ-MOD-006"], severity="warn",
            workaround="Tier 2 binds to acausal Modelica.Fluid components where these apply."),
        Gap(id="OPEN-ISSUE-05", kind="unimplemented_requirement", subject="REQ-MOD-003",
            detail="The known WaterNaCl pump-start convergence failure is recorded but not "
                   "diagnosed. Pumps P1 and P2 are retained in both architecture and model.",
            requirement_ids=["REQ-MOD-003"], severity="info"),
    ]


if __name__ == "__main__":
    model = build()
    out = Path(__file__).with_name("reference_ir.json")
    out.write_text(model.model_dump_json(indent=2), encoding="utf-8")
    cov = model.coverage()
    print(f"wrote {out}")
    for k, v in cov.items():
        print(f"  {k:28s} {v}")
