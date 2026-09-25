"""SysML v2 text -> SystemModel, so the Modelica can be *derived from* the SysML (C-08).

PLAN.md §3 had the IR feeding two independent emitters. The briefing's top outcome band asks
for something stricter -- *"Modelica derived from the SysML, correspondence shown"* -- so the
chain is now:

    IR  ->  SysML v2  ->  SystemModel'  ->  Modelica

`SystemModel'` is rebuilt here from nothing but the emitted SysML text, and then handed to the
*existing* `ModelicaEmitter`. Reusing that emitter is deliberate: if the Modelica built from
`SystemModel'` differs from the Modelica built from the original IR, the difference can only
be something this reader failed to recover. That makes the equivalence test a real measurement
of what the SysML carries, instead of a comparison of two hand-written code paths.

Nothing in `emit/sysml.py` is modified. This module re-uses B's `_PATTERNS` and adds two
things B's `parse_back` does not need for a round-trip *name* check but a reader does:

  * **retention** -- B's patterns already capture attribute values, guard expressions and
    allocated class names; `ParsedSysML` keeps only the identifiers. We keep the values.
  * **the comment channel** -- `_code()` strips trailing `//` comments and drops comment-only
    lines. Four load-bearing facts ride in comments (`@series`, sensor/actuator role,
    `bound to`, `@scope`), so we read the comment alongside the statement.

Owner: C.  See Decisions/C.md C-08.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..ir.system import (
    AcceptanceCheck,
    Block,
    Connection,
    Interlock,
    Parameter,
    Port,
    Provenance,
    Quantity,
    Scenario,
    Signal,
    State,
    StateMachine,
    SystemModel,
    Transition,
)
from .sysml import _PATTERNS

# --------------------------------------------------------------------------- what SysML lacks


@dataclass
class SimulationProfile:
    """Facts the Modelica needs that the SysML does not carry. Supplied, never guessed.

    Two kinds live here, and the distinction matters for how we describe C-08:

    * **Legitimately out of scope.** Scan period, stop time, solver and tolerance are
      properties of a simulation run, not of a system. A SysML model that omitted them would
      still be a complete SysML model. Decisions/C.md C-08 item 3 states this on purpose.

    * **A gap in the emitter, tracked as D-2.** `parameters` should not be here. The emitted
      SysML references twelve setpoint symbols inside transition guards
      (`if LIS_301 >= SP_B3_LVL_WATER then …`) and declares none of them, so a model built
      from the SysML alone has guards over undeclared identifiers and will not compile. Once
      the emitter declares them, this field goes away and `sysml_carries_parameters` flips.
    """

    scan_period: float = 0.1
    stop_time: float = 3000.0
    interval: float | None = None
    tolerance: float = 1e-6
    solver: str = "dassl"
    #: The acceptance run's identity. The SysML names each `verification def` but not the
    #: run that executes them, so the scenario's own id and name are not recoverable.
    scenario_id: str = "from_sysml"
    scenario_name: str | None = None
    #: Global/controller parameters, by id. D-2 -- see above.
    parameters: list[Parameter] = field(default_factory=list)

    @classmethod
    def from_ir(cls, model: SystemModel) -> SimulationProfile:
        """Take the uncarried fields off an existing IR, for the `--from-sysml` demo path."""
        sc = model.scenarios[0] if model.scenarios else None
        sm = model.state_machines[0] if model.state_machines else None
        return cls(
            scan_period=sm.scan_period if sm else 0.1,
            stop_time=sc.stop_time if sc else 3000.0,
            interval=sc.interval if sc else None,
            tolerance=sc.tolerance if sc else 1e-6,
            solver=sc.solver if sc else "dassl",
            scenario_id=sc.id if sc else "from_sysml",
            scenario_name=sc.name if sc else None,
            parameters=list(model.parameters),
        )


# ------------------------------------------------------------------------------ parsed shapes


@dataclass
class SysPort:
    name: str
    port_def: str


@dataclass
class SysPartDef:
    name: str
    doc: str = ""
    ports: list[SysPort] = field(default_factory=list)
    attributes: dict[str, str] = field(default_factory=dict)  # name -> unit


@dataclass
class SysPart:
    id: str
    part_def: str
    doc: str = ""
    redefines: dict[str, str] = field(default_factory=dict)  # attribute -> literal
    units: dict[str, str] = field(default_factory=dict)
    physical_only: bool = False
    abstracted_into: str | None = None


@dataclass
class SysInterface:
    id: str
    source: str  # "B1.outlet_1_"
    target: str
    medium: str | None = None
    series: list[str] = field(default_factory=list)


@dataclass
class SysSignal:
    name: str
    datatype: str
    role: str = "sensor"
    binding: str | None = None


@dataclass
class SysConstraint:
    id: str
    sense: str
    actuator: str
    condition: str


@dataclass
class SysState:
    id: str
    region: str
    doc: str = ""
    actions: dict[str, str] = field(default_factory=dict)
    initial: bool = False


@dataclass
class SysTransition:
    id: str
    source: str
    guard: str
    target: str
    #: Regions this transition also activates. Carried as `// fork -> Step12, Step7`.
    #: Structural, not decorative: without it the parallel split never fires and the
    #: sequence deadlocks at the end of Step6.
    forks: list[str] = field(default_factory=list)
    joins: list[str] = field(default_factory=list)
    #: SA-05. A step the evidence leaves no way out of gets an added exit, and the
    #: Modelica emitter only declares the dwell clock `tEnter_<region>` for regions that
    #: have one. Lose the flag and a guard referring to `dwell(...)` has no clock.
    declared_fallback: bool = False


@dataclass
class SysVerification:
    id: str
    doc: str = ""
    expression: str = ""
    verifies: list[str] = field(default_factory=list)


@dataclass
class SysMLModel:
    """Everything recoverable from the emitted SysML, with values, not just names."""

    package: str = ""
    system: str = ""
    part_defs: dict[str, SysPartDef] = field(default_factory=dict)
    parts: list[SysPart] = field(default_factory=list)
    interfaces: list[SysInterface] = field(default_factory=list)
    signals: list[SysSignal] = field(default_factory=list)
    constraints: list[SysConstraint] = field(default_factory=list)
    state_machine: str = ""  # state def name
    state_machine_id: str = ""  # from `exhibit state <id> : <name>`
    regions: list[str] = field(default_factory=list)
    states: list[SysState] = field(default_factory=list)
    transitions: list[SysTransition] = field(default_factory=list)
    allocations: dict[str, tuple[str, str]] = field(default_factory=dict)  # part -> (class, tier)
    verifications: list[SysVerification] = field(default_factory=list)
    #: Statements no pattern matched. Non-empty means the emitter grew a construct this
    #: reader does not know, which under C-08 breaks the Modelica build -- so it is an error,
    #: not a warning.
    unparsed: list[str] = field(default_factory=list)


# ------------------------------------------------------------------------------------ parsing

_TRAILING = re.compile(r"\s//\s?(.*)$")
_SERIES = re.compile(r"^//\s*@series\s+(.*)$")
_SCOPE = re.compile(r"^//\s*@scope\b")
_ABSTRACTION = re.compile(r"^//\s*@abstraction\b.*merged into (\w+)")
_ROLE = re.compile(r"^(sensor|actuator)(?:\s+bound to\s+(\S+))?$")
_CONSTRAINT_DOC = re.compile(r"^(permissive|inhibit) on (\S+):\s*(.*)$")
_FORK = re.compile(r"^fork ->\s*(.*)$")
_FALLBACK = re.compile(r"DECLARED FALLBACK", re.I)
_JOIN = re.compile(r"^join <-\s*(.*)$")
_DOC = re.compile(r"^doc /\* (.*) \*/$")
_EXPR = re.compile(r'^attribute expression : String default "(.*)";$')


def _split(line: str) -> tuple[str, str]:
    """(statement, comment). Unlike `_code`, the comment is returned rather than discarded."""
    s = line.strip()
    if not s:
        return "", ""
    if s.startswith("//"):
        return "", s
    if s.startswith("doc /*") or s.startswith("do action"):
        return s, ""
    m = _TRAILING.search(s)
    return (s[: m.start()].rstrip(), m.group(1).strip()) if m else (s, "")


def read_sysml(text: str) -> SysMLModel:
    """Recover a typed model from emitted SysML v2 text. Deterministic; no model involved."""
    out = SysMLModel()
    stack: list[tuple[str, str]] = []
    cur_part: SysPart | None = None
    cur_def: SysPartDef | None = None
    cur_state: SysState | None = None
    cur_ver: SysVerification | None = None
    cur_region = "main"
    last_iface: SysInterface | None = None

    for raw in text.splitlines():
        code, comment = _split(raw)

        if not code:
            if comment:
                _apply_comment(comment, cur_part, last_iface)
            continue

        kind, m = next(((k, p.match(code)) for k, p in _PATTERNS if p.match(code)), (None, None))
        if kind is None or m is None:
            out.unparsed.append(code)
            continue
        top = stack[-1] if stack else ("", "")

        if kind == "package":
            out.package = m.group(1)
        elif kind == "part_def":
            cur_def = SysPartDef(m.group(1))
            out.part_defs[cur_def.name] = cur_def
        elif kind == "port" and top[0] == "part_def" and cur_def:
            cur_def.ports.append(SysPort(m.group(1), m.group(2)))
        elif kind == "typed_attr" and top[0] == "part_def" and cur_def:
            cur_def.attributes[m.group(1)] = comment or ""
        elif kind == "system":
            out.system = m.group(1)
        elif kind == "part":
            cur_part = SysPart(m.group(1), m.group(2))
            out.parts.append(cur_part)
        elif kind == "redefine" and cur_part:
            cur_part.redefines[m.group(1)] = m.group(2)
            if comment:
                cur_part.units[m.group(1)] = comment
        elif kind == "typed_attr" and top[0] == "system":
            role, binding = "sensor", None
            if rm := _ROLE.match(comment):
                role, binding = rm.group(1), rm.group(2)
            out.signals.append(SysSignal(m.group(1), m.group(2).lower(), role, binding))
        elif kind == "interface":
            last_iface = SysInterface(m.group(1), m.group(2), m.group(3), comment or None)
            out.interfaces.append(last_iface)
        elif kind == "constraint":
            stack.append((kind, m.group(1)))
            out.constraints.append(SysConstraint(m.group(1), "permissive", "", ""))
            continue
        elif kind == "exhibit":
            out.state_machine_id, out.state_machine = m.group(1), m.group(2)
        elif kind == "state_def":
            out.state_machine = out.state_machine or m.group(1)
        elif kind == "region":
            cur_region = m.group(1)
            if cur_region not in out.regions:
                out.regions.append(cur_region)
        elif kind == "state":
            cur_state = SysState(m.group(1), cur_region)
            out.states.append(cur_state)
        elif kind == "entry":
            for s in out.states:
                if s.id == m.group(1):
                    s.initial = True
            out._pending_initial = m.group(1)  # type: ignore[attr-defined]
        elif kind == "action" and cur_state:
            cur_state.actions[m.group(1)] = "true"
        elif kind == "transition":
            tr = SysTransition(m.group(1), m.group(2), m.group(3).strip(), m.group(4))
            if _FALLBACK.search(comment):
                tr.declared_fallback = True
            if fm := _FORK.search(comment):
                tr.forks = [x.strip() for x in fm.group(1).split(",") if x.strip()]
            elif jm := _JOIN.search(comment):
                tr.joins = [x.strip() for x in jm.group(1).split(",") if x.strip()]
            out.transitions.append(tr)
        elif kind == "allocation":
            cls = m.group(3).split("::", 1)[-1]
            tier = comment.replace("tier", "").strip() if comment else "L1"
            out.allocations[m.group(2)] = (cls, tier)
        elif kind == "verification":
            cur_ver = SysVerification(m.group(1))
            out.verifications.append(cur_ver)
        elif kind == "verify" and cur_ver:
            cur_ver.verifies.append(m.group(1))
        elif kind == "doc":
            body = _DOC.match(code)
            txt = body.group(1) if body else ""
            if top[0] == "constraint" and out.constraints:
                if cm := _CONSTRAINT_DOC.match(txt):
                    c = out.constraints[-1]
                    c.sense, c.actuator, c.condition = cm.group(1), cm.group(2), cm.group(3)
            elif top[0] == "verification" and cur_ver:
                cur_ver.doc = txt
            elif top[0] == "state" and cur_state:
                cur_state.doc = txt
            elif top[0] == "part_def" and cur_def:
                cur_def.doc = txt
            elif top[0] == "part" and cur_part is not None:
                cur_part.doc = txt
        elif kind == "string_attr" and cur_ver and top[0] == "verification":
            if em := _EXPR.match(code):
                cur_ver.expression = em.group(1)

        if code.endswith("{"):
            stack.append((kind, m.group(1) if m.groups() else ""))
        elif kind == "close" and stack:
            closed = stack.pop()
            if closed[0] == "part":
                cur_part = None
            elif closed[0] == "state":
                cur_state = None
            elif closed[0] == "verification":
                cur_ver = None
            elif closed[0] == "part_def":
                cur_def = None
    # `entry; then X` precedes the state block, so mark initials in a second pass.
    pending = getattr(out, "_pending_initial", None)
    if pending:
        for s in out.states:
            if s.id == pending:
                s.initial = True
    return out


def _apply_comment(comment: str, part: SysPart | None, iface: SysInterface | None) -> None:
    """Comment-only lines carry three facts the statements do not."""
    if (sm := _SERIES.match(comment)) and iface is not None:
        iface.series = [e.strip() for e in sm.group(1).split(",") if e.strip()]
    elif _SCOPE.match(comment) and part is not None:
        part.physical_only = True
    elif (am := _ABSTRACTION.match(comment)) and part is not None:
        part.abstracted_into = am.group(1)


# ------------------------------------------------------------------- SysML -> SystemModel


_CAMEL = re.compile(r"[A-Z][a-z]*")
_SUBSCRIPT = re.compile(r"^(\w+?)_(\d+)_$")


def _domain_direction(port_def: str) -> tuple[str, str]:
    """`FluidInPort` -> ('fluid', 'in'). The inverse of `_port_def_name`."""
    words = _CAMEL.findall(port_def.removesuffix("Port"))
    if len(words) >= 2:
        return words[0].lower(), words[-1].lower()
    return (words[0].lower() if words else "unknown"), "acausal"


def unsanitise_connector(sysml_name: str, catalog_ports: set[str] | None = None) -> str:
    """`inlet_1_` -> `inlet[1]`, but only when the catalog agrees the base name exists.

    `_ident()` folds `[` and `]` to `_`, and that is not reversible on its own: a component
    could legitimately own a connector called `inlet_1_`. So we propose the un-sanitised form
    and accept it only if the harvested catalog says the allocated class really has a
    connector by that base name. Guessing is replaced by a lookup against ground truth --
    the same move as C-07.
    """
    m = _SUBSCRIPT.match(sysml_name)
    if not m:
        return sysml_name
    base, idx = m.group(1), m.group(2)
    if catalog_ports is None or base in catalog_ports:
        return f"{base}[{idx}]"
    return sysml_name


def to_system_model(
    sysml: SysMLModel,
    profile: SimulationProfile | None = None,
    *,
    index: Any | None = None,
    name: str | None = None,
) -> SystemModel:
    """Rebuild a SystemModel from parsed SysML, so the existing emitter can run on it.

    `index` is a `CatalogIndex`. It is optional but strongly recommended: without it the
    connector un-sanitising in `unsanitise_connector` has nothing to check itself against.
    """
    profile = profile or SimulationProfile()
    if sysml.unparsed:
        raise ValueError(
            f"{len(sysml.unparsed)} SysML statement(s) not understood; the Modelica would be "
            f"incomplete. First: {sysml.unparsed[0]!r}"
        )

    def ports_of(cls: str) -> set[str] | None:
        if index is None:
            return None
        entry = index.get(cls)
        return {p.name for p in entry.ports} if entry else None

    # A part def declares every port ANY block of that kind uses, so reading a part's ports
    # straight off its def hands a two-port vessel a third port belonging to a sibling. Only
    # the ports this part is actually wired through are its own.
    used: dict[str, set[str]] = {}
    for iface in sysml.interfaces:
        for ref in (iface.source, iface.target):
            bid, _, port = ref.partition(".")
            if port:
                used.setdefault(bid, set()).add(port)

    blocks: list[Block] = []
    for p in sysml.parts:
        cls, tier = sysml.allocations.get(p.id, (None, "unbound"))
        pdef = sysml.part_defs.get(p.part_def)
        known = ports_of(cls) if cls else None
        mine = used.get(p.id)
        ports = [
            Port(
                id=sp.name,
                name=unsanitise_connector(sp.name, known),
                domain=_domain_direction(sp.port_def)[0],  # type: ignore[arg-type]
                direction=_domain_direction(sp.port_def)[1],  # type: ignore[arg-type]
            )
            for sp in (pdef.ports if pdef else [])
            if mine is None or sp.name in mine
        ]
        params = [
            Parameter(
                id=f"{p.id}.{k}",
                name=k,
                quantity=Quantity(value=_number(v), unit=p.units.get(k)),
                scope=p.id,
            )
            for k, v in p.redefines.items()
        ]
        blocks.append(
            Block(
                id=p.id,
                name=p.id,
                # `_ident()` folds a kind into an identifier -- "Cooling tank" becomes
                # `Cooling_tank` -- and the binder matches L1 templates on kind WORDS
                # ("cooling tank", "evaporator"). Left sanitised, `Cooling_tank` misses the
                # cooled-vessel template and falls through to the plain vessel one, so B6/B7
                # came back as Reservoir and lost the `cooler` connector the controller
                # drives. Restoring the spacing is what makes the round trip re-bind to the
                # same class the IR path picks.
                kind=p.part_def.replace("_", " ").strip(),
                domains=[ports[0].domain] if ports else ["unknown"],  # type: ignore[list-item]
                ports=ports,
                parameters=params,
                # The part's own doc first: a part def's doc belongs to the KIND, and
                # handing it to every instance gave B2 B1's stated initial charge.
                description=p.doc or (pdef.doc if pdef else None) or None,
                binding_tier=tier if tier in ("L0", "L1", "L2") else "unbound",  # type: ignore[arg-type]
                modelica_class=cls,
                # The SysML carries the DOCUMENT's word for each attribute -- `height`,
                # `max_level` -- because that is what the evidence says and what the system
                # model should show. Modelica needs the class's own parameter names. Copying
                # the document names straight across produced `Reservoir(height = 1)`, which
                # is not a parameter of that class and does not compile.
                #
                # So map them, exactly as the binder does when it binds a block for the first
                # time: tolerate case and word order, and emit only names the catalog confirms
                # the class really has. That also makes this a derivation rather than a
                # transcription, which is the point of C-08.
                modelica_modifiers=_map_to_class(p.redefines, cls, index),
                physical_only=p.physical_only,
                abstracted_into=p.abstracted_into,
            )
        )

    by_id = {b.id: b for b in blocks}

    def endpoint(ref: str) -> str:
        """`B1.outlet_1_` -> `B1.outlet_1_`, keeping the port *id* the reader assigned."""
        bid, _, pname = ref.partition(".")
        blk = by_id.get(bid)
        if blk and any(p.id == pname for p in blk.ports):
            return f"{bid}.{pname}"
        return ref

    connections = [
        Connection(
            id=i.id,
            source=endpoint(i.source),
            target=endpoint(i.target),
            medium=i.medium,
            series_elements=list(i.series),
        )
        for i in sysml.interfaces
    ]

    signals = [
        Signal(id=s.name, name=s.name, role=s.role, datatype=s.datatype, binding=s.binding)  # type: ignore[arg-type]
        for s in sysml.signals
    ]
    interlocks = [
        Interlock(id=c.id, actuator=c.actuator, condition=c.condition, sense=c.sense)  # type: ignore[arg-type]
        for c in sysml.constraints
        if c.actuator
    ]

    states = [
        State(id=s.id, name=s.id, region=s.region, initial=s.initial, actions=dict(s.actions))
        for s in sysml.states
    ]
    transitions = [
        Transition(
            id=t.id,
            source_state=t.source,
            target_state=t.target,
            guard=t.guard,
            forks=list(t.forks),
            joins=list(t.joins),
            declared_fallback=t.declared_fallback,
        )
        for t in sysml.transitions
    ]
    machines: list[StateMachine] = []
    if states:
        machines.append(
            StateMachine(
                id=sysml.state_machine_id or "ctrl",
                name=sysml.state_machine or "Controller",
                regions=sysml.regions or ["main"],
                states=states,
                transitions=transitions,
                scan_period=profile.scan_period,
            )
        )

    checks = [
        AcceptanceCheck(
            id=v.id, description=v.doc, expression=v.expression, requirement_ids=list(v.verifies)
        )
        for v in sysml.verifications
    ]
    scenario = Scenario(
        id=profile.scenario_id,
        name=profile.scenario_name or f"{sysml.system or 'System'}Acceptance",
        stop_time=profile.stop_time,
        interval=profile.interval,
        tolerance=profile.tolerance,
        solver=profile.solver,
        checks=checks,
    )

    return SystemModel(
        name=name or sysml.system or sysml.package or "System",
        description=f"Derived from SysML v2 ({len(sysml.parts)} parts) -- C-08",
        blocks=blocks,
        connections=connections,
        signals=signals,
        interlocks=interlocks,
        state_machines=machines,
        scenarios=[scenario],
        # D-2: not carried by the SysML. See SimulationProfile.
        parameters=list(profile.parameters),
        provenance_note="modelica derived from sysml",
    )


def _number(raw: str) -> Any:
    raw = raw.strip()
    if raw in ("true", "false", "True", "False"):
        return raw.lower() == "true"
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw


def _map_to_class(redefines: dict[str, str], cls: str | None, index: Any) -> dict[str, str]:
    """Document attribute names -> the bound class's real parameter names.

    Without a catalog we cannot tell a valid modifier from an invalid one, so we pass the
    names through unchanged and let the compiler (and the repair loop) be the judge -- better
    than silently dropping a value the evidence supplied.
    """
    from ..ir.complete import match_parameter

    literals = {k: _modelica_literal(v) for k, v in redefines.items()}
    entry = index.get(cls) if (index is not None and cls) else None
    if entry is None:
        return literals
    valid = {p.name for p in entry.params}
    out: dict[str, str] = {}
    for name, value in literals.items():
        target = match_parameter(name, valid)
        if target:
            out[target] = value
    return out


def _modelica_literal(raw: str) -> str:
    """Normalise a SysML attribute value into a Modelica literal.

    Exists because of **D-3**: the SysML emitter interpolates the IR value straight into an
    f-string, so a Python bool arrives as `False`, which is valid in neither SysML v2 nor
    Modelica. `useSupport = False` is what made the drivetrain fail to compile on the
    `--from-sysml` path while the IR path was fine -- the IR carries the correct string
    `'false'` in `modelica_modifiers` and only the SysML round-trip sees the bad one.

    Normalising here keeps the reader robust against what is actually emitted. The real fix
    belongs in the emitter and is raised with B.
    """
    s = raw.strip()
    return {"True": "true", "False": "false"}.get(s, s)
