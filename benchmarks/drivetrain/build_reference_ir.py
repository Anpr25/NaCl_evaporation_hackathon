"""Reference IR for the geared drive bench — the generality proof.

This packet exists to answer one question: is SpecAlive actually domain-general, or is it
NaCl-shaped? It shares nothing with the evaporation packet:

  * a different physical domain (rotational mechanics, not fluid/thermal)
  * a different connector kind (acausal Flange_a/Flange_b, not our causal stream ports)
  * no state machine at all -- this is continuous-only, exercising a path the NaCl fixture
    never touches
  * and crucially, **every block must bind at L0**, against the harvested Modelica catalog.
    Not one SpecAlive template is involved. If this compiles and simulates, the catalog
    grounding works on a domain nobody designed for.

It also carries its own precedence trap, in a different shape from CR-017: the archived
model says the gear ratio is 4.0, an approved change record says 5.0.

Run:  python benchmarks/drivetrain/build_reference_ir.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from specalive.ir.evidence import DecisionRecord  # noqa: E402
from specalive.ir.system import (  # noqa: E402
    AcceptanceCheck,
    Block,
    Connection,
    Parameter,
    Port,
    Provenance,
    Quantity,
    Requirement,
    Scenario,
    SystemModel,
)

P = Provenance
ROT = "Modelica.Mechanics.Rotational"


def q(v, u=None):
    return Quantity(value=v, unit=u)


def flange(pid: str, name: str, direction: str = "acausal") -> Port:
    return Port(id=pid, name=name, domain="rotational", direction=direction)


# tag, name, kind, modelica class, params, ports
BLOCKS = [
    ("M1", "Torque source", "constant torque drive",
     f"{ROT}.Sources.ConstantTorque",
     {"tau_constant": 2.0, "useSupport": False},
     [("flange", "flange")]),
    ("J1", "Motor inertia", "rotational inertia",
     f"{ROT}.Components.Inertia",
     {"J": 0.02},
     [("flange_a", "flange_a"), ("flange_b", "flange_b")]),
    ("G1", "Reduction gear", "ideal rotational gear",
     f"{ROT}.Components.IdealGear",
     {"ratio": 5.0, "useSupport": False},
     [("flange_a", "flange_a"), ("flange_b", "flange_b")]),
    ("J2", "Load inertia", "rotational inertia",
     f"{ROT}.Components.Inertia",
     {"J": 0.35},
     [("flange_a", "flange_a"), ("flange_b", "flange_b")]),
    ("D1", "Viscous damper", "rotational damper",
     f"{ROT}.Components.Damper",
     {"d": 0.8},
     [("flange_a", "flange_a"), ("flange_b", "flange_b")]),
    ("F1", "Frame", "mechanical ground",
     f"{ROT}.Components.Fixed",
     {"phi0": 0.0},
     [("flange", "flange")]),
]

CONNECTIONS = [
    ("C1", "M1.flange", "J1.flange_a", "shaft torque"),
    ("C2", "J1.flange_b", "G1.flange_a", "motor shaft"),
    ("C3", "G1.flange_b", "J2.flange_a", "output shaft"),
    ("C4", "J2.flange_b", "D1.flange_a", "load shaft"),
    ("C5", "D1.flange_b", "F1.flange", "reaction to frame"),
]

REQUIREMENTS = [
    ("REQ-DRV-001", "The rig shall drive a load-side inertia through a single-stage reduction gear.", "active", None),
    ("REQ-DRV-002", "The applied torque shall be 2.0 N.m, constant from t = 0.", "active", None),
    ("REQ-DRV-003", "The reduction ratio shall be 4.0.", "superseded", "CR-114"),
    ("REQ-DRV-004", "The reduction ratio shall be 5.0.", "active", None),
    ("REQ-DRV-005", "Parasitic load shall be modelled as linear viscous damping of 0.8 N.m.s/rad.", "active", None),
    ("REQ-DRV-006", "The damper shall react against a fixed mechanical ground.", "active", None),
    ("REQ-VV-010", "The load-side speed shall settle at 12.5 rad/s within 2%.", "active", None),
    ("REQ-VV-011", "The load-side speed shall not overshoot 13.0 rad/s.", "active", None),
    ("REQ-VV-012", "The motor-side speed shall be the ratio multiple of the load-side speed.", "active", None),
]

# Steady state: the gear multiplies motor torque by the ratio, and the damper balances it.
#   w_load = ratio * tau / d = 5.0 * 2.0 / 0.8 = 12.5 rad/s
#   w_motor = ratio * w_load = 62.5 rad/s
CHECKS = [
    ("AT22-01", "Load spins up past 12.0 rad/s",
     "crosses(J2.w, 12.0, rising)", ["REQ-VV-010"]),
    ("AT22-02", "Load-side speed settles at 12.5 rad/s within 2%",
     "final(J2.w) >= 12.25", ["REQ-VV-010", "REQ-DRV-004"]),
    ("AT22-03", "Load-side speed does not exceed the 2% upper band",
     "final(J2.w) <= 12.75", ["REQ-VV-010"]),
    ("AT22-04", "No overshoot above 13.0 rad/s",
     "always(J2.w <= 13.0)", ["REQ-VV-011"]),
    ("AT22-05", "Load-side speed is never negative",
     "always(J2.w >= 0.0)", []),
    ("AT22-06", "Motor-side speed reaches 5x the load-side speed",
     "final(J1.w) >= 62.0", ["REQ-VV-012", "REQ-DRV-004"]),
    ("AT22-07", "Motor-side speed does not exceed 5x plus tolerance",
     "final(J1.w) <= 63.0", ["REQ-VV-012"]),
]


def build() -> SystemModel:
    m = SystemModel(
        name="GearedDriveBench",
        description="Constant-torque drive through a reduction gear into a damped load inertia",
        domains=["rotational"],
    )

    m.parameters = [
        Parameter(id="P-M1-TAU", name="tau_constant", quantity=q(2.0, "N.m"), scope="M1",
                  description="Applied constant torque", provenance=P(requirement_ids=["REQ-DRV-002"])),
        Parameter(id="P-J1-INERTIA", name="J", quantity=q(0.02, "kg.m2"), scope="J1",
                  description="Motor-side inertia"),
        Parameter(id="P-G1-RATIO-OLD", name="ratio", quantity=q(4.0, "1"), scope="G1",
                  description="Reduction ratio (prototype gearbox)", status="superseded",
                  provenance=P(requirement_ids=["REQ-DRV-003"])),
        Parameter(id="P-G1-RATIO", name="ratio", quantity=q(5.0, "1"), scope="G1",
                  description="Reduction ratio", provenance=P(requirement_ids=["REQ-DRV-004"])),
        Parameter(id="P-J2-INERTIA", name="J", quantity=q(0.35, "kg.m2"), scope="J2",
                  description="Load-side inertia"),
        Parameter(id="P-D1-DAMPING", name="d", quantity=q(0.8, "N.m.s/rad"), scope="D1",
                  description="Viscous damping coefficient",
                  provenance=P(requirement_ids=["REQ-DRV-005"])),
    ]

    req_for = {
        "M1": ["REQ-DRV-002"], "G1": ["REQ-DRV-004"], "D1": ["REQ-DRV-005"],
        "F1": ["REQ-DRV-006"], "J2": ["REQ-DRV-001"],
    }
    for tag, name, kind, cls, params, ports in BLOCKS:
        m.blocks.append(
            Block(
                id=tag, name=name, kind=kind, domains=["rotational"],
                ports=[flange(pid, pname) for pid, pname in ports],
                parameters=[
                    Parameter(id=f"{tag}.{k}", name=k, quantity=q(v)) for k, v in params.items()
                ],
                description=name,
                # Pre-bound to catalog classes: every one is L0, no SpecAlive template.
                binding_tier="L0",
                modelica_class=cls,
                modelica_modifiers={
                    k: ("true" if v is True else "false" if v is False else repr(v))
                    for k, v in params.items()
                },
                binding_rationale="harvested catalog class, verified ports and parameters",
                provenance=P(requirement_ids=req_for.get(tag, [])),
            )
        )

    for cid, src, tgt, medium in CONNECTIONS:
        m.connections.append(
            Connection(id=cid, source=src, target=tgt, domain="rotational", medium=medium,
                       provenance=P(requirement_ids=["REQ-DRV-001"]))
        )

    m.requirements = [
        Requirement(id=r, text=t, status=st, superseded_by=sb, priority="must",
                    provenance=P(note="Rig datasheet / AT-22"))
        for r, t, st, sb in REQUIREMENTS
    ]

    m.scenarios = [
        Scenario(id="AT-22", name="AT22", stop_time=20.0, interval=0.02, tolerance=1e-6,
                 solver="dassl",
                 checks=[AcceptanceCheck(id=c, description=d, expression=e, requirement_ids=rq)
                         for c, d, e, rq in CHECKS],
                 provenance=P(requirement_ids=["REQ-VV-010", "REQ-VV-011", "REQ-VV-012"]))
    ]

    m.decisions = [
        DecisionRecord(
            id="DEC-DRV-01", subject="G1", predicate="ratio",
            winner_claim_id="CLM-CR-114", loser_claim_ids=["CLM-LEGACY-RIG"],
            rule_id="P1-explicit-supersession",
            rationale="CR-114 (approved, 2026-04-18) sets the G1 reduction ratio to 5.0 and "
                      "explicitly supersedes the 4.0 value carried in the archived simulation "
                      "model, which was taken from a prototype gearbox that was never fitted.",
            failure_mode="F1-recency-bias",
        ),
    ]

    # Link satisfaction the same way the NaCl fixture does.
    index: dict[str, list[str]] = {}
    for coll in (m.blocks, m.connections):
        for el in coll:
            for rid in el.provenance.requirement_ids:
                index.setdefault(rid, []).append(el.id)
    for c in m.scenarios[0].checks:
        for rid in c.requirement_ids:
            index.setdefault(rid, []).append(c.id)
    for r in m.requirements:
        r.satisfied_by = sorted(set(index.get(r.id, [])))

    return m


if __name__ == "__main__":
    model = build()
    out = Path(__file__).with_name("reference_ir.json")
    out.write_text(model.model_dump_json(indent=2), encoding="utf-8")
    cov = model.coverage()
    print(f"wrote {out}")
    for k in ("blocks", "connections", "requirements_active", "requirements_satisfied",
              "binding_tiers"):
        print(f"  {k:26s} {cov[k]}")
