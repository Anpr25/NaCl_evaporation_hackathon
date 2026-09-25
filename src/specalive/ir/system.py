"""The domain-agnostic SystemModel IR.

Everything upstream (ingest, extract, reconcile) produces one of these. Everything downstream
(SysML emitter, Modelica emitter, verification, report) consumes one. Nothing in here mentions
tanks, valves, resistors or gearboxes: the IR describes *blocks with typed ports*, a
*connection graph*, *behaviour*, and *requirements*, which is enough for any physical domain.

FROZEN CONTRACT -- coordinate any change across all four workstreams.
Owner: B.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .evidence import Assumption, DecisionRecord, EvidenceClaim, Gap, Question, Source

SCHEMA_VERSION = "1.0.0"

Domain = Literal[
    "fluid",
    "thermal",
    "electrical",
    "magnetic",
    "translational",
    "rotational",
    "multibody",
    "chemical",
    "signal",
    "control",
    "logical",
    "unknown",
]

PortDirection = Literal["in", "out", "inout", "acausal"]


class Provenance(BaseModel):
    """Attached to every IR element. Empty provenance is a bug, not a style choice."""

    claim_ids: list[str] = Field(default_factory=list)
    decision_ids: list[str] = Field(default_factory=list)
    requirement_ids: list[str] = Field(default_factory=list)
    note: str | None = None


class Quantity(BaseModel):
    """A value with a unit. Keep SI base units internally; `display_unit` is cosmetic."""

    value: float | int | bool | str | None = None
    unit: str | None = None
    display_unit: str | None = None
    tolerance: float | None = None

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return f"{self.value}{' ' + self.unit if self.unit else ''}"


class Requirement(BaseModel):
    id: str
    text: str
    category: str | None = None
    priority: Literal["must", "should", "may", "unknown"] = "unknown"
    status: Literal["active", "superseded", "proposed", "unknown"] = "active"
    superseded_by: str | None = None
    authority: str | None = None
    verification_method: str | None = None
    #: IR element ids that satisfy this requirement. Filled by the emitters, read by the report.
    satisfied_by: list[str] = Field(default_factory=list)
    verified_by: list[str] = Field(default_factory=list)
    provenance: Provenance = Field(default_factory=Provenance)


class Parameter(BaseModel):
    id: str
    name: str
    quantity: Quantity
    scope: str | None = Field(default=None, description="Block id or 'global'")
    description: str | None = None
    status: Literal["effective", "superseded", "provisional"] = "effective"
    provenance: Provenance = Field(default_factory=Provenance)


class Port(BaseModel):
    id: str
    name: str
    domain: Domain = "unknown"
    direction: PortDirection = "acausal"
    #: Modelica connector class once bound, e.g. "Modelica.Electrical.Analog.Interfaces.Pin".
    connector_type: str | None = None
    multiplicity: int = 1
    description: str | None = None
    provenance: Provenance = Field(default_factory=Provenance)


class Block(BaseModel):
    """Any part of the system: a vessel, a resistor, a gearbox, a controller, a heat exchanger."""

    id: str
    name: str
    kind: str = Field(description="Free-text type from the source, e.g. 'evaporator vessel'")
    domains: list[Domain] = Field(default_factory=lambda: ["unknown"])
    ports: list[Port] = Field(default_factory=list)
    parameters: list[Parameter] = Field(default_factory=list)
    description: str | None = None

    #: --- binding, filled by the Modelica emitter's tier cascade (owner C) -----------------
    binding_tier: Literal["L0", "L1", "L2", "unbound"] = "unbound"
    modelica_class: str | None = Field(
        default=None, description="L0: a harvested catalog class. L1: a SpecAlive template."
    )
    modelica_modifiers: dict[str, str] = Field(default_factory=dict)
    synthesised_equations: str | None = Field(
        default=None, description="L2 only: model body authored under a fixed port skeleton"
    )
    binding_rationale: str | None = None

    #: True when the source merges this part into another for simulation but the part exists
    #: physically. Keeps architecture honest without distorting the executable model.
    abstracted_into: str | None = None

    physical_only: bool = Field(
        default=False, description="Present in the architecture, not in the executable model"
    )
    provenance: Provenance = Field(default_factory=Provenance)


class Connection(BaseModel):
    id: str
    source: str = Field(description="'<block_id>.<port_id>'")
    target: str = Field(description="'<block_id>.<port_id>'")
    domain: Domain = "unknown"
    medium: str | None = None
    #: Ordered element ids (valves, breakers, couplings) that sit in series on this connection.
    #: The Modelica emitter lowers a series group to one commanded element; SysML keeps them all.
    series_elements: list[str] = Field(default_factory=list)
    description: str | None = None
    provenance: Provenance = Field(default_factory=Provenance)

    def endpoints(self) -> tuple[tuple[str, str], tuple[str, str]]:
        (sb, _, sp) = self.source.partition(".")
        (tb, _, tp) = self.target.partition(".")
        return (sb, sp), (tb, tp)


class Signal(BaseModel):
    """A sensor reading or an actuator command, and what it is bound to in the plant."""

    id: str
    name: str
    role: Literal["sensor", "actuator"]
    datatype: Literal["real", "boolean", "integer"] = "real"
    unit: str | None = None
    #: Dotted path into the plant, e.g. "B3.level" or "motor.flange_b.tau".
    binding: str | None = None
    owner: Literal["controller", "manual", "monitoring", "unknown"] = "unknown"
    range: tuple[float, float] | None = None
    provenance: Provenance = Field(default_factory=Provenance)


class Transition(BaseModel):
    id: str
    source_state: str
    target_state: str
    guard: str = Field(description="Boolean expression over signal ids and parameter ids")
    effect: str | None = None

    #: True when this transition is not in the customer's specification: it is a declared
    #: fallback added under SA-05 because the specified guard was *proved* unreachable and the
    #: sequence would otherwise deadlock. The specified transition is always kept exactly as
    #: written and evaluated first; this one only catches what it cannot.
    declared_fallback: bool = False
    fallback_for: str | None = Field(
        default=None, description="Id of the specified transition this one backs up"
    )
    #: Seconds in the source state after which a declared fallback fires. Derived from how
    #: long the quantity actually took to reach its limit in the trace, not picked.
    dwell_timeout: float | None = None
    #: For a split: the region states entered concurrently. For a join: the states awaited.
    forks: list[str] = Field(default_factory=list)
    joins: list[str] = Field(default_factory=list)
    provenance: Provenance = Field(default_factory=Provenance)


class State(BaseModel):
    id: str
    name: str
    region: str = "main"
    initial: bool = False
    final: bool = False
    #: signal id -> expression, applied while the state is active.
    actions: dict[str, str] = Field(default_factory=dict)
    description: str | None = None
    provenance: Provenance = Field(default_factory=Provenance)


class StateMachine(BaseModel):
    id: str
    name: str
    regions: list[str] = Field(default_factory=lambda: ["main"])
    states: list[State] = Field(default_factory=list)
    transitions: list[Transition] = Field(default_factory=list)
    scan_period: float = Field(default=0.1, description="Seconds; the emitter lowers to sample()")
    provenance: Provenance = Field(default_factory=Provenance)

    def state(self, sid: str) -> State | None:
        return next((s for s in self.states if s.id == sid), None)

    def states_in(self, region: str) -> list[State]:
        return [s for s in self.states if s.region == region]


class Interlock(BaseModel):
    """A permissive or inhibit that gates an actuator regardless of sequence position."""

    id: str
    actuator: str
    condition: str
    sense: Literal["permissive", "inhibit"] = "permissive"
    provenance: Provenance = Field(default_factory=Provenance)


class AcceptanceCheck(BaseModel):
    """One machine-checkable acceptance criterion, lifted from the test procedure."""

    id: str
    description: str
    kind: Literal["threshold", "ordering", "final_value", "invariant", "routing"] = "threshold"
    expression: str = Field(description="Evaluated against the simulation result frame")
    tolerance: float | None = None
    requirement_ids: list[str] = Field(default_factory=list)
    provenance: Provenance = Field(default_factory=Provenance)


class Scenario(BaseModel):
    id: str
    name: str
    stop_time: float = 10.0
    interval: float | None = None
    tolerance: float = 1e-6
    solver: str = "dassl"
    initial_conditions: dict[str, Quantity] = Field(default_factory=dict)
    inputs: dict[str, str] = Field(default_factory=dict)
    checks: list[AcceptanceCheck] = Field(default_factory=list)
    provenance: Provenance = Field(default_factory=Provenance)


class SystemModel(BaseModel):
    """The whole extracted system. This is what gets serialised to out/ir.json."""

    schema_version: str = SCHEMA_VERSION
    name: str
    description: str | None = None
    domains: list[Domain] = Field(default_factory=lambda: ["unknown"])

    sources: list[Source] = Field(default_factory=list)
    claims: list[EvidenceClaim] = Field(default_factory=list)
    decisions: list[DecisionRecord] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)
    #: The brief requires missing information to be "inferred with a stated assumption, or
    #: surfaced as a question". These are those two, kept apart from `gaps` so a reviewer can
    #: find what we invented and what we are asking without reading every warning.
    assumptions: list[Assumption] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list)

    requirements: list[Requirement] = Field(default_factory=list)
    parameters: list[Parameter] = Field(default_factory=list)
    blocks: list[Block] = Field(default_factory=list)
    connections: list[Connection] = Field(default_factory=list)
    signals: list[Signal] = Field(default_factory=list)
    interlocks: list[Interlock] = Field(default_factory=list)
    state_machines: list[StateMachine] = Field(default_factory=list)
    scenarios: list[Scenario] = Field(default_factory=list)

    # ----------------------------------------------------------------- lookup helpers
    def block(self, bid: str) -> Block | None:
        return next((b for b in self.blocks if b.id == bid), None)

    def port(self, ref: str) -> Port | None:
        bid, _, pid = ref.partition(".")
        blk = self.block(bid)
        return next((p for p in blk.ports if p.id == pid), None) if blk else None

    def signal(self, sid: str) -> Signal | None:
        return next((s for s in self.signals if s.id == sid), None)

    def requirement(self, rid: str) -> Requirement | None:
        return next((r for r in self.requirements if r.id == rid), None)

    def claim(self, cid: str) -> EvidenceClaim | None:
        return next((c for c in self.claims if c.id == cid), None)

    def simulatable_blocks(self) -> list[Block]:
        return [b for b in self.blocks if not b.physical_only and b.abstracted_into is None]

    @model_validator(mode="after")
    def _unique_ids(self) -> SystemModel:
        for field in ("blocks", "connections", "signals", "requirements", "parameters"):
            ids = [x.id for x in getattr(self, field)]
            dupes = {i for i in ids if ids.count(i) > 1}
            if dupes:
                raise ValueError(f"duplicate ids in {field}: {sorted(dupes)}")
        return self

    # ----------------------------------------------------------------- metrics for the report
    def coverage(self) -> dict[str, Any]:
        """Numbers the report and the bench both quote. Keep cheap and side-effect free."""
        reqs = self.requirements
        active = [r for r in reqs if r.status == "active"]
        tiers = {"L0": 0, "L1": 0, "L2": 0, "unbound": 0}
        for b in self.simulatable_blocks():
            tiers[b.binding_tier] = tiers.get(b.binding_tier, 0) + 1
        det = sum(1 for c in self.claims if c.extracted_by == "t0_deterministic")
        return {
            "requirements_total": len(reqs),
            "requirements_active": len(active),
            "requirements_satisfied": sum(1 for r in active if r.satisfied_by),
            "requirements_verified": sum(1 for r in active if r.verified_by),
            "blocks": len(self.blocks),
            "blocks_simulatable": len(self.simulatable_blocks()),
            "binding_tiers": tiers,
            "connections": len(self.connections),
            "signals": len(self.signals),
            "claims": len(self.claims),
            "claims_deterministic_pct": round(100 * det / len(self.claims), 1) if self.claims else 0.0,
            "decisions": len(self.decisions),
            "decisions_provisional": sum(1 for d in self.decisions if d.provisional),
            "gaps": len(self.gaps),
            "gaps_blocking": sum(1 for g in self.gaps if g.severity == "blocking"),
            "assumptions": len(self.assumptions),
            "assumptions_unfounded": sum(1 for a in self.assumptions if not a.basis),
            "questions": len(self.questions),
            "questions_blocking": sum(1 for q in self.questions if q.blocking),
        }
