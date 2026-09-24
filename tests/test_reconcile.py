"""Workstream B regression tests: IR assembly, series groups, reachability, SysML round trip.

Each test pins a behaviour the backlog asked for (B1..B5) or a trap the packet plants. The
synthetic cases deliberately use other domains -- a switchboard, capacitors, flywheels -- so a
rule that only works for tanks fails here rather than on evaluation day.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from specalive.emit.sysml import SysMLEmitter, parse_back, round_trip_check
from specalive.extract.claims import column_predicates, extract_claims
from specalive.ingest.registry import load_packet
from specalive.ir.evidence import EvidenceClaim, Locator
from specalive.ir.system import (
    Block,
    Connection,
    Parameter,
    Port,
    Quantity,
    Signal,
    State,
    StateMachine,
    SystemModel,
    Transition,
)
from specalive.ir.validate import ValidationReport, _supply_ceiling, check_guard_reachability, validate
from specalive.reconcile.builder import build_model

ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "nacl_evaporation_sysmlv2_full_dataset"
REF_IR = ROOT / "benchmarks" / "nacl_evaporation" / "reference_ir.json"
PRECEDENCE = ROOT / "config" / "precedence.yaml"

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


@pytest.fixture(scope="module")
def built() -> SystemModel:
    if not PACKET.exists():
        pytest.skip("NaCl packet not present")
    docs = load_packet(PACKET)
    return build_model(docs, extract_claims(docs), precedence_config=PRECEDENCE)


def _route(m: SystemModel, src: str, dst: str) -> Connection:
    """The connection that delivers into `dst` on the path that leaves `src`."""
    first = next(c for c in m.connections if c.source.startswith(f"{src}.") and c.target.endswith(".port_a"))
    path = first.target.split(".")[0]
    return next(c for c in m.connections if c.source == f"{path}.port_b" and c.target.startswith(f"{dst}."))


# ------------------------------------------------------------------------ extraction shape


def test_every_named_column_becomes_a_predicate():
    preds, units, hits = column_predicates(
        ["Interface ID", "From", "From Port", "To", "To Port", "Item/Medium", "Area (m^2)"]
    )
    assert preds[1] == "from" and preds[3] == "to"
    assert preds[2] == "from_port" and preds[4] == "to_port", "a collision must not drop a column"
    assert preds[5] == "item_medium", "an unrecognised header keeps its own name"
    assert (preds[6], units[6]) == ("area", "m^2"), "a header with a unit names a quantity"
    assert hits >= 2


# ------------------------------------------------------------------------------- B1 blocks


def test_blocks_come_from_the_registers_with_honest_scope(built):
    m = built
    for tag in ("B1", "B2", "B3", "B4", "B5", "B6", "B7", "K1"):
        assert m.block(tag) is not None and m.block(tag) in m.simulatable_blocks(), tag
    # F3: the legacy model merges K1 into B5; the architecture keeps it, and says why.
    assert any(d.failure_mode == "F3-simulation-abstraction-as-architecture" and d.subject == "K1"
               for d in m.decisions)
    # Series elements are real parts, lumped into their path for simulation only.
    assert m.block("P2").abstracted_into == _route(m, "B6", "B1").source.split(".")[0]
    # F5: manual valves are architecture-only and never controller outputs.
    for v in ("V2", "V17", "V29"):
        assert m.block(v).physical_only
        assert m.signal(f"cmd_{v}") is None
    assert len([s for s in m.signals if s.role == "actuator" and s.name.startswith("cmd_V")]) == 15
    assert m.block("M_301").physical_only, "a part the register calls physical-only stays out of the model"


def test_a_tag_only_a_model_read_is_flagged_not_built():
    claims = [
        EvidenceClaim(id="c1", source_id="S1", kind="component", subject="V99", predicate="label",
                      value="V99", quote="V99", confidence=0.4, extracted_by="t4_vision"),
    ]
    m = build_model([], claims, precedence_config=PRECEDENCE)
    assert m.block("V99") is None
    assert any(g.subject == "V99" for g in m.gaps)


# ------------------------------------------------------------------------------- B2 series


def test_return_routes_carry_their_full_series_groups(built):
    """Backlog B2 acceptance: the condensate return (reference RET_A) carries {P2,V20,V24,V25,V1,V3}."""
    ret_a = _route(built, "B6", "B1")
    ret_b = _route(built, "B7", "B2")
    assert ret_a.series_elements == ["P2", "V20", "V24", "V25", "V1", "V3"]
    assert set(ret_b.series_elements) == {"P1", "V18", "V22", "V23", "V5", "V6"}
    # F2: the destination group follows the destination, and the derivation is on record.
    groups = {d.subject: d for d in built.decisions if d.rule_id == "D-group-membership"}
    assert {"B1 group", "B2 group"} <= set(groups)
    assert all(d.failure_mode == "F2-physical-layout-implies-function" for d in groups.values())


def _row(cid: str, subject: str, predicate: str, value, sheet: str, row: int) -> EvidenceClaim:
    return EvidenceClaim(id=cid, source_id="S1", kind="note", subject=subject, predicate=predicate,
                         value=value, locator=Locator(sheet=sheet, cell=f"B{row}"), confidence=0.95)


def test_series_groups_are_domain_neutral():
    """A switchboard, not a plant: breakers in series, a named feeder group spelled out elsewhere."""
    claims = [
        _row("e1", "G1", "type", "Generator", "Equipment", 2),
        _row("e2", "L1", "type", "Load bank", "Equipment", 3),
        _row("e3", "CB1", "type", "Circuit breaker", "Equipment", 4),
        _row("e4", "CB2", "type", "Circuit breaker", "Equipment", 5),
        _row("e5", "CB3", "type", "Circuit breaker", "Equipment", 6),
        _row("i1", "IF-01", "from", "G1", "Interfaces", 2),
        _row("i2", "IF-01", "to", "CB1", "Interfaces", 2),
        _row("i3", "IF-01", "item_medium", "Electrical power", "Interfaces", 2),
        _row("i4", "IF-02", "from", "CB1", "Interfaces", 3),
        _row("i5", "IF-02", "to", "L1", "Interfaces", 3),
        _row("i6", "IF-02", "constraint_note", "Uses CB2 plus L1 feeder group", "Interfaces", 3),
        EvidenceClaim(id="n1", source_id="S2", kind="note", subject="old feeder", predicate="says",
                      value="G1 feeder -> CB1/CB2 + CB3 -> L1", quote="G1 feeder -> CB1/CB2 + CB3 -> L1"),
    ]
    m = build_model([], claims, precedence_config=PRECEDENCE)
    delivery = next(c for c in m.connections if c.target.startswith("L1."))
    assert delivery.series_elements == ["CB1", "CB2", "CB3"]
    assert m.block("CB1").abstracted_into is not None
    assert "electrical" in m.block(delivery.source.split(".")[0]).domains


# ------------------------------------------------------------------------------- B3 signals


def test_sensors_bind_to_parts_and_setpoints_follow_the_change_record(built):
    m = built
    assert m.signal("LIS_301").binding == "B3.level"
    assert m.signal("TIS_702").unit == "K"
    assert m.signal("FIS_801").binding is None, "a location that is not a part is not guessed at"
    b7 = next(p for p in m.parameters if p.id == "SP-B7-COOL")
    assert b7.quantity.value == pytest.approx(298.15) and b7.status == "effective"
    assert next(p for p in m.parameters if p.id == "SP-B7-COOL-OLD").status == "superseded"


# ---------------------------------------------------------------------------- B4 behaviour


def test_state_machine_has_three_regions_a_fork_and_a_join(built):
    sm = built.state_machines[0]
    assert sm.regions == ["main", "A", "B"]
    listed = {"Initial", "Step1", "Step2", "Step3", "Step4", "Step5", "Step6", "Step12", "Step13",
              "Step7", "Step8", "Step9", "Step10_11", "Join"}
    assert listed <= {s.id for s in sm.states}, "all 14 listed steps must survive"
    fork = next(t for t in sm.transitions if t.forks)
    assert fork.source_state == "Step6" and set(fork.forks) == {"Step12", "Step7"}
    join = next(t for t in sm.transitions if t.joins)
    assert join.guard == "in(DoneA) and in(DoneB)" and join.target_state == "Join"
    # 'Step9 -> Step10' must reach the merged 'Step10/11' row, not invent a second fork.
    assert any(t.source_state == "Step9" and t.target_state == "Step10_11" for t in sm.transitions)
    # 'P2=ON + return valve group' commands the pump's whole series group.
    assert set(sm.state("Step13").actions) == {"cmd_P2", "cmd_V20", "cmd_V24", "cmd_V25", "cmd_V1", "cmd_V3"}
    b7 = next(t for t in sm.transitions if t.source_state == "Step9")
    assert "SP_B7_COOL" in b7.guard and "OLD" not in b7.guard


def test_interlocks_are_merged_across_sources_and_traced(built):
    by_actuator: dict[str, list] = {}
    for il in built.interlocks:
        by_actuator.setdefault(il.actuator, []).append(il)
    assert [il.condition for il in by_actuator["cmd_P1"]] == ["LIS_701 > 0.02"]
    assert "REQ-SAF-003" in by_actuator["cmd_P1"][0].provenance.requirement_ids
    assert len(by_actuator["cmd_B5_Heater"]) == 2


def test_extracted_ir_validates_and_round_trips(built):
    report = validate(built)
    assert report.ok, "\n".join(str(f) for f in report.errors)
    assert not round_trip_check(built, SysMLEmitter(built).emit())


# ---------------------------------------------------------------------------- B5 scenario


def test_scenario_and_checks_come_from_the_evidence(built):
    sc = built.scenarios[0]
    assert (sc.id, sc.stop_time) == ("BAT-09", 3000.0)
    exprs = {c.expression for c in sc.checks}
    assert "crosses(B3.level, 0.13, rising)" in exprs
    assert "crosses(B7.T, 298.15, falling)" in exprs
    step1 = next(c for c in sc.checks if c.expression == "crosses(B3.level, 0.13, rising)")
    assert step1.requirement_ids == ["REQ-FUN-002"]


# -------------------------------------------------------------------- B3 guard reachability


def _store_model(receiver: Block, suppliers: list[Block], variable: str, threshold: float,
                 domain: str, via: Block | None = None, guard_op: str = ">=") -> SystemModel:
    blocks = [receiver, *suppliers] + ([via] if via else [])
    conns = []
    for s in suppliers:
        if via is None:
            conns.append(Connection(id=f"c_{s.id}", source=f"{s.id}.a", target=f"{receiver.id}.a", domain=domain))
        else:
            conns.append(Connection(id=f"c_{s.id}", source=f"{s.id}.a", target=f"{via.id}.a", domain=domain))
    if via is not None:
        conns.append(Connection(id="c_via", source=f"{via.id}.b", target=f"{receiver.id}.a", domain=domain))
    return SystemModel(
        name="probe", blocks=blocks, connections=conns,
        signals=[Signal(id="x", name="x", role="sensor", binding=f"{receiver.id}.{variable}")],
        state_machines=[StateMachine(id="sm", name="sm", states=[State(id="s0", name="s0", initial=True),
                                                                   State(id="s1", name="s1")],
                                     transitions=[Transition(id="t", source_state="s0", target_state="s1",
                                                             guard=f"x {guard_op} {threshold}")])],
    )


def _blk(bid: str, **params: float) -> Block:
    return Block(id=bid, name=bid, kind="store",
                 ports=[Port(id="a", name="a"), Port(id="b", name="b")],
                 parameters=[Parameter(id=f"{bid}.{k}", name=k, quantity=Quantity(value=v)) for k, v in params.items()])


def _warns(m: SystemModel) -> list[str]:
    r = ValidationReport()
    check_guard_reachability(m, r)
    return [f.message for f in r.findings if f.check == "guard-reachability"]


def test_supply_ceiling_covers_charge():
    # 5 mC can at most lift a 1 mF capacitor to 5 V, whatever the circuit does.
    c2 = _blk("C2", C=1e-3, v_start=0.0)
    c1 = _blk("C1", C=1e-3, v_start=5.0)
    r1 = _blk("R1")
    assert _supply_ceiling(_store_model(c2, [c1], "v", 4.0, "electrical", via=r1), "C2", "v") == pytest.approx(5.0)
    assert not _warns(_store_model(c2, [c1], "v", 4.0, "electrical", via=r1))
    assert _warns(_store_model(c2, [c1], "v", 6.0, "electrical", via=r1))


def test_supply_ceiling_covers_rotational_energy():
    # A 2 kg.m2 flywheel at 10 rad/s holds 100 J: an equal flywheel can never exceed 10 rad/s.
    f2 = _blk("F2", J=2.0, w_start=0.0)
    f1 = _blk("F1", J=2.0, w_start=10.0)
    clutch = _blk("K")
    assert not _warns(_store_model(f2, [f1], "w", 9.0, "rotational", via=clutch))
    assert _warns(_store_model(f2, [f1], "w", 12.0, "rotational", via=clutch))


def test_supply_ceiling_never_claims_what_it_cannot_prove():
    tank = _blk("T2", area=1.0, level_start=0.0)
    unknown = _blk("SRC")                       # an origin of unknown size
    assert _supply_ceiling(_store_model(tank, [unknown], "level", 5.0, "fluid"), "T2", "level") is None
    full = _blk("T1", area=1.0, level_start=1.0)
    assert _warns(_store_model(tank, [full], "level", 2.0, "fluid"))
    alt = _store_model(tank, [full], "level", 2.0, "fluid")
    alt.state_machines[0].transitions[0].guard = "x >= 2.0 or time > 100"
    assert not _warns(alt), "a guard with an alternative exit can still fire"


def test_reference_ir_stays_clean_under_the_generalised_check():
    m = SystemModel.model_validate_json(REF_IR.read_text(encoding="utf-8"))
    assert not _warns(m)


# ------------------------------------------------------------------------- B4/B5 SysML


@pytest.fixture(scope="module")
def reference() -> SystemModel:
    return SystemModel.model_validate_json(REF_IR.read_text(encoding="utf-8"))


def test_satisfy_and_verify_are_first_class(reference):
    text = SysMLEmitter(reference).emit()
    assert "satisfy REQ_FUN_002 by NaClEvaporationPlantSystem.ctrl;" in text
    parsed = parse_back(text)
    assert ("BAT09_01", "REQ_FUN_002") in parsed.verifies
    assert ("BAT_09", "REQ_VV_001") in parsed.verifies
    assert ("ctrl", "BatchController") in parsed.exhibits
    assert "// @trace" not in text, "traceability is a relationship now, not a comment"


def test_round_trip_notices_a_lost_relationship(reference):
    text = SysMLEmitter(reference).emit()
    dropped = "\n".join(line for line in text.splitlines()
                        if not line.strip().startswith("satisfy REQ_SAF_003 "))
    assert any("REQ-SAF-003" in p for p in round_trip_check(reference, dropped))


def test_parse_back_rejects_what_it_does_not_understand(reference):
    """B5: a construct the emitter learns but parse_back does not is reported, not skipped."""
    text = SysMLEmitter(reference).emit()
    assert not parse_back(text).unparsed
    stale = text.replace("}\n", "    perform action startCycle;\n}\n", 1)
    assert parse_back(stale).unparsed == ["perform action startCycle;"]
    assert round_trip_check(reference, stale)


def test_part_defs_declare_the_ports_of_every_block_of_their_kind(built):
    parsed = parse_back(SysMLEmitter(built).emit())
    b3 = built.block("B3")
    assert b3.kind == built.block("B1").kind, "the case this test exists for: siblings of one kind"
    for p in b3.ports:
        assert (b3.kind, p.name) in parsed.part_def_ports
