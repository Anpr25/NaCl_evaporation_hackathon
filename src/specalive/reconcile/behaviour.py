"""Resolved facts -> interlocks, a state machine and an acceptance scenario.

Everything here turns engineering prose ('LIS-301 >= 0.13 m', 'P1 shall be inhibited when
LIS-701 <= 0.02 m', 'A complete AND B complete AND time > 2500 s') into the IR's guard language:
signal ids, parameter ids, `time`, `in(<state>)`, `pre()` and `and/or/not`.

The parser is deliberately small and deterministic. A clause it cannot formalise is *never*
guessed at: it is dropped from the guard, and a Gap names the clause, the transition and the
consequence, so the report tells the reviewer exactly which piece of behaviour is assumed.

Lowering a sequence with parallel branches follows one rule, independent of any domain:

    a successor that is not a listed step, reached while parallel regions exist, is a fork;
    each region is entered at its first listed step;
    a region step whose successor is a main-sequence step ends that region (-> Done<R>);
    the main-sequence step that regions end into is the join, reached once every Done<R> holds.

Owner: B.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Callable

from ..ir.evidence import EvidenceClaim, Gap
from ..ir.system import (
    AcceptanceCheck,
    Interlock,
    Parameter,
    Provenance,
    Quantity,
    Scenario,
    Signal,
    State,
    StateMachine,
    Transition,
)
from .entities import Entity, clean_unit, ident, is_temperature_unit, norm, to_si

_TAG = r"[A-Z]{1,4}[-_]?\d{1,4}[A-Z]?"
_NUMBER = r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?"
_UNIT = r"(?:degC|degF|°C|°F|[A-Za-z%][A-Za-z%/^0-9]*(?:\([a-z]\))?)"
_CMP = re.compile(
    rf"^(?P<lhs>{_TAG}|time)\s*(?P<op><=|>=|==|=<|=>|<|>|=)\s*(?P<num>{_NUMBER})\s*(?P<unit>{_UNIT})?\s*$"
)
_WORDS = {
    "at least": ">=", "not less than": ">=", "minimum of": ">=", "reaches": ">=", "reach": ">=",
    "at most": "<=", "not more than": "<=", "maximum of": "<=", "or below": "<=",
    "below": "<", "under": "<", "less than": "<", "above": ">", "over": ">",
    "greater than": ">", "exceeds": ">", "exceed": ">",
}
_WORD_CMP = re.compile(
    rf"(?P<lhs>{_TAG}|time)\b(?P<mid>[^.;]{{0,80}}?)\b(?P<word>{'|'.join(sorted(map(re.escape, _WORDS), key=len, reverse=True))})"
    rf"\s+(?P<num>{_NUMBER})\s*(?P<unit>{_UNIT})?"
)
_SYM_CMP = re.compile(rf"(?P<lhs>{_TAG}|time)\s*(?P<op><=|>=|<|>)\s*(?P<num>{_NUMBER})\s*(?P<unit>{_UNIT})?")
_SPLIT = re.compile(r"\s+(AND|OR|and|or)\s+|\s*(&&|\|\|)\s*")
_NOT = re.compile(r"^(?:NOT|not|!)\s*(?P<rest>.+)$")
_COMPLETE = re.compile(
    rf"^(?:the\s+)?(?P<tag>{_TAG}|[A-Za-z]\w*)\s+(?:[a-z]+\s+)?(?:complete|completed|done|finished|returned|empty|emptied|drained)$",
    re.I,
)
_FLIP = {">": "<=", ">=": "<", "<": ">=", "<=": ">", "==": "<>"}


@dataclass
class Parsed:
    expr: str
    unparsed: list[str] = field(default_factory=list)
    params: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    #: (signal id, op, SI value) for every simple comparison -- used to derive acceptance checks.
    comparisons: list[tuple[str, str, float, str | None]] = field(default_factory=list)


class GuardParser:
    """Prose conditions -> IR guard expressions over known signals and parameters."""

    def __init__(
        self,
        signals: list[Signal],
        parameters: list[Parameter],
        *,
        param_scope: dict[str, str | None],
        signal_block: dict[str, str | None],
        regions: list[str] | None = None,
        complete: Callable[[str], tuple[str, str] | None] | None = None,
    ) -> None:
        self.by_key = {norm(s.id): s for s in signals}
        self.by_key.update({norm(s.name): s for s in signals})
        self.parameters = [p for p in parameters if p.status == "effective"
                           and isinstance(p.quantity.value, (int, float))
                           and not isinstance(p.quantity.value, bool)]
        self.param_scope = param_scope
        self.signal_block = signal_block
        self.regions = regions or []
        self.complete = complete

    # ------------------------------------------------------------------ public
    def parse(self, text: str, *, prose: bool = False, join_regions: bool = False) -> Parsed:
        out = Parsed(expr="")
        parts = [p for p in _SPLIT.split(str(text or "").strip()) if p is not None and p.strip()]
        terms: list[str] = []
        pending_op: str | None = None
        for part in parts:
            if part.strip() in ("AND", "and", "&&"):
                pending_op = "and"
                continue
            if part.strip() in ("OR", "or", "||"):
                pending_op = "or"
                continue
            expr = self._clause(part.strip(), out, prose=prose, join_regions=join_regions)
            if expr is None:
                continue
            if terms:
                terms.append(pending_op or "and")
            terms.append(expr)
            pending_op = None
        out.expr = " ".join(terms)
        return out

    # ------------------------------------------------------------------ clauses
    def _clause(self, clause: str, out: Parsed, *, prose: bool, join_regions: bool) -> str | None:
        clause = clause.strip().rstrip(".").strip()
        if not clause:
            return None
        negate = False
        if m := _NOT.match(clause):
            negate, clause = True, m.group("rest").strip()

        if m := _CMP.match(clause):
            expr = self._comparison(m.group("lhs"), m.group("op"), m.group("num"), m.group("unit"), out)
            if expr:
                return f"not ({expr})" if negate else expr
        if prose:
            m = _SYM_CMP.search(clause)
            if m:
                expr = self._comparison(m.group("lhs"), m.group("op"), m.group("num"), m.group("unit"), out)
                if expr:
                    return f"not ({expr})" if negate else expr
            m = _WORD_CMP.search(clause)
            if m:
                expr = self._comparison(m.group("lhs"), _WORDS[m.group("word")], m.group("num"), m.group("unit"), out)
                if expr:
                    return f"not ({expr})" if negate else expr

        # 'NOT V15' -- an actuated element's own command, read through pre() so the controller
        # never reads an output in the same scan that computes it.
        if negate and (sig := self._actuator_for(clause)) is not None:
            return f"not pre({sig.name})"

        if (m := _COMPLETE.match(clause)) is not None:
            who = m.group("tag")
            region = next((r for r in self.regions if r.lower() == who.lower()), None)
            if region is not None:
                if join_regions:
                    out.notes.append(f"'{clause}' is enforced by the join transition")
                    return None
                return f"in(Done{ident(region)})"
            if who.lower() in ("both", "all", "each"):
                if join_regions:
                    out.notes.append(f"'{clause}' is enforced by the join transition")
                    return None
                return " and ".join(f"in(Done{ident(r)})" for r in self.regions) or None
            if self.complete is not None and (derived := self.complete(who)) is not None:
                expr, why = derived
                out.notes.append(f"'{clause}' formalised as '{expr}': {why}")
                return expr

        out.unparsed.append(clause)
        return None

    def _comparison(self, lhs: str, op: str, num: str, unit: str | None, out: Parsed) -> str | None:
        op = {"=<": "<=", "=>": ">=", "=": "=="}.get(op, op)
        if lhs.lower() == "time":
            symbol, block, temperature = "time", None, False
        else:
            sig = self.by_key.get(norm(lhs))
            if sig is None or sig.role != "sensor":
                return None
            symbol, block = sig.name, self.signal_block.get(sig.id)
            temperature = is_temperature_unit(sig.unit)
        value, si_unit, note = to_si(float(num), unit, temperature=temperature)
        if note:
            out.notes.append(note)
        if isinstance(value, float) and value.is_integer() and "." not in num:
            value = int(value)
        rhs = self.symbol_for(value, si_unit, block) or _literal(value)
        if not rhs[0].isdigit() and not rhs.startswith("-"):
            out.params.append(rhs)
        out.comparisons.append((symbol, op, float(value), si_unit))
        return f"{symbol} {op} {rhs}"

    def symbol_for(self, value: float, unit: str | None, block: str | None) -> str | None:
        """The effective parameter that states this very number, if exactly one does."""
        unit = clean_unit(unit)
        cands = [
            p for p in self.parameters
            if math.isclose(float(p.quantity.value), float(value), rel_tol=1e-9, abs_tol=1e-12)
            and (unit is None or clean_unit(p.quantity.unit) in (unit, None))
        ]
        scoped = [p for p in cands if block and self.param_scope.get(p.id) == block]
        pick = scoped if scoped else ([] if block and len(cands) > 1 else cands)
        return pick[0].name if len(pick) == 1 else None

    def _actuator_for(self, text: str) -> Signal | None:
        m = re.fullmatch(_TAG, text.strip())
        if not m:
            return None
        return self.by_key.get(norm(f"cmd_{text.strip()}"))


def _literal(v: float | int) -> str:
    return repr(v) if isinstance(v, float) else str(v)


def negate_comparison(expr: str) -> str | None:
    m = re.fullmatch(r"(\w+) (<=|>=|<|>) (\S+)", expr.strip())
    if not m or m.group(2) not in _FLIP:
        return None
    return f"{m.group(1)} {_FLIP[m.group(2)]} {m.group(3)}"


# ------------------------------------------------------------------------------ interlocks

_REQ_INTERLOCK = re.compile(
    r"^(?:the\s+)?(?P<actor>.+?)\s+shall\s+be\s+(?P<kind>inhibited|interlocked|prevented|blocked|"
    r"tripped|permitted|enabled|allowed)\s+(?P<conj>only\s+when|only\s+if|when|if|unless|while)\s+"
    r"(?P<cond>.+?)\.?$",
    re.I,
)
_PERMISSIVE_SUBJECT = re.compile(r"^(?P<actor>.+?)\s+(?P<kind>permissive|inhibit|interlock)$", re.I)


@dataclass
class InterlockEvidence:
    actor: str
    sense: str
    condition: str
    claim: EvidenceClaim
    requirement_id: str | None = None


def interlock_evidence(claims: list[EvidenceClaim], active_requirements: dict[str, str]) -> list[InterlockEvidence]:
    """Find permissive/inhibit statements in requirement text and in extracted claims."""
    out: list[InterlockEvidence] = []
    for c in claims:
        if c.kind == "requirement" and norm(c.predicate) == "requirement" and isinstance(c.value, str):
            rid = str(c.subject).strip()
            if rid not in active_requirements:
                continue
            m = _REQ_INTERLOCK.match(c.value.strip())
            if not m:
                continue
            kind, conj = m.group("kind").lower(), m.group("conj").lower()
            blocks = kind in ("inhibited", "interlocked", "prevented", "blocked", "tripped")
            sense = "inhibit" if blocks and conj != "unless" else "permissive"
            out.append(InterlockEvidence(m.group("actor"), sense, m.group("cond"), c, rid))
        elif isinstance(c.value, str) and (m := _PERMISSIVE_SUBJECT.match(str(c.subject).strip())):
            sense = "permissive" if m.group("kind").lower() == "permissive" else "inhibit"
            # In a transposed datasheet ('Property | P1 | P2') the column is the device.
            actor = m.group("actor")
            if re.fullmatch(_TAG, str(c.predicate).strip().upper()):
                actor = f"{str(c.predicate).strip().upper()} {actor}"
            out.append(InterlockEvidence(actor, sense, c.value, c))
    return out


def build_interlocks(
    evidence: list[InterlockEvidence],
    parser: GuardParser,
    actuators: list[Signal],
    known_tags: dict[str, str],
) -> tuple[list[Interlock], list[Gap]]:
    """One Interlock per distinct (actuator, condition), merged across every source that states it."""
    merged: dict[tuple[str, frozenset[str]], Interlock] = {}
    gaps: list[Gap] = []
    for ev in evidence:
        act = _actuator_for_actor(ev.actor, actuators, known_tags)
        parsed = parser.parse(ev.condition, prose=True)
        if act is None or not parsed.expr:
            why = "no actuator matches its subject" if act is None else "its condition could not be formalised"
            gaps.append(Gap(
                id=f"GAP-IL-{len(gaps) + 1:02d}", kind="unextracted", subject=ev.actor,
                detail=f"interlock statement '{ev.actor} ... {ev.condition}' ({ev.claim.ref()}) was not "
                       f"modelled: {why}", severity="warn",
                requirement_ids=[ev.requirement_id] if ev.requirement_id else [],
            ))
            continue
        sense, expr = ev.sense, parsed.expr
        # 'inhibited when X < a' is 'permitted when X >= a': normalise, so the same rule stated
        # both ways by two documents is recognised as one rule.
        if sense == "inhibit" and " and " not in expr and " or " not in expr:
            flipped = negate_comparison(expr)
            if flipped:
                sense, expr = "permissive", flipped
        clauses = frozenset(x.strip() for x in re.split(r"\band\b", expr)) if " or " not in expr else frozenset([expr])
        for clause in sorted(clauses) if sense == "permissive" and " or " not in expr else [expr]:
            key = (act.name, frozenset([clause]))
            il = merged.get(key)
            if il is None:
                il = Interlock(
                    id=f"IL_{ident(act.name.removeprefix('cmd_'))}_{sum(1 for k in merged if k[0] == act.name) + 1}",
                    actuator=act.name, condition=clause, sense=sense,  # type: ignore[arg-type]
                    provenance=Provenance(note="derived from permissive/inhibit statements"),
                )
                merged[key] = il
            if ev.claim.id not in il.provenance.claim_ids:
                il.provenance.claim_ids.append(ev.claim.id)
            if ev.requirement_id and ev.requirement_id not in il.provenance.requirement_ids:
                il.provenance.requirement_ids.append(ev.requirement_id)
    return list(merged.values()), gaps


def _actuator_for_actor(actor: str, actuators: list[Signal], known_tags: dict[str, str]) -> Signal | None:
    from .entities import find_tags

    for tag in find_tags(actor, known_tags):
        sig = next((s for s in actuators if norm(s.name) == norm(f"cmd_{tag}")), None)
        if sig is not None:
            return sig
    words = [w for w in re.findall(r"[a-z]{4,}", actor.lower()) if w not in ("shall", "with", "from")]
    stems = {w[:4] for w in words}
    hits = [s for s in actuators if any(stem in s.name.lower() for stem in stems)]
    tags = find_tags(actor, known_tags)
    if len(hits) > 1 and tags:
        hits = [s for s in hits if any(norm(t) in norm(s.name) for t in tags)]
    return hits[0] if len(hits) == 1 else None


# ------------------------------------------------------------------------------ state machine


@dataclass
class StepRow:
    entity: Entity
    id: str
    name: str
    region: str
    action: str
    guard: str
    next: str


def region_of(label: str) -> str:
    low = (label or "").strip().lower()
    if low in ("", "single", "main", "sequential", "serial", "join", "none", "-"):
        return "main"
    rest = re.sub(r"^(parallel|branch|region|thread|lane)\s*", "", low, flags=re.I).strip()
    return ident(rest.upper() if len(rest) <= 2 else rest) if rest else "main"


def step_rows(entities: dict[str, Entity]) -> list[StepRow]:
    """Rows of the sequence table: entities with an explicit successor, in the author's order."""
    rows = [e for e in entities.values() if e.has("next")]
    rows.sort(key=lambda e: e.order())
    return [
        StepRow(
            entity=e,
            id=ident(e.subject),
            name=e.text("purpose", "name", "description") or e.subject,
            region=region_of(e.text("region")),
            action=e.text("action"),
            guard=e.text("guard"),
            next=e.text("next"),
        )
        for e in rows
    ]


@dataclass
class FsmResult:
    machine: StateMachine | None
    gaps: list[Gap] = field(default_factory=list)
    comparisons: dict[str, list[tuple[str, str, float, str | None]]] = field(default_factory=dict)


def build_state_machine(
    rows: list[StepRow],
    parser: GuardParser,
    actions_for: Callable[[str], tuple[dict[str, str], list[str]]],
    *,
    name: str = "Controller",
    scan_period: float = 0.1,
) -> FsmResult:
    res = FsmResult(machine=None)
    if not rows:
        return res
    by_key = _step_index(rows)
    regions = ["main"] + [r for r in dict.fromkeys(row.region for row in rows) if r != "main"]
    parser.regions = [r for r in regions if r != "main"]

    states: list[State] = []
    transitions: list[Transition] = []

    def gap(subject: str, detail: str, severity: str = "warn") -> None:
        res.gaps.append(Gap(id=f"GAP-FSM-{len(res.gaps) + 1:02d}", kind="unextracted", subject=subject,
                            detail=detail, severity=severity))  # type: ignore[arg-type]

    initial = next((r for r in rows if r.region == "main" and re.match(r"(?i)^(initial|idle|init|start)", r.id)), None)
    initial = initial or next((r for r in rows if r.region == "main"), rows[0])

    for r in rows:
        acts, unresolved = actions_for(r.action)
        for u in unresolved:
            gap(r.id, f"action '{u}' in step {r.id} names nothing the controller can command; left out")
        states.append(State(
            id=r.id, name=r.name, region=r.region, initial=(r is initial), actions=acts,
            description=r.name, provenance=Provenance(claim_ids=r.entity.claim_ids),
        ))

    parallel = [g for g in regions if g != "main"]
    entry = {g: next(r.id for r in rows if r.region == g) for g in parallel}
    for g in parallel:
        states.append(State(id=f"Idle{ident(g)}", name=f"Region {g} inactive", region=g, initial=True,
                            provenance=Provenance(note="synthesised: a parallel region's idle state before the fork")))
        states.append(State(id=f"Done{ident(g)}", name=f"Region {g} complete", region=g,
                            provenance=Provenance(note="synthesised: a parallel region's completion state for the join")))

    fork_state: str | None = None
    join_target: str | None = None
    join_rows: list[StepRow] = []

    def add(src: str, dst: str, guard_text: str, row: StepRow | None, *, forks=None, joins=None,
            join_regions: bool = False, guard_override: str | None = None) -> None:
        tid = f"T_{src}_{dst}"
        if guard_override is not None:
            expr, parsed = guard_override, None
        else:
            parsed = parser.parse(guard_text, join_regions=join_regions)
            expr = parsed.expr
            for u in parsed.unparsed:
                gap(tid, f"guard clause '{u}' of {src} -> {dst} could not be formalised and was dropped; "
                         f"the transition fires on the remaining clauses" + ("" if expr else " (none: it fires on the next scan)"))
            if parsed.comparisons:
                res.comparisons[tid] = parsed.comparisons
        if not expr:
            expr = "true"
        transitions.append(Transition(
            id=tid, source_state=src, target_state=dst, guard=expr, forks=forks or [], joins=joins or [],
            provenance=Provenance(claim_ids=row.entity.claim_ids if row else [],
                                  note="; ".join(parsed.notes) if parsed and parsed.notes else None),
        ))

    for r in rows:
        tgt = by_key.get(norm(r.next))
        if tgt is not None:
            if r.region != "main" and tgt.region == "main":
                add(r.id, f"Done{ident(r.region)}", r.guard, r)
                join_target = join_target or tgt.id
                join_rows.append(r)
            else:
                add(r.id, tgt.id, r.guard, r, join_regions=(r.region == "main" and r.id in _join_ids(rows, by_key)))
            continue
        if parallel and r.next:
            fork_state = ident(r.next)
            states.append(State(id=fork_state, name=f"{r.next} (parallel branches active)", region="main",
                                provenance=Provenance(claim_ids=r.entity.claim_ids,
                                                      note="synthesised: the fork named as a successor")))
            add(r.id, fork_state, r.guard, r, forks=[entry[g] for g in parallel])
        else:
            gap(r.id, f"step {r.id} names successor '{r.next}', which is not a listed step")

    if fork_state and join_target:
        dones = [f"Done{ident(g)}" for g in parallel]
        add(fork_state, join_target, "", None, joins=dones,
            guard_override=" and ".join(f"in({d})" for d in dones))
    elif parallel:
        gap(name, "parallel regions were listed but no fork/join pair could be identified", "blocking")

    res.machine = StateMachine(
        id=ident(name).lower(), name=ident(name), regions=regions, states=states,
        transitions=transitions, scan_period=scan_period,
        provenance=Provenance(claim_ids=[c for r in rows for c in r.entity.claim_ids][:50]),
    )
    return res


def _step_index(rows: list[StepRow]) -> dict[str, StepRow]:
    """Every name a step answers to. A merged row 'Step10/11' is referred to as 'Step10' by
    whoever precedes it, so each number of a combined name is an alias of the row."""
    idx: dict[str, StepRow] = {}
    for r in rows:
        idx.setdefault(norm(r.entity.subject), r)
        idx.setdefault(norm(r.id), r)
        m = re.fullmatch(r"(?P<stem>[A-Za-z_ ]*?)(?P<nums>\d+(?:\s*/\s*\d+)+)", r.entity.subject.strip())
        if m:
            for n in re.split(r"\s*/\s*", m.group("nums")):
                idx.setdefault(norm(f"{m.group('stem')}{n}"), r)
    return idx


def _join_ids(rows: list[StepRow], by_key: dict[str, StepRow]) -> set[str]:
    """Main-sequence steps that some parallel region hands back to."""
    out: set[str] = set()
    for r in rows:
        tgt = by_key.get(norm(r.next))
        if tgt is not None and r.region != "main" and tgt.region == "main":
            out.add(tgt.id)
    return out


# ------------------------------------------------------------------------------ scenario

_DURATION = re.compile(r"(?P<n>\d+(?:\.\d+)?)\s*s\s+(?:acceptance|test|run|simulation|batch run|trace|scenario)", re.I)
_LOWER_BOUND = re.compile(r"(?:beyond|exceeds?|exceeding|past|more than|longer than|>)\s*(?P<n>\d+(?:\.\d+)?)\s*s\b", re.I)
_INTERVAL = re.compile(r"\blog(?:ged|ging)?\s+(?:at|every)\s+(?P<n>\d+(?:\.\d+)?)\s*s\b", re.I)
_INITIAL = re.compile(rf"\binitial\s+(?P<var>[A-Za-z_]\w*)\s*=\s*(?P<num>{_NUMBER})", re.I)
_RECORD_ID = re.compile(r"\b[A-Z]{2,}-\d{2,}\b")


def build_scenario(
    claims: list[EvidenceClaim],
    title: str | None,
    machine: StateMachine | None,
    comparisons: dict[str, list[tuple[str, str, float, str | None]]],
    signals: dict[str, Signal],
    blocks_initial: dict[str, list[tuple[str, float, EvidenceClaim]]],
) -> tuple[Scenario, list[Gap]]:
    gaps: list[Gap] = []
    used: list[str] = []
    direct, lower, interval = [], [], []
    for c in claims:
        text = c.value if isinstance(c.value, str) else c.quote
        if not text:
            continue
        for m in _DURATION.finditer(text):
            direct.append(float(m.group("n")))
            used.append(c.id)
        for m in _LOWER_BOUND.finditer(text):
            lower.append(float(m.group("n")))
            used.append(c.id)
        for m in _INTERVAL.finditer(text):
            interval.append(float(m.group("n")))
            used.append(c.id)

    floor = max(lower, default=0.0)
    if direct and max(direct) > floor:
        stop, why = max(direct), f"the packet names a {max(direct):g} s run"
    elif floor:
        stop = float(_round_up(1.2 * floor))
        why = f"no run length is stated; {stop:g} s clears the longest stated time bound ({floor:g} s) by 20%"
        gaps.append(Gap(id="GAP-SCN-01", kind="deviation", subject="scenario.stop_time", severity="info",
                        detail=f"assumption: stop time {stop:g} s ({why})"))
    else:
        stop, why = 10.0, "nothing in the packet bounds the run"
        gaps.append(Gap(id="GAP-SCN-01", kind="unextracted", subject="scenario.stop_time", severity="warn",
                        detail="no run length or time bound found; defaulted to 10 s"))

    sid = (_RECORD_ID.search(title or "") or [None])[0] if title else None
    scenario = Scenario(
        id=sid or "SCN-01",
        name=ident((sid or "Acceptance").replace("-", "")),
        stop_time=stop,
        interval=min(interval) if interval else None,
        provenance=Provenance(claim_ids=sorted(set(used)), note=f"stop time: {why}"),
    )

    # Initial conditions stated as 'Initial <var> = <value>' against a part.
    for bid, items in blocks_initial.items():
        for var, value, claim in items:
            scenario.initial_conditions[f"{bid}.{var}"] = Quantity(value=value)
            scenario.provenance.claim_ids.append(claim.id)

    # Acceptance checks: every threshold the sequence waits on must actually be crossed.
    if machine is not None:
        for t in machine.transitions:
            for sig_name, op, value, _unit in comparisons.get(t.id, []):
                sig = signals.get(sig_name)
                if sig is None or not sig.binding:
                    continue
                direction = "rising" if op in (">", ">=") else "falling"
                src = machine.state(t.source_state)
                scenario.checks.append(AcceptanceCheck(
                    id=f"CHK-{t.id.removeprefix('T_')}",
                    description=f"{src.name if src else t.source_state} completes when {sig_name} {op} {value:g}",
                    kind="threshold",
                    expression=f"crosses({sig.binding}, {value:g}, {direction})",
                    requirement_ids=list(t.provenance.requirement_ids),
                    provenance=Provenance(claim_ids=list(t.provenance.claim_ids),
                                          note=f"derived from transition {t.id}"),
                ))
    return scenario, gaps


def _round_up(x: float) -> float:
    if x <= 0:
        return 10.0
    mag = 10 ** math.floor(math.log10(x))
    return math.ceil(x / mag * 2) / 2 * mag
