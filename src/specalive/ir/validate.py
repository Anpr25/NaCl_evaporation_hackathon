"""Static checks on the IR, run *before* any code is generated.

Catching a defect here costs nothing. Catching it in the repair loop costs six LLM round trips,
and catching it in the demo costs the hard gate. Everything that can be checked structurally is
checked here.

The reachability and consistency checks are the interesting ones: they find defects in the
*source evidence*, not in our code, and those findings are worth points on their own.

Owner: B.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

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
    for b in m.simulatable_blocks():
        if b.binding_tier == "unbound":
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
    """Coarse conservation screen: can a 'fill to level/charge/quantity X' guard ever be met?

    Domain-agnostic form: for each transition whose guard is a monotone threshold on a
    conserved accumulation (``level``, ``mass``, ``charge``, ``energy``), sum the capacity of
    every upstream supplier feeding that block in the current sequence step. If the supply
    ceiling is below the threshold the guard can never fire and the sequence deadlocks.

    This is what found OPEN-ISSUE-01 in the NaCl packet. It is deliberately conservative: it
    only reports when it can prove insufficiency from declared numbers, never on a hunch.
    """
    accum = ("level", "mass", "charge", "volume", "energy", "inventory")
    for sm in m.state_machines:
        for t in sm.transitions:
            match = re.match(r"\s*([A-Za-z_][\w.]*)\s*(>=|>)\s*([0-9.eE+-]+)", t.guard)
            if not match:
                continue
            sig_ref, _, threshold_txt = match.groups()
            sig = m.signal(sig_ref)
            if sig is None or not sig.binding:
                continue
            if not any(a in sig.binding.lower() or a in sig.name.lower() for a in accum):
                continue
            ceiling = _supply_ceiling(m, sig.binding.split(".")[0])
            if ceiling is None:
                continue
            if ceiling < float(threshold_txt):
                r.add(
                    "guard-reachability",
                    "warning",
                    t.id,
                    (
                        f"guard '{t.guard}' needs {threshold_txt} but the upstream supply ceiling for "
                        f"'{sig.binding}' is {ceiling:.4g}; the transition can never fire and the "
                        f"sequence will deadlock at state '{t.source_state}'"
                    ),
                    suggestion=(
                        "raise this with the customer as a source-data defect, and emit a declared "
                        "fallback transition so the generated sequence cannot deadlock"
                    ),
                )


def _supply_ceiling(m: SystemModel, block_id: str) -> float | None:
    """Best-effort upstream capacity for `block_id`, in the same unit as its accumulation.

    TODO(C+B): today this only understands a single geometric upstream vessel, which covers the
    process case. Generalise to electrical charge and rotational energy when those benches land.
    Returning None means 'cannot prove anything', which must never be reported as a defect.
    """
    feeders = [c.source.split(".")[0] for c in m.connections if c.target.startswith(f"{block_id}.")]
    if not feeders:
        return None
    total = 0.0
    for fid in feeders:
        blk = m.block(fid)
        if blk is None:
            return None
        params = {p.name: p.quantity.value for p in blk.parameters}
        area, level = params.get("area"), params.get("level_start")
        if not isinstance(area, (int, float)) or not isinstance(level, (int, float)):
            return None
        total += float(area) * float(level)
    here = m.block(block_id)
    if here is None:
        return None
    my_area = next((p.quantity.value for p in here.parameters if p.name == "area"), None)
    if not isinstance(my_area, (int, float)) or my_area == 0:
        return None
    return total / float(my_area)


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
