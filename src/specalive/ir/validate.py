"""Static checks on the IR, run *before* any code is generated.

Catching a defect here costs nothing. Catching it in the repair loop costs six LLM round trips,
and catching it in the demo costs the hard gate. Everything that can be checked structurally is
checked here.

The reachability and consistency checks are the interesting ones: they find defects in the
*source evidence*, not in our code, and those findings are worth points on their own.

Owner: B.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Callable, Literal

from .evidence import Gap
from .system import SystemModel

Severity = Literal["error", "warning", "info"]


@dataclass
class Finding:
    check: str
    severity: Severity
    subject: str
    message: str
    suggestion: str | None = None

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return f"[{self.severity:7}] {self.check}: {self.subject} -- {self.message}"


@dataclass
class ValidationReport:
    findings: list[Finding] = field(default_factory=list)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def add(self, *args, **kwargs) -> None:
        self.findings.append(Finding(*args, **kwargs))

    def as_gaps(self) -> list[Gap]:
        """Non-fatal findings become declared gaps so they surface in the report."""
        out: list[Gap] = []
        for i, f in enumerate(self.findings):
            if f.severity == "info":
                continue
            out.append(
                Gap(
                    id=f"GAP-VAL-{i:03d}",
                    kind="unreachable_guard" if "reachab" in f.check else "unresolved_conflict",
                    subject=f.subject,
                    detail=f.message,
                    severity="blocking" if f.severity == "error" else "warn",
                    workaround=f.suggestion,
                )
            )
        return out


# --------------------------------------------------------------------------- structural checks


def check_port_closure(m: SystemModel, r: ValidationReport) -> None:
    """Every connection endpoint must name a block and a port that exist."""
    for c in m.connections:
        for ref in (c.source, c.target):
            bid, _, pid = ref.partition(".")
            blk = m.block(bid)
            if blk is None:
                r.add("port-closure", "error", c.id, f"connection endpoint '{ref}' names unknown block '{bid}'")
            elif not any(p.id == pid for p in blk.ports):
                r.add(
                    "port-closure",
                    "error",
                    c.id,
                    f"block '{bid}' has no port '{pid}' (has: {[p.id for p in blk.ports]})",
                    suggestion="add the port during extraction or correct the connection",
                )


def check_port_compatibility(m: SystemModel, r: ValidationReport) -> None:
    """A connection must join ports of the same physical domain."""
    for c in m.connections:
        sp, tp = m.port(c.source), m.port(c.target)
        if sp is None or tp is None:
            continue
        if "unknown" in (sp.domain, tp.domain):
            r.add("port-domain", "warning", c.id, f"connection has an unknown-domain endpoint")
        elif sp.domain != tp.domain:
            r.add(
                "port-domain",
                "error",
                c.id,
                f"domain mismatch: {c.source} is {sp.domain} but {c.target} is {tp.domain}",
            )


def check_dangling_blocks(m: SystemModel, r: ValidationReport) -> None:
    """A simulatable block with no connection is almost always an extraction miss."""
    connected: set[str] = set()
    for c in m.connections:
        connected.add(c.source.split(".")[0])
        connected.add(c.target.split(".")[0])
    for b in m.simulatable_blocks():
        if b.id not in connected and b.ports:
            r.add(
                "connectivity",
                "warning",
                b.id,
                "block has ports but no connections; it will be an isolated island in the model",
            )


def check_signal_bindings(m: SystemModel, r: ValidationReport) -> None:
    """Sensors and actuators must bind to something the plant actually exposes."""
    # An actuator may be bound directly, or indirectly by appearing in a connection's series
    # group -- a valve in a series chain is realised as one term of that path's open command.
    in_series: set[str] = set()
    for c in m.connections:
        in_series.update(c.series_elements)

    for s in m.signals:
        if not s.binding:
            stripped = s.name.removeprefix("cmd_")
            if s.role == "actuator" and (s.name in in_series or stripped in in_series):
                continue
            r.add("signal-binding", "warning", s.id, f"{s.role} '{s.name}' has no plant binding")
            continue
        bid = s.binding.split(".")[0]
        if m.block(bid) is None:
            r.add("signal-binding", "error", s.id, f"binding '{s.binding}' names unknown block '{bid}'")


def check_state_machine(m: SystemModel, r: ValidationReport) -> None:
    """States reachable, transitions well-formed, every region has exactly one entry."""
    for sm in m.state_machines:
        ids = {s.id for s in sm.states}
        for t in sm.transitions:
            for ref, what in ((t.source_state, "source"), (t.target_state, "target")):
                if ref not in ids:
                    r.add("fsm-structure", "error", t.id, f"{what} state '{ref}' does not exist")

        for region in sm.regions:
            states = sm.states_in(region)
            if not states:
                r.add("fsm-structure", "warning", sm.id, f"region '{region}' has no states")
                continue
            initials = [s for s in states if s.initial]
            entered_by_fork = {
                s for t in sm.transitions for s in t.forks if (sm.state(s) and sm.state(s).region == region)
            }
            if len(initials) > 1:
                r.add("fsm-structure", "error", sm.id, f"region '{region}' has {len(initials)} initial states")
            if not initials and not entered_by_fork:
                r.add(
                    "fsm-structure",
                    "error",
                    sm.id,
                    f"region '{region}' has no initial state and is never entered by a fork",
                )

        # graph reachability from every entry point
        entries = {s.id for s in sm.states if s.initial}
        entries |= {s for t in sm.transitions for s in t.forks}
        seen, frontier = set(entries), list(entries)
        while frontier:
            cur = frontier.pop()
            for t in sm.transitions:
                if t.source_state == cur:
                    for nxt in [t.target_state, *t.forks]:
                        if nxt not in seen:
                            seen.add(nxt)
                            frontier.append(nxt)
        for s in sm.states:
            if s.id not in seen:
                r.add("fsm-reachability", "warning", s.id, f"state '{s.name}' is unreachable")


def check_guard_symbols(m: SystemModel, r: ValidationReport) -> None:
    """Every identifier in a guard must be a known signal, parameter or builtin."""
    builtins = {
        "time", "true", "false", "and", "or", "not", "abs", "min", "max", "pre", "der",
        "in",  # in(<state>) is the guard language's state-membership predicate
    }
    known = builtins | {s.id for s in m.signals} | {s.name for s in m.signals}
    known |= {p.id for p in m.parameters} | {p.name for p in m.parameters}
    for sm in m.state_machines:
        known |= {s.id for s in sm.states}
        for t in sm.transitions:
            for tok in set(re.findall(r"[A-Za-z_][A-Za-z0-9_.]*", t.guard)):
                root = tok.split(".")[0]
                if root not in known and tok not in known:
                    r.add(
                        "guard-symbols",
                        "error",
                        t.id,
                        f"guard references unknown symbol '{tok}'",
                        suggestion="extract the missing signal/parameter, or fix the guard expression",
                    )


def check_units(m: SystemModel, r: ValidationReport) -> None:
    """Numeric parameters should carry a unit; a bare number is a future bug."""
    for p in m.parameters:
        if isinstance(p.quantity.value, (int, float)) and not isinstance(p.quantity.value, bool):
            if not p.quantity.unit:
                r.add("units", "warning", p.id, f"parameter '{p.name}' has a numeric value with no unit")


def check_binding_coverage(m: SystemModel, r: ValidationReport) -> None:
    """An attempted binding that failed is an error. A block nobody has tried to bind yet is not:
    validation runs before the Modelica emitter binds, and an extracted IR arrives unbound."""
    for b in m.simulatable_blocks():
        if b.binding_tier == "unbound" and b.binding_rationale is None:
            r.add("binding", "info", b.id, "binding pending: the Modelica emitter binds this block")
        elif b.binding_tier == "unbound":
            r.add(
                "binding",
                "error",
                b.id,
                f"block '{b.name}' ({b.kind}) was not bound to any catalog class or template",
                suggestion="extend the catalog aliases, add an L1 template, or mark the block physical_only",
            )
        elif b.binding_tier == "L2":
            r.add("binding", "info", b.id, "bound at L2: equations were model-authored, review before trusting")


# ----------------------------------------------------------------- evidence-quality checks


def check_guard_reachability(m: SystemModel, r: ValidationReport) -> None:
    """Coarse conservation screen: can a 'fill to level / charge to voltage / spin up to speed'
    guard ever be met?

    Domain-agnostic form: for each transition whose guard requires a stored quantity to rise to a
    threshold, add up every inventory that could ever reach that store -- its own, plus every
    storing block upstream of it, transitively, through any number of non-storing elements
    (paths, valves, resistors, clutches). That total is an upper bound on what the store can
    ever hold. If it is still below the threshold the guard can never fire and the sequence
    deadlocks. The stores it understands are listed in `STORES`: geometric volume, electrical
    charge, rotational and translational kinetic energy, and plain mass.

    This is how OPEN-ISSUE-01 is argued in the NaCl packet. It is deliberately conservative:
    it reports only when it can prove insufficiency from declared numbers -- a missing capacity,
    a missing initial state, or an upstream source of unknown size all mean "cannot prove", never
    "defect". A guard with an `or` alternative is skipped: the other branch may fire.
    """
    for sm in m.state_machines:
        for t in sm.transitions:
            if re.search(r"\bor\b", t.guard):
                continue
            for sig_ref, op, rhs in re.findall(r"([A-Za-z_][\w.]*)\s*(>=|>)\s*([A-Za-z_][\w.]*|[0-9.eE+-]+)", t.guard):
                threshold = _resolve_number(m, rhs)
                sig = m.signal(sig_ref)
                if threshold is None or sig is None or not sig.binding or "." not in sig.binding:
                    continue
                block_id, _, variable = sig.binding.partition(".")
                ceiling = _supply_ceiling(m, block_id, variable)
                if ceiling is None or ceiling >= threshold:
                    continue
                r.add(
                    "guard-reachability",
                    "warning",
                    t.id,
                    (
                        f"guard '{t.guard}' needs {sig_ref} {op} {threshold:.4g} but everything that can "
                        f"ever reach '{sig.binding}' amounts to at most {ceiling:.4g}; the transition can "
                        f"never fire and the sequence will deadlock at state '{t.source_state}'"
                    ),
                    suggestion=(
                        "raise this with the customer as a source-data defect, and emit a declared "
                        "fallback transition so the generated sequence cannot deadlock"
                    ),
                )


@dataclass(frozen=True)
class Store:
    """How one conserved quantity is held by a block and read back by a guard."""

    domain: str
    capacity: tuple[str, ...]      # the storage constant: area, capacitance, inertia, mass
    initial: tuple[str, ...]       # the initial state: level, voltage, speed
    inventory: Callable[[float, float], float]   # (capacity, state)  -> conserved amount
    reading: Callable[[float, float], float]     # (capacity, amount) -> the variable a guard reads


_GEOMETRIC = (("area", "A", "cross_section"), ("level_start", "level0", "h_start", "level.start"))
_CAPACITOR = (("C", "capacitance"), ("v_start", "v.start", "voltage_start", "v0"))
_INERTIA = (("J", "inertia"), ("w_start", "w.start", "omega_start", "speed_start"))
_MASS = (("m", "mass"), ("v_start", "v.start", "velocity_start"))

#: guard variable -> the stores that could hold it. Tried in order; the first whose capacity
#: parameter the receiving block declares is used.
STORES: dict[str, tuple[Store, ...]] = {
    "level": (Store("fluid", *_GEOMETRIC, lambda a, h: a * h, lambda a, vol: vol / a),),
    "volume": (Store("fluid", *_GEOMETRIC, lambda a, h: a * h, lambda a, vol: vol),),
    "v": (Store("electrical", *_CAPACITOR, lambda c, v: c * v, lambda c, q: q / c),),
    "voltage": (Store("electrical", *_CAPACITOR, lambda c, v: c * v, lambda c, q: q / c),),
    "q": (Store("electrical", *_CAPACITOR, lambda c, v: c * v, lambda c, q: q),),
    "charge": (Store("electrical", *_CAPACITOR, lambda c, v: c * v, lambda c, q: q),),
    "w": (Store("rotational", *_INERTIA, lambda j, w: 0.5 * j * w * w, lambda j, e: math.sqrt(2 * e / j)),),
    "speed": (Store("rotational", *_INERTIA, lambda j, w: 0.5 * j * w * w, lambda j, e: math.sqrt(2 * e / j)),),
    "energy": (
        Store("rotational", *_INERTIA, lambda j, w: 0.5 * j * w * w, lambda j, e: e),
        Store("translational", *_MASS, lambda mm, v: 0.5 * mm * v * v, lambda mm, e: e),
    ),
    "mass": (Store("fluid", ("m_start", "mass_start"), ("m_start", "mass_start"), lambda m0, _: m0, lambda _, mm: mm),),
}


def _param(blk, names: tuple[str, ...]) -> float | None:
    for p in blk.parameters:
        if p.name in names and isinstance(p.quantity.value, (int, float)) and not isinstance(p.quantity.value, bool):
            return float(p.quantity.value)
    return None


def _resolve_number(m: SystemModel, token: str) -> float | None:
    try:
        return float(token)
    except ValueError:
        pass
    p = next((p for p in m.parameters if token in (p.id, p.name)), None)
    v = p.quantity.value if p else None
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _supply_ceiling(m: SystemModel, block_id: str, variable: str = "level") -> float | None:
    """Upper bound on `block_id.variable` from every inventory that can ever flow into it.

    Returns None -- "cannot prove anything" -- whenever a number is missing: the receiver has no
    declared capacity or initial state, an upstream storing block lacks one, or an upstream
    origin stores nothing we can size (a boundary source is effectively unbounded). None must
    never be reported as a defect.
    """
    here = m.block(block_id)
    if here is None:
        return None
    store = next((s for s in STORES.get(variable, ()) if _param(here, s.capacity) is not None), None)
    if store is None:
        return None
    cap_here, init_here = _param(here, store.capacity), _param(here, store.initial)
    if not cap_here or init_here is None:
        return None
    total = store.inventory(cap_here, init_here)

    simulated = {b.id for b in m.simulatable_blocks()}
    feeds: dict[str, list[str]] = {}
    for c in m.connections:
        if c.domain not in (store.domain, "unknown"):
            continue
        src, dst = c.source.split(".")[0], c.target.split(".")[0]
        if src in simulated and dst in simulated:
            feeds.setdefault(dst, []).append(src)
    if not feeds.get(block_id):
        return None

    seen, frontier = {block_id}, list(feeds[block_id])
    while frontier:
        fid = frontier.pop()
        if fid in seen:
            continue
        seen.add(fid)
        blk = m.block(fid)
        if blk is None:
            return None
        cap, init = _param(blk, store.capacity), _param(blk, store.initial)
        if cap is not None and init is not None:
            total += store.inventory(cap, init)
        elif cap is not None or not feeds.get(fid):
            return None   # a store of unknown content, or an origin of unknown size
        frontier.extend(feeds.get(fid, []))
    return store.reading(cap_here, total)


def check_reference_data_consistency(m: SystemModel, r: ValidationReport) -> None:
    """Placeholder hook for cross-checking supplied reference traces against conservation.

    The NaCl packet ships a 'golden' CSV whose NaCl mass is not conserved across the
    evaporation phase, which means signal-level RMSE against it is meaningless and only
    event-level checks are valid. Whenever a packet supplies reference data, run the same
    screen and say so in the report rather than quietly scoring against bad data.

    TODO(D): implement in verify/acceptance.py once the reference-trace loader is in.
    """
    return


# --------------------------------------------------------------------------------- entry point

ALL_CHECKS = (
    check_port_closure,
    check_port_compatibility,
    check_dangling_blocks,
    check_signal_bindings,
    check_state_machine,
    check_guard_symbols,
    check_units,
    check_binding_coverage,
    check_guard_reachability,
    check_reference_data_consistency,
)


def validate(model: SystemModel, *, checks=ALL_CHECKS) -> ValidationReport:
    report = ValidationReport()
    for check in checks:
        try:
            check(model, report)
        except Exception as exc:  # a broken check must not break the pipeline
            report.add("internal", "warning", check.__name__, f"check raised {exc!r}")
    return report
