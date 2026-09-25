"""Structural repair: correcting the IR when no edit to the .mo could have worked.

Own file, same reason as test_agentic.py: appends to test_specalive.py cost merge conflicts.

Everything here runs offline against a hand-built IR. The fixture is the shape that actually
broke us -- a chain whose interior vessels arrived flagged architecture-only and whose
boundaries never bound -- because the failure this module exists for is not hypothetical:

    SRC_101 -> V1 -> TK_101 -> V2 -> TK_102 -> V3 -> DRN_101
                     ^^^^^^          ^^^^^^
                     physical_only, so the emitter skips them and the system is
                     under-determined by exactly the equations they would have supplied

The controller hangs off the side with inbound edges only, and must survive untouched: it is
realised by a state machine, not a component, and materialising it would be a regression
dressed up as a fix.
"""

from __future__ import annotations

import types

from specalive.ir.system import Block, Connection, Port, SystemModel
from specalive.repair.structural import (
    _connector_families,
    candidates,
    interior_architecture_blocks,
    plan_structural_repair,
    unbound_blocks,
)
from specalive.repair.writeback import IREdit, apply_ir_edits


# --------------------------------------------------------------------------------- fixtures


class FakePort:
    def __init__(self, name: str, type_: str) -> None:
        self.name, self.type = name, type_


class FakeParam:
    def __init__(self, name: str) -> None:
        self.name, self.unit = name, None


class FakeEntry:
    def __init__(self, key, library, ports, params=(), comment="", restriction="model"):
        self.key, self.library, self.restriction, self.comment = key, library, restriction, comment
        self.ports = [FakePort(n, t) for n, t in ports]
        self.params = [FakeParam(p) for p in params]
        self.domain = "fluid"
        self.aliases: list[str] = []


class FakeIndex:
    """Two libraries: a small in-house one and enough MSL-alikes to make the share test bite."""

    def __init__(self) -> None:
        I = "Demo.Interfaces"
        S = "Modelica.Blocks.Interfaces"
        self.entries = [
            FakeEntry("Demo.Vessels.Tank", "Demo", [("inlet", f"{I}.Inlet"), ("outlet", f"{I}.Outlet")],
                      ["area", "level_start"], "A vessel with an inlet and an outlet"),
            FakeEntry("Demo.Transport.Valve", "Demo",
                      [("port_a", f"{I}.Suction"), ("port_b", f"{I}.Discharge"), ("open", f"{S}.BooleanInput")],
                      ["m_flow_nominal"], "Commanded transfer path"),
            FakeEntry("Demo.Sources.Supply", "Demo", [("outlet", f"{I}.Outlet")], [], "Fixed supply"),
            FakeEntry("Demo.Sources.Drain", "Demo", [("inlet", f"{I}.Inlet")], [], "Drain to ambient"),
        ]
        # Enough signal-only classes that Modelica.Blocks.Interfaces is on >20% of the
        # catalog and is therefore measured as non-discriminating, exactly as in the real one.
        for i in range(12):
            self.entries.append(
                FakeEntry(f"Modelica.Blocks.Math.Op{i}", "Modelica",
                          [("u", f"{S}.RealInput"), ("y", f"{S}.RealOutput")], [], "A maths block")
            )

    def get(self, key):
        return next((e for e in self.entries if e.key == key), None)

    def search(self, query, *, k=12, domain=None, restriction=None, library=None):
        hits = [e for e in self.entries if library is None or e.library == library]
        return [types.SimpleNamespace(entry=e, score=1.0, why="fake") for e in hits[:k]]


def _port(pid: str) -> Port:
    return Port(id=pid, name=pid, domain="fluid", direction="acausal")


def chain_model() -> SystemModel:
    """SRC -> V1 -> TK_101 -> V2 -> TK_102 -> V3 -> DRN, plus a controller off to the side."""

    def blk(bid, kind, ports, *, phys=False, cls=None):
        b = Block(id=bid, name=bid, kind=kind, domains=["fluid"], ports=[_port(p) for p in ports])
        b.physical_only = phys
        if cls:
            b.modelica_class, b.binding_tier = cls, "L0"
        return b

    blocks = [
        blk("SRC_101", "Boundary source", ["port_out"]),
        blk("V1", "transfer path", ["port_a", "port_b"], cls="Demo.Transport.Valve"),
        blk("TK_101", "external boundary", ["port_in", "port_out"], phys=True),
        blk("V2", "transfer path", ["port_a", "port_b"], cls="Demo.Transport.Valve"),
        blk("TK_102", "external boundary", ["port_in", "port_out"], phys=True),
        blk("V3", "transfer path", ["port_a", "port_b"], cls="Demo.Transport.Valve"),
        blk("DRN_101", "Boundary sink", ["port_in"]),
        blk("PLC", "external boundary", ["port_in"], phys=True),
        blk("LT_101", "Level transmitter", ["port_out"]),
    ]
    conns = [
        ("SRC_101.port_out", "V1.port_a"),
        ("V1.port_b", "TK_101.port_in"),
        ("TK_101.port_out", "V2.port_a"),
        ("V2.port_b", "TK_102.port_in"),
        ("TK_102.port_out", "V3.port_a"),
        ("V3.port_b", "DRN_101.port_in"),
        ("LT_101.port_out", "PLC.port_in"),
    ]
    return SystemModel(
        name="Chain",
        blocks=blocks,
        connections=[
            Connection(id=f"C{i}", source=s, target=t, domain="fluid")
            for i, (s, t) in enumerate(conns)
        ],
    )


class Picker:
    """A router that binds whatever it is asked about, to the first candidate offered."""

    def __init__(self, choices: dict[str, str]) -> None:
        self.choices, self.calls, self.prompts = choices, 0, []

    def run(self, task, prompt, schema=None, validator=None):
        self.calls += 1
        self.prompts.append(prompt)
        data = {
            "decisions": [
                {"block": b, "action": "bind", "modelica_class": c, "reason": "test"}
                for b, c in self.choices.items()
                if f"### {b}" in prompt
            ]
        }
        if validator is not None:
            ok, why = validator(data)
            assert ok, why
        return types.SimpleNamespace(data=data)


# ----------------------------------------------------------------- the deterministic stage


def test_interior_nodes_are_found_and_terminals_are_left_alone():
    """The graph rule, which is the whole deterministic stage.

    Both tanks are traversed by the executable model and must come back. The controller is a
    terminal -- inbound only -- and must not, because nothing on the flow path depends on it
    existing as a component and binding it to one would invent a plant the evidence never
    described.
    """
    m = chain_model()
    found = {b.id for b in interior_architecture_blocks(m)}
    assert found == {"TK_101", "TK_102"}
    assert "PLC" not in found


def test_materialising_needs_a_simulatable_neighbour_on_each_side():
    """A vessel with nothing downstream is a terminal, however vessel-shaped it looks.

    Cutting only `TK_101 -> V2` leaves TK_101 fed but feeding nothing, while TK_102 keeps a
    live neighbour on both sides. One drops out of the rule and the other does not, which is
    the discrimination the rule exists to make.
    """
    m = chain_model()
    m.connections = [c for c in m.connections if c.source != "TK_101.port_out"]
    assert {b.id for b in interior_architecture_blocks(m)} == {"TK_102"}


def test_deterministic_stage_runs_without_a_router():
    """`--provider none` must still reach the correct structural verdict and spend nothing."""
    m = chain_model()
    plan = plan_structural_repair(m, "under-determined", index=FakeIndex(), router=None)
    assert [e.kind for e in plan.edits] == ["materialise", "materialise"]
    assert plan.method == "deterministic"
    # Everything it could not bind is declared, not quietly dropped.
    assert {g.subject for g in plan.gaps} >= {"SRC_101", "DRN_101", "TK_101", "TK_102"}
    assert all(g.severity == "blocking" for g in plan.gaps)


# ------------------------------------------------------------------------- candidate search


def test_generic_connector_families_are_ignored():
    """A connector package on most of the catalog cannot discriminate, so it is dropped.

    Without this the valve's BooleanInput matches every signal block in the library and the
    shortlist fills with maths operators instead of vessels.
    """
    m, idx = chain_model(), FakeIndex()
    fams = _connector_families(m, m.block("TK_101"), idx)
    assert "Demo.Interfaces" in fams
    assert "Modelica.Blocks.Interfaces" not in fams


def test_shortlist_contains_the_right_class_despite_a_wrong_stated_kind():
    """`TK_101` is filed as an 'external boundary'. The graph says otherwise, and wins."""
    m, idx = chain_model(), FakeIndex()
    keys = [e.key for e in candidates(m, m.block("TK_101"), idx)]
    assert "Demo.Vessels.Tank" in keys
    assert keys.index("Demo.Vessels.Tank") < len(keys)


def test_a_block_with_no_bound_neighbour_is_not_offered_to_the_model():
    """No graph signal means the shortlist would be lexical noise, so we do not build one.

    LT_101 connects only to the controller, which is not a component. Offering a list whose
    right answer is absent invites a confident wrong bind -- and one that compiles.
    """
    m, idx = chain_model(), FakeIndex()
    assert candidates(m, m.block("LT_101"), idx) == []


def test_ungrounded_blocks_cost_no_model_call_and_say_why():
    m, idx = chain_model(), FakeIndex()
    picker = Picker({"TK_101": "Demo.Vessels.Tank"})
    plan = plan_structural_repair(m, "under-determined", index=idx, router=picker)
    lt = next(g for g in plan.gaps if g.subject == "LT_101")
    assert "no model call was made" in lt.detail.lower()
    assert "LT_101" not in "".join(picker.prompts).split("BLOCKS")[-1].split("###")[0]


# -------------------------------------------------------------------------- the agent stage


def test_one_call_settles_every_unresolved_block():
    """Token cost must not scale with how broken the packet is."""
    m, idx = chain_model(), FakeIndex()
    picker = Picker(
        {
            "TK_101": "Demo.Vessels.Tank",
            "TK_102": "Demo.Vessels.Tank",
            "SRC_101": "Demo.Sources.Supply",
            "DRN_101": "Demo.Sources.Drain",
        }
    )
    plan = plan_structural_repair(m, "under-determined", index=idx, router=picker)
    assert picker.calls == 1
    assert plan.method == "both"
    binds = {e.block: e.new for e in plan.edits if e.kind == "bind"}
    assert binds == {
        "TK_101": "Demo.Vessels.Tank",
        "TK_102": "Demo.Vessels.Tank",
        "SRC_101": "Demo.Sources.Supply",
        "DRN_101": "Demo.Sources.Drain",
    }


def test_an_invented_class_is_rejected_rather_than_applied():
    """The check that makes 'it cannot name a class that does not exist' literally true."""
    m, idx = chain_model(), FakeIndex()
    seen: dict[str, tuple[bool, str]] = {}

    class Liar:
        def run(self, task, prompt, schema=None, validator=None):
            seen["invented"] = validator(
                {"decisions": [{"block": "TK_101", "action": "bind",
                                "modelica_class": "Demo.Vessels.Imaginary", "reason": "x"}]}
            )
            seen["unknown"] = validator(
                {"decisions": [{"block": "NOPE", "action": "bind",
                                "modelica_class": "Demo.Vessels.Tank", "reason": "x"}]}
            )
            return types.SimpleNamespace(data={"decisions": []})

    plan_structural_repair(m, "under-determined", index=idx, router=Liar())
    assert seen["invented"][0] is False and "candidate list" in seen["invented"][1]
    assert seen["unknown"][0] is False


def test_declining_produces_a_gap_not_a_guess():
    m, idx = chain_model(), FakeIndex()

    class Decliner:
        def run(self, task, prompt, schema=None, validator=None):
            return types.SimpleNamespace(
                data={"decisions": [{"block": "TK_101", "action": "decline",
                                     "reason": "nothing offered fits"}]}
            )

    plan = plan_structural_repair(m, "under-determined", index=idx, router=Decliner())
    assert not [e for e in plan.edits if e.kind == "bind"]
    assert any(g.subject == "TK_101" for g in plan.gaps)


def test_a_dead_router_degrades_to_declared_gaps():
    """A quota outage must not read as 'this block is unbindable'."""
    m, idx = chain_model(), FakeIndex()

    class Dead:
        def run(self, *a, **k):
            raise RuntimeError("quota exhausted")

    plan = plan_structural_repair(m, "under-determined", index=idx, router=Dead())
    assert [e.kind for e in plan.edits] == ["materialise", "materialise"]
    assert any("unavailable" in n for n in plan.notes)


# ------------------------------------------------------------------------------- write-back


def test_edits_land_on_the_ir():
    m = chain_model()
    landed = apply_ir_edits(
        m,
        [
            IREdit(kind="materialise", old="physical_only", new="simulatable", block="TK_101", detail="d"),
            IREdit(kind="bind", old="unbound", new="Demo.Vessels.Tank", block="TK_101", detail="d"),
        ],
    )
    tk = m.block("TK_101")
    assert len(landed) == 2
    assert tk.physical_only is False
    assert tk.modelica_class == "Demo.Vessels.Tank"
    assert tk.binding_tier == "L0"
    assert tk in m.simulatable_blocks()


def test_a_bind_never_overwrites_a_binding_the_cascade_already_made():
    """Structural repair fills holes. The cascade saw evidence this stage does not."""
    m = chain_model()
    before = m.block("V1").modelica_class
    landed = apply_ir_edits(
        m, [IREdit(kind="bind", old="unbound", new="Demo.Sources.Drain", block="V1", detail="d")]
    )
    assert landed == []
    assert m.block("V1").modelica_class == before


def test_replaying_the_same_edit_is_harmless():
    """The pipeline dedupes by string, but a second application must still be a no-op.

    This is what bounds the rebuild loop: an edit that has already landed cannot land again
    and so cannot ask for another pass.
    """
    m = chain_model()
    edit = IREdit(kind="materialise", old="physical_only", new="simulatable", block="TK_101", detail="d")
    assert apply_ir_edits(m, [edit]) != []
    assert apply_ir_edits(m, [edit]) == []


def test_materialised_blocks_are_offered_for_binding_in_the_same_pass():
    """Both halves of the repair decided together, so one rebuild is enough for both."""
    m = chain_model()
    mat = {b.id for b in interior_architecture_blocks(m)}
    pending = {b.id for b in unbound_blocks(m, extra_live=mat)}
    assert {"TK_101", "TK_102"} <= pending
    assert "PLC" not in pending
