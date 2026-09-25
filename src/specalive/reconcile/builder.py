"""Claims -> a single validated SystemModel, with a DecisionRecord for every contested fact.

Shape of the job:

  1. group claims by (subject, predicate)             -- one group = one fact
  2. run every multi-claim group through the precedence engine
  3. regroup the surviving facts per subject          -- one Entity = everything we believe about it
  4. assemble entities into IR elements, by what their facts *are*, not by where they came from:
       a subject with `from` and `to`             is a hop          -> topology (paths, series groups)
       a subject with `next`                      is a sequence step -> state machine
       a subject with `location` + a measurement  is an instrument  -> sensor signal
       a subject with a numeric `value`           is a parameter
       a tagged subject with a physical kind      is a part         -> block
  5. attach provenance everywhere, and a Gap wherever something did not survive

Step 4 reads *shapes of facts*, so a new packet whose registers use different sheet names or
column wording assembles the same way; nothing here names a tag, medium or value from any
particular packet. Only resolved facts are ever read, so a superseded value cannot leak into
the model -- the losing claims exist only in the decision log.

Owner: B.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from ..ingest.base import Document
from ..ir.evidence import AuthorityClass, DecisionRecord, EvidenceClaim, Gap, Source
from ..ir.system import (
    Block,
    Connection,
    Parameter,
    Port,
    Provenance,
    Quantity,
    Requirement,
    Signal,
    SystemModel,
)
from .behaviour import (
    GuardParser,
    build_interlocks,
    build_scenario,
    build_state_machine,
    interlock_evidence,
    negate_comparison,
    step_rows,
)
from .entities import (
    MANUAL_WORDS,
    PHYSICAL_ONLY_WORDS,
    TAG_RE,
    Entity,
    build_entities,
    find_tags,
    ident,
    infer_domains,
    looks_like_tag,
    measurement_var,
    norm,
    predicate_key,
    singular,
    to_si,
)
from .precedence import PrecedenceEngine, build_supersession_map, resolve_source_supersession
from .topology import GROUP_REF, Path as Route, TopologyBuilder, collect_edges, connects_to_claims, is_signal_medium


#: Relations where one subject legitimately has many values at once.
MULTI_VALUED = {"connectsto", "connectedto", "feeds", "flowsto", "label"}


def group_claims(claims: list[EvidenceClaim]) -> dict[tuple[str, str], list[EvidenceClaim]]:
    """One group per fact. Subject matching is case-insensitive and whitespace-insensitive,
    because the same tag is written 'B5', 'b5' and 'B-5' across a real packet; predicates are
    canonicalised so 'Guard/transition' and 'Guard' compete for the same fact."""
    groups: dict[tuple[str, str], list[EvidenceClaim]] = defaultdict(list)
    for c in claims:
        key = (_norm(c.subject), predicate_key(c.predicate))
        groups[key].append(c)
    return dict(groups)


def _norm(s: str) -> str:
    return norm(s)


def resolve_all(
    claims: list[EvidenceClaim],
    sources: dict[str, Source],
    engine: PrecedenceEngine,
) -> tuple[dict[tuple[str, str], EvidenceClaim], list[DecisionRecord]]:
    """Resolve every fact. Returns the winning claim per fact plus the full decision log."""
    record_sup = build_supersession_map(claims)
    source_sup = resolve_source_supersession(record_sup, sources, claims)

    winners: dict[tuple[str, str], EvidenceClaim] = {}
    decisions: list[DecisionRecord] = []
    for key, group in group_claims(claims).items():
        # Distinct values only: five sources agreeing is not a conflict, it is corroboration.
        # A many-valued relation (B5 feeds K1 *and* B7) is not a conflict either; topology reads
        # those claims directly, so they never need a single winner.
        distinct = {repr(c.value) for c in group}
        if len(distinct) == 1 or key[1] in MULTI_VALUED:
            winners[key] = max(group, key=lambda c: c.confidence)
            continue
        winner, decision = engine.resolve(
            group[0].subject, group[0].predicate, group, sources, supersession=source_sup
        )
        winners[key] = winner
        decisions.append(decision)
    return winners, decisions


def build_model(
    docs: list[Document],
    claims: list[EvidenceClaim],
    *,
    name: str | None = None,
    precedence_config: str | Path = "config/precedence.yaml",
) -> SystemModel:
    """Assemble the IR: requirements, parameters, blocks, connections, signals, interlocks,
    the state machine and the acceptance scenario, each traced to the claims it came from."""
    sources = {d.source.id: d.source for d in docs}
    engine = PrecedenceEngine(precedence_config)
    winners, decisions = resolve_all(claims, sources, engine)

    model = SystemModel(
        name=name or _infer_name(docs),
        description=None,
        sources=list(sources.values()),
        claims=claims,
        decisions=decisions,
    )
    model.requirements = _build_requirements(winners, claims)
    model.parameters = _build_parameters(winners, claims)

    Assembler(docs, claims, build_entities(winners), model).run()

    model.gaps.extend(_unassembled_gaps(winners, model))
    return model


# ------------------------------------------------------------------------------- assembly


class Assembler:
    """Turns resolved entities into IR elements. One method per backlog item B1..B5."""

    def __init__(self, docs: list[Document], claims: list[EvidenceClaim],
                 entities: dict[str, Entity], model: SystemModel) -> None:
        self.docs = docs
        self.claims = claims
        self.entities = entities
        self.m = model
        self.topo = TopologyBuilder(entities, claims)
        self.known = self.topo.known
        self.ports: dict[str, list[Port]] = defaultdict(list)
        self.initials: dict[str, list[tuple[str, float, EvidenceClaim]]] = defaultdict(list)
        self.routes: list[Route] = []
        self.path_of: dict[str, Route] = {}
        self.gaps: list[Gap] = []
        self.decisions: list[DecisionRecord] = []
        self.signal_block: dict[str, str | None] = {}
        self.comparisons: dict[str, list[tuple[str, str, float, str | None]]] = {}

    def run(self) -> None:
        self.classify()
        self.build_blocks()          # B1
        self.build_topology()        # B2
        self.build_signals()         # B3
        self.build_behaviour()       # B4
        self.build_scenario()        # B5
        self.link_requirements()
        self.m.domains = sorted({d for b in self.m.blocks for d in b.domains if d != "unknown"}
                                | ({"control"} if self.m.state_machines else set())) or ["unknown"]  # type: ignore[assignment]
        self.m.decisions.extend(self.decisions + self.topo.decisions)
        self.m.gaps.extend(self.topo.gaps + self.gaps)

    # ------------------------------------------------------------------ classification
    def classify(self) -> None:
        ents = self.entities.values()
        self.requirement_keys = {e.key for e in ents if e.has("requirement")}
        self.parameter_keys = {e.key for e in ents if e.get("value") is not None
                               and isinstance(e.get("value").value, (int, float))}
        self.edge_keys = {e.key for e in ents if e.has("from") and e.has("to")}
        self.step_keys = {e.key for e in ents if e.has("next")}
        self.instrument_keys = {
            e.key for e in ents
            if e.has("location") and (e.has("measurement") or e.has("unit"))
            and e.key not in self.parameter_keys and looks_like_tag(e.subject)
        }
        taken = self.requirement_keys | self.parameter_keys | self.edge_keys | self.step_keys | self.instrument_keys

        referenced: set[str] = set()
        for e in ents:
            if e.key in self.edge_keys:
                referenced |= {norm(e.text("from")), norm(e.text("to"))}
            if e.key in self.instrument_keys:
                referenced |= {norm(m.group(0)) for m in TAG_RE.finditer(e.text("location"))}
        registered_mentions = {
            norm(m.group(0))
            for c in self.claims if c.extracted_by == "t0_deterministic"
            for m in TAG_RE.finditer(f"{c.value if isinstance(c.value, str) else ''} {c.quote}")
        }
        self.part_keys: list[str] = []
        for e in sorted(ents, key=lambda e: e.order()):
            if e.key in taken or not looks_like_tag(e.subject):
                continue
            has_kind = e.has("type", "kind", "ownership")
            physical = infer_domains(self._kind_text(e), e.text("name"), e.text("kind")) != ["unknown"]
            if has_kind and (physical or e.key in referenced):
                self.part_keys.append(e.key)
            elif e.key in referenced:
                self.part_keys.append(e.key)
            elif not e.registered and e.key not in registered_mentions:
                # A tag only a model read (e.g. off a drawing) and no register confirms.
                self._gap("unextracted", e.subject,
                          f"tag '{e.subject}' appears only in model-read evidence "
                          f"({', '.join(sorted({c.source_id for c in e.facts.values()}))}) and in no register; "
                          f"it is not added to the model", "info")

    # ------------------------------------------------------------------ B1 blocks
    def _kind_text(self, e: Entity) -> str:
        explicit = e.text("type") or e.text("kind")
        if explicit:
            return explicit
        owner = e.text("ownership").lower()
        cls = "manual" if any(w in owner for w in MANUAL_WORDS) else ("automated" if owner else "")
        noun = singular(e.sheet or "element").lower()
        return f"{cls} {noun}".strip()

    def build_blocks(self) -> None:
        for key in self.part_keys:
            e = self.entities[key]
            bid = ident(e.subject)
            kind = self._kind_text(e)
            name = e.text("name") or kind
            description = "; ".join(x for x in (e.text("kind") if e.text("type") else "", e.text("comments"),
                                                e.text("notes")) if x) or None
            everything = " ".join(str(c.value) for c in e.facts.values() if isinstance(c.value, str)).lower()
            ownership = " ".join((e.text("ownership"), e.text("controlsource"))).lower()
            manual = any(w in ownership for w in MANUAL_WORDS)
            # A controller's behaviour is realised by build_behaviour()'s state machine, a
            # different code path with its own Modelica emission (_emit_controller). Letting it
            # ALSO enter the L0/L1/L2 binding cascade as ordinary equipment asks that cascade to
            # invent physics for something that has none of its own -- L2 duly synthesised a
            # controller out of two equations, one of them referencing a member no plain
            # RealInput has.
            is_controller = "controller" in kind.lower()
            physical_only = manual or is_controller or any(w in everything for w in PHYSICAL_ONLY_WORDS)
            params = self._block_parameters(e, bid)
            for c in e.facts.values():
                if isinstance(c.value, str):
                    for m in re.finditer(r"\binitial\s+(?P<var>[A-Za-z_]\w*)\s*=\s*(?P<num>[-+]?\d*\.?\d+)", c.value, re.I):
                        self.initials[bid].append((m.group("var"), float(m.group("num")), c))
            block = Block(
                id=bid, name=name, kind=kind,
                domains=infer_domains(kind, name),  # type: ignore[arg-type]
                parameters=params, description=description, physical_only=physical_only,
                provenance=Provenance(
                    claim_ids=e.claim_ids,
                    note="manual/local device: architecture only, never a controller output" if manual else None,
                ),
            )
            self.m.blocks.append(block)
            self._legacy_merge(e, block)

    def _block_parameters(self, e: Entity, bid: str) -> list[Parameter]:
        # Bookkeeping columns (a source line number, a row index) are numbers, not properties.
        skip = {"value", "unit", "range", "priority", "revision", "line", "row", "index", "page", "no", "number"}
        out: list[Parameter] = []
        for pkey, c in e.facts.items():
            if pkey in skip or not isinstance(c.value, (int, float)) or isinstance(c.value, bool):
                continue
            words = re.findall(r"[a-z]+", str(c.predicate).lower())
            if c.extracted_by != "t0_deterministic" and (len(words) > 3 or set(words) & _VERBS):
                continue
            pname = ident(str(c.predicate).lower())
            value, unit, note = to_si(c.value, c.unit, temperature="temp" in pname or "cool" in pname)
            out.append(Parameter(id=f"{bid}.{pname}", name=pname, quantity=Quantity(value=value, unit=unit),
                                 scope=bid, provenance=Provenance(claim_ids=[c.id], note=note)))
        return out

    def _legacy_merge(self, e: Entity, block: Block) -> None:
        """F3: a legacy model that merges this part into another does not remove it physically."""
        for c in e.facts.values():
            if not isinstance(c.value, str):
                continue
            m = re.search(r"\b(integrated|combined|merged|lumped)\s+(with|into)\s+([A-Z]{1,4}[-_]?\d{1,4})", c.value, re.I)
            if not m or not re.search(r"legacy|simulation|model", c.value, re.I):
                continue
            support = [x for x in e.facts.values() if x is not c and isinstance(x.value, str)
                       and re.search(r"physical|exists|separate|distinct", x.value, re.I)]
            did = f"DER-ABS-{sum(1 for d in self.decisions if d.id.startswith('DER-ABS')) + 1:02d}"
            self.decisions.append(DecisionRecord(
                id=did, subject=block.id, predicate="exists_as_part",
                winner_claim_id=(support[0] if support else c).id,
                loser_claim_ids=[c.id] if support else [],
                rule_id="D-abstraction-not-architecture",
                rationale=(f"{c.ref()} says a legacy/simulation model {m.group(1).lower()} {block.id} "
                           f"{m.group(2).lower()} {m.group(3)}; that is a modelling abstraction, not an "
                           f"architectural fact, so {block.id} stays a distinct part"
                           + (f" (corroborated by {support[0].ref()})" if support else "")),
                failure_mode="F3-simulation-abstraction-as-architecture",
            ))
            block.provenance.decision_ids.append(did)
            return

    # ------------------------------------------------------------------ B2 topology
    def build_topology(self) -> None:
        edges = collect_edges(self.entities, self.topo.resolve)
        # A command or measurement is a signal-bundle interface whether or not both ends turned
        # out to be modeled parts -- a controller commanding a real valve is still a Boolean
        # open/close signal, not a structural connection, and routing it as one collided its
        # path id with the valve's real fluid path (same id, two Block instances) once the
        # controller itself was no longer mis-typed as architecture-only.
        bus = [e for e in edges if is_signal_medium(e.medium)]
        physical = [e for e in edges if e not in bus]
        if bus:
            self._gap("deviation", "controller interfaces",
                      f"{len(bus)} signal-bundle interface(s) ({', '.join(e.id for e in bus)}) are realised "
                      f"as sensor/actuator signals bound to the plant, not as structural connections", "info")

        self.routes = self.topo.paths(physical)
        for r in self.routes:
            for end in (r.src, r.dst):
                if self.m.block(ident(end)) is None:
                    self._boundary(end, r)
            src, dst = ident(r.src), ident(r.dst)
            domain = self._medium_domain(r.medium, src)
            if r.hops:
                pid = r.id
                pumped = any("pump" in (self.m.block(ident(h)).kind.lower() if self.m.block(ident(h)) else "")
                             for h in r.hops)
                self.m.blocks.append(Block(
                    id=pid, name=f"{r.src} to {r.dst}",
                    kind="pumped path" if pumped else "transfer path",
                    domains=[domain],  # type: ignore[list-item]
                    ports=[Port(id="port_a", name="port_a", domain=domain, direction="in"),  # type: ignore[arg-type]
                           Port(id="port_b", name="port_b", domain=domain, direction="out")],  # type: ignore[arg-type]
                    description=f"{r.src} to {r.dst}; series group: {', '.join(r.elements)}",
                    provenance=Provenance(claim_ids=r.claim_ids, decision_ids=list(r.decision_ids),
                                          note="lumped path: every series element must be open for flow"),
                ))
                a = self._port(src, r.src_port, "out", domain)
                b = self._port(dst, r.dst_port, "in", domain)
                self._connect(f"C_{pid}_a", f"{src}.{a}", f"{pid}.port_a", domain, r, [])
                self._connect(f"C_{pid}_b", f"{pid}.port_b", f"{dst}.{b}", domain, r, r.elements)
                for el in r.elements:
                    blk = self.m.block(ident(el))
                    if blk is not None and not blk.physical_only and blk.abstracted_into is None:
                        blk.abstracted_into = pid
                    self.path_of.setdefault(el, r)
            else:
                a = self._port(src, r.src_port, "out", domain)
                b = self._port(dst, r.dst_port, "in", domain)
                self._connect(r.id, f"{src}.{a}", f"{dst}.{b}", domain, r, r.elements)
        for bid, ports in self.ports.items():
            if (blk := self.m.block(bid)) is not None:
                blk.ports.extend(ports)
        self._corroborate_edges()

    def _boundary(self, name: str, route: Route) -> None:
        bid = ident(name)
        self.m.blocks.append(Block(
            id=bid, name=name, kind="external boundary",
            domains=infer_domains(route.medium, name),  # type: ignore[arg-type]
            description=f"named as a connection endpoint ({', '.join(e.id for e in route.edges)}) but "
                        f"not listed as equipment: treated as a supply/sink at the system boundary",
            physical_only=True,
            provenance=Provenance(claim_ids=route.claim_ids, note="boundary inferred from a connection record"),
        ))

    def _medium_domain(self, medium: str | None, fallback_block: str) -> str:
        doms = infer_domains(medium)
        if "fluid" in doms:
            return "fluid"
        if doms != ["unknown"]:
            return doms[0]
        blk = self.m.block(fallback_block)
        return next((d for d in (blk.domains if blk else []) if d != "unknown"), "unknown")

    def _port(self, bid: str, label: str | None, direction: str, domain: str) -> str:
        base = ident((label or f"port_{direction}").lower())
        used = [p for p in self.ports[bid] if p.id == base or p.id.startswith(f"{base}_")]
        pid = base if not used else f"{base}_{len(used) + 1}"
        desc = label if not used else f"{label}: another stream through the same physical opening"
        self.ports[bid].append(Port(id=pid, name=pid, domain=domain, direction=direction, description=desc))  # type: ignore[arg-type]
        return pid

    def _connect(self, cid: str, src: str, dst: str, domain: str, r: Route, series: list[str]) -> None:
        self.m.connections.append(Connection(
            id=cid, source=src, target=dst, domain=domain, medium=r.medium,  # type: ignore[arg-type]
            series_elements=list(series),
            description="; ".join(f"{e.id}: {e.note}" for e in r.edges if e.note) or None,
            provenance=Provenance(claim_ids=r.claim_ids, decision_ids=list(r.decision_ids)),
        ))

    def _corroborate_edges(self) -> None:
        """Drawing and diagram edges corroborate the register's topology; alone they never create it
        when a connection register exists, because a drawing is not a routing authority (F2)."""
        uncorroborated: list[str] = []
        for c in connects_to_claims(self.claims):
            a, b = self.topo.resolve(str(c.subject)), self.topo.resolve(str(c.value))
            if not a or not b:
                continue
            route = next((r for r in self.routes
                          if a in (r.src, *r.elements) and b in (r.dst, *r.elements) and a != b), None)
            if route is not None:
                for conn in self.m.connections:
                    ends = {conn.source.split(".")[0], conn.target.split(".")[0]}
                    if route.id in ends or ends == {ident(route.src), ident(route.dst)}:
                        if c.id not in conn.provenance.claim_ids:
                            conn.provenance.claim_ids.append(c.id)
            elif self.routes:
                uncorroborated.append(f"{a}->{b} ({c.source_id})")
            elif self.m.block(ident(a)) and self.m.block(ident(b)):
                ra, rb = ident(a), ident(b)
                pa = self._port(ra, None, "out", "unknown")
                pb = self._port(rb, None, "in", "unknown")
                for bid, pid in ((ra, pa), (rb, pb)):
                    blk = self.m.block(bid)
                    if blk is not None:
                        blk.ports.append(next(p for p in self.ports[bid] if p.id == pid))
                self.m.connections.append(Connection(
                    id=f"C_{ra}_{rb}", source=f"{ra}.{pa}", target=f"{rb}.{pb}",
                    provenance=Provenance(claim_ids=[c.id], note="from a drawing edge: no connection register"),
                ))
        if uncorroborated:
            self._gap("unresolved_conflict", "drawing topology",
                      f"{len(uncorroborated)} edge(s) read from drawings/legacy models are not in the connection "
                      f"register and were not modelled: {', '.join(uncorroborated[:12])}", "info")

    # ------------------------------------------------------------------ B3 signals
    def build_signals(self) -> None:
        for key in sorted(self.instrument_keys, key=lambda k: self.entities[k].order()):
            e = self.entities[key]
            sid = ident(e.subject)
            loc_tags = find_tags(e.text("location"), self.known)
            loc = ident(loc_tags[0]) if loc_tags else None
            exact = loc is not None and norm(e.text("location")) == norm(loc_tags[0])
            var = measurement_var(e.text("measurement"))
            raw_unit = e.text("unit") or None
            _, unit, _ = to_si(1.0, raw_unit, temperature="temp" in e.text("measurement").lower())
            blk = self.m.block(loc) if loc else None
            binding = f"{loc}.{var}" if (exact and blk and var and not blk.physical_only
                                         and blk.abstracted_into is None) else None
            if binding is None:
                why = ("its location is not a modelled part" if not exact or blk is None else
                       "its part is not in the executable model" if blk.physical_only or blk.abstracted_into else
                       f"measurement '{e.text('measurement')}' has no conventional variable")
                self._gap("unextracted", sid, f"sensor {e.subject} at '{e.text('location')}' is left unbound: {why}", "info")
            use = " ".join((e.text("use"), e.text("notes"))).lower()
            owner = ("controller" if ("controller" in use or "interlock" in use) else
                     "monitoring" if ("monitor" in use or "protection" in use) else "unknown")
            sig = Signal(
                id=sid, name=sid, role="sensor",
                datatype="boolean" if re.search(r"digital|discrete|switch", e.text("medium"), re.I) else "real",
                unit=unit, binding=binding, owner=owner, range=self._range(e.text("range"), raw_unit, e),  # type: ignore[arg-type]
                provenance=Provenance(claim_ids=e.claim_ids),
            )
            self.m.signals.append(sig)
            self.signal_block[sid] = loc

        # Actuators: every automated owned device. A manual one is never a controller output (F5).
        for key in self.part_keys:
            e = self.entities[key]
            blk = self.m.block(ident(e.subject))
            if blk is None or blk.physical_only or not e.has("ownership"):
                continue
            self._actuator(e.subject, e.claim_ids, datatype="boolean" if re.search(
                r"bool|on/off|discrete", " ".join((e.text("action"), e.text("ownership"))), re.I) else "real")

        # Anything the sequence commands becomes an actuator too, before interlocks look for them.
        for row in step_rows(self.entities):
            self.actions_for(row.action)

    def _actuator(self, target: str, claim_ids: list[str], *, datatype: str = "boolean",
                  binding: str | None = None) -> Signal:
        name = f"cmd_{ident(target)}"
        sig = self.m.signal(name)
        if sig is None:
            sig = Signal(id=name, name=name, role="actuator", datatype=datatype, binding=binding,  # type: ignore[arg-type]
                         owner="controller", provenance=Provenance(claim_ids=list(claim_ids)))
            self.m.signals.append(sig)
        return sig

    def _range(self, text: str, unit: str | None, e: Entity) -> tuple[float, float] | None:
        m = re.match(r"^\s*([-+]?\d*\.?\d+)\s*(?:\.\.|-|to|–)\s*([-+]?\d*\.?\d+)", text or "")
        if not m:
            return None
        temp = "temp" in e.text("measurement").lower()
        lo, _, _ = to_si(float(m.group(1)), unit, temperature=temp)
        hi, _, _ = to_si(float(m.group(2)), unit, temperature=temp)
        return (float(lo), float(hi))

    def actions_for(self, text: str) -> tuple[dict[str, str], list[str]]:
        """'V8=OPEN', 'P2=ON + return valve group', 'B5_Heater=ON' -> {signal: 'true'}."""
        actions: dict[str, str] = {}
        unresolved: list[str] = []
        group_parts: list[str] = []
        commanded: list[str] = []
        for part in re.split(r"\s*(?:\+|;|,|\band\b)\s*", text or ""):
            part = part.strip()
            if not part:
                continue
            if re.search(r"\bgroup\b", part, re.I):
                group_parts.append(part)
                continue
            m = re.match(r"^(?P<t>[A-Za-z][\w\-]*)\s*=\s*(?P<v>\w+)$", part)
            if not m:
                if not re.search(r"\b(closed|off|no|none|wait|idle|hold)\b", part, re.I):
                    unresolved.append(part)
                continue
            if m.group("v").lower() not in ("open", "on", "true", "1", "start", "run", "enable", "enabled"):
                continue
            target = m.group("t")
            sig = self._command(target)
            if sig is None:
                unresolved.append(part)
                continue
            actions[sig.name] = "true"
            if (tag := self.topo.resolve(target)) is not None:
                commanded.append(tag)
        for part in group_parts:
            members: list[str] = []
            for gm in GROUP_REF.finditer(part):
                owner = self.topo.resolve(gm.group("owner"))
                if owner:
                    members += self.topo.group_members(owner, self.routes, context=part)[0]
            if not members:
                # 'return valve group' with no owner: the group of the path this step drives.
                route = next((self.path_of[t] for t in commanded if t in self.path_of), None)
                members = list(route.elements) if route else []
            if not members:
                unresolved.append(part)
            for tag in members:
                sig = self._command(tag)
                if sig is not None:
                    actions[sig.name] = "true"
        return actions, unresolved

    def _command(self, target: str) -> Signal | None:
        tag = self.topo.resolve(target)
        if tag is not None:
            blk = self.m.block(ident(tag))
            if blk is not None and blk.physical_only:
                return None
            ent = self.entities.get(norm(tag))
            return self._actuator(tag, ent.claim_ids if ent else [])
        m = re.match(r"^(?P<tag>[A-Za-z]{1,4}-?\d{1,4})_(?P<fn>[A-Za-z]\w*)$", target)
        if m and (owner := self.topo.resolve(m.group("tag"))) and self.m.block(ident(owner)):
            return self._actuator(target, [], binding=f"{ident(owner)}.{m.group('fn').lower()}")
        return None

    # ------------------------------------------------------------------ B4 behaviour
    def build_behaviour(self) -> None:
        param_scope: dict[str, str | None] = {}
        for p in self.m.parameters:
            ent = self.entities.get(norm(p.id))
            scope = ent.text("scope") if ent else ""
            tag = self.topo.resolve(scope) if scope else None
            param_scope[p.id] = ident(tag) if tag else None
        self.parser = GuardParser(self.m.signals, self.m.parameters, param_scope=param_scope,
                                  signal_block=self.signal_block, complete=self._completion)
        active = {r.id: r.text for r in self.m.requirements if r.status == "active"}
        actuators = [s for s in self.m.signals if s.role == "actuator"]
        self.m.interlocks, il_gaps = build_interlocks(
            interlock_evidence(self.claims, active), self.parser, actuators, self.known)
        self.gaps += il_gaps

        res = build_state_machine(step_rows(self.entities), self.parser, self.actions_for, name="Controller")
        self.gaps += res.gaps
        self.comparisons = res.comparisons
        if res.machine is not None:
            self.m.state_machines = [res.machine]

    def _completion(self, who: str) -> tuple[str, str] | None:
        """'B6 return complete' -> the transfer out of B6 has drained it to where its own interlock
        would stop it. Derived only when that interlock exists; otherwise the clause stays open."""
        tag = self.topo.resolve(who)
        if tag is None:
            return None
        bid = ident(tag)
        level = next((s for s in self.m.signals if s.role == "sensor" and s.binding == f"{bid}.level"), None)
        if level is None:
            return None
        for r in self.routes:
            if ident(r.src) != bid:
                continue
            for el in r.elements:
                for il in self.m.interlocks:
                    if il.actuator != f"cmd_{ident(el)}" or il.sense != "permissive":
                        continue
                    m = re.fullmatch(rf"{re.escape(level.name)} (>|>=) (\S+)", il.condition.strip())
                    if m:
                        expr = negate_comparison(il.condition)
                        if expr:
                            return expr, (f"the transfer out of {bid} ends where its own interlock "
                                          f"{il.id} ({il.condition}) stops {el}")
        return None

    # ------------------------------------------------------------------ B5 scenario
    def build_scenario(self) -> None:
        title = _procedure_title(self.docs)
        scenario, gaps = build_scenario(
            self.claims, title, self.m.state_machines[0] if self.m.state_machines else None,
            self.comparisons, {s.name: s for s in self.m.signals}, self.initials,
        )
        self.m.scenarios = [scenario]
        self.gaps += gaps

    # ------------------------------------------------------------------ traceability
    def link_requirements(self) -> None:
        """Requirement -> the elements that realise it, from what the requirement text names.

        Behaviour first: a transition whose guard compares a sensor the requirement names (or a
        sensor on a part it names) against a number *and unit* the requirement states, or whose
        source step commands an element the requirement names; an interlock the requirement
        stated or whose actuator and sensor it names; fork/join transitions for requirements
        about parallel branches. Structure otherwise: a path whose source the text routes
        *from* and whose destination it names, then parts and signals it names. Verification
        requirements are realised by the acceptance scenario. Superseded requirements are never
        satisfied: they are carried for traceability, not built.
        """
        sm = self.m.state_machines[0] if self.m.state_machines else None
        signal_keys = {norm(s.id): s for s in self.m.signals if s.role == "sensor"}
        for req in self.m.requirements:
            if req.status != "active":
                continue
            text = req.text
            tags = {norm(m.group(0)) for m in TAG_RE.finditer(text)}
            numbers = _numbers(text)
            blocks = {b.id for b in self.m.blocks if norm(b.id) in tags}
            links: list[tuple[Any, str]] = []

            if re.search(r"verif|acceptance|simulation", f"{req.category or ''} {req.id}", re.I) \
                    and re.search(r"\b(acceptance|simulation|run|test)\b", text, re.I):
                for sc in self.m.scenarios:
                    links.append((sc, sc.id))
            elif sm is not None:
                for t in sm.transitions:
                    src = sm.state(t.source_state)
                    commanded = list(src.actions) if src else []
                    for sig, _op, val, unit in self.comparisons.get(t.id, []):
                        named = (norm(sig) in tags or self.signal_block.get(sig) in blocks
                                 or (sig == "time" and re.search(r"\btime\b", text, re.I)))
                        if not named:
                            continue
                        number = any(abs(val - n) <= 1e-9 * max(1.0, abs(n)) and (u is None or unit is None or u == unit)
                                     for n, u in numbers)
                        drives = norm(sig) in tags and any(_actuator_named(a, tags, text) for a in commanded)
                        if number or drives:
                            links.append((t, f"{sm.id}.{t.id}"))
                            break
                    if t.forks and re.search(r"\b(split|fork|concurrent)\b", text, re.I):
                        links.append((t, f"{sm.id}.{t.id}"))
                    if t.joins and re.search(r"\b(join|rejoin)\b|\bboth\b.*\bcomplete", text, re.I):
                        links.append((t, f"{sm.id}.{t.id}"))
            for il in self.m.interlocks:
                named_sensor = any(norm(x) in tags for x in re.findall(r"[A-Za-z]\w*", il.condition))
                if req.id in il.provenance.requirement_ids or (_actuator_named(il.actuator, tags, text) and named_sensor):
                    links.append((il, il.id))
            if not links:
                for r in self.routes:
                    if not r.hops or norm(r.dst) not in tags:
                        continue
                    via = any(norm(el) in tags for el in r.elements)
                    if via or _routes_from(text, r.src):
                        blk = self.m.block(r.id)
                        if blk is not None:
                            links.append((blk, blk.id))
                        links += [(c, c.id) for c in self.m.connections if c.id.startswith(f"C_{r.id}_")]
                links += [(b, b.id) for b in self.m.blocks if b.id in blocks]
                links += [(s, s.id) for k, s in signal_keys.items() if k in tags]
                links += [(s, s.id) for s in self.m.signals
                          if s.role == "actuator" and _actuator_named(s.name, tags, text)]
            if not links and (m := re.search(r"\ball\s+(automated\s+)?(?:\w+\s+)?(\w+?)s\b", text, re.I)):
                # 'All automated process valves shall ...': a property of every part of that kind.
                noun = m.group(2).lower()
                links += [(b, b.id) for b in self.m.blocks
                          if noun in b.kind.lower() and not (m.group(1) and b.physical_only)]
            seen: list[str] = []
            for element, eid in links:
                if eid in seen:
                    continue
                seen.append(eid)
                if req.id not in element.provenance.requirement_ids:
                    element.provenance.requirement_ids.append(req.id)
            req.satisfied_by = sorted(seen)
            if seen:
                req.provenance.note = "satisfied_by derived from the tags and values the requirement text names"
        if sm is not None:
            sm.provenance.requirement_ids = sorted({r for t in sm.transitions for r in t.provenance.requirement_ids})
            for sc in self.m.scenarios:
                for chk in sc.checks:
                    t = next((t for t in sm.transitions
                              if chk.provenance.note == f"derived from transition {t.id}"), None)
                    if t is not None:
                        chk.requirement_ids = list(t.provenance.requirement_ids)

    # ------------------------------------------------------------------ helpers
    def _gap(self, kind: str, subject: str, detail: str, severity: str = "warn") -> None:
        self.gaps.append(Gap(id=f"GAP-ASM-{len(self.gaps) + 1:03d}", kind=kind, subject=subject,  # type: ignore[arg-type]
                             detail=detail, severity=severity))  # type: ignore[arg-type]


_VERBS = {"is", "are", "be", "was", "shall", "must", "may", "should", "equals", "equal", "stated",
          "requires", "require", "has", "have", "gets", "means", "remains", "does", "do", "not"}


def _numbers(text: str) -> list[tuple[float, str | None]]:
    """Every number in a requirement with its unit, both as written and converted to SI."""
    out: list[tuple[float, str | None]] = []
    for m in re.finditer(r"(?<![A-Za-z\d-])([-+]?\d[\d,]*\.?\d*)\s*(degC|°C|deg\s*C|[A-Za-z/%()^0-9]*)", text or ""):
        try:
            raw = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        unit = m.group(2).replace(" ", "") or None
        if unit and not re.fullmatch(r"[A-Za-z°/%()^0-9]{1,8}", unit):
            unit = None
        conv, si, _ = to_si(raw, unit, temperature=bool(unit and unit.lower() in ("degc", "°c", "c")))
        out.append((raw, unit if si == unit else None))
        if isinstance(conv, (int, float)):
            out.append((float(conv), si))
    return out


def _actuator_named(name: str, tags: set[str], text: str) -> bool:
    """Does the text name this actuator? 'cmd_P1' needs P1; 'cmd_B5_Heater' needs B5 *and* heat-."""
    stem = name.removeprefix("cmd_")
    parts = stem.split("_")
    if norm(stem) in tags:
        return True
    if len(parts) > 1 and norm(parts[0]) in tags:
        low = text.lower()
        return all(p.lower()[:4] in low for p in parts[1:] if p)
    return False


def _routes_from(text: str, src: str) -> bool:
    """'... from B1 and B2', 'stream from B6': the text routes something out of `src`."""
    for m in re.finditer(r"\bfrom\s+((?:(?:the\s+)?[A-Z]{1,4}[-_]?\d{1,4}(?:\s*(?:,|and|or)\s*)?)+)", text):
        if norm(src) in {norm(t.group(0)) for t in TAG_RE.finditer(m.group(1))}:
            return True
    return False


def _build_requirements(
    winners: dict[tuple[str, str], EvidenceClaim], claims: list[EvidenceClaim]
) -> list[Requirement]:
    by_subject: dict[str, dict[str, EvidenceClaim]] = defaultdict(dict)
    for (subject, predicate), claim in winners.items():
        by_subject[subject][predicate] = claim

    out: list[Requirement] = []
    for subject, facts in sorted(by_subject.items()):
        text_claim = facts.get("requirement")
        if text_claim is None or text_claim.extracted_by != "t0_deterministic" and not looks_like_tag(text_claim.subject):
            continue
        status_raw = str(facts["status"].value).lower() if "status" in facts else "active"
        superseded_by = facts.get("supersededby") or facts.get("superseded_by")
        out.append(
            Requirement(
                id=str(text_claim.subject),
                text=str(text_claim.value),
                category=str(facts["kind"].value) if "kind" in facts else None,
                priority=_priority(facts),
                status="superseded" if "supersed" in status_raw else "active",
                superseded_by=str(superseded_by.value) if superseded_by else None,
                authority=str(facts["authority"].value) if "authority" in facts else None,
                verification_method=str(facts["verification"].value) if "verification" in facts else None,
                provenance=Provenance(claim_ids=[c.id for c in facts.values()]),
            )
        )
    return out


def _build_parameters(
    winners: dict[tuple[str, str], EvidenceClaim], claims: list[EvidenceClaim]
) -> list[Parameter]:
    by_subject: dict[str, dict[str, EvidenceClaim]] = defaultdict(dict)
    for (subject, predicate), claim in winners.items():
        by_subject[subject][predicate] = claim

    out: list[Parameter] = []
    for subject, facts in sorted(by_subject.items()):
        value_claim = facts.get("value")
        if value_claim is None or not isinstance(value_claim.value, (int, float)) or isinstance(value_claim.value, bool):
            continue
        unit = value_claim.unit or (str(facts["unit"].value) if "unit" in facts else None)
        if unit is None and re.search(r"\s", str(value_claim.subject).strip()):
            # 'Automated valves | 15' in a summary sheet is a count about the packet, not a
            # parameter of the system: no identifier, no unit.
            continue
        text = str(facts["name"].value) if "name" in facts else None
        temperature = bool(text and re.search(r"temp|cool|heat", text, re.I))
        value, si_unit, note = to_si(value_claim.value, unit, temperature=temperature)
        status_raw = str(facts["status"].value).lower() if "status" in facts else "effective"
        scope = str(facts["scope"].value) if "scope" in facts else None
        out.append(
            Parameter(
                id=str(value_claim.subject),
                name=ident(str(value_claim.subject)),
                quantity=Quantity(value=value, unit=si_unit),
                # Setpoints are controller parameters even when they concern one part; the part
                # they concern is kept in the description and used to disambiguate guards.
                scope="global",
                description="; ".join(x for x in (text, f"applies to {scope}" if scope else None) if x) or None,
                status="superseded" if "supersed" in status_raw else "effective",
                provenance=Provenance(claim_ids=[c.id for c in facts.values()], note=note),
            )
        )
    return out


def _unassembled_gaps(winners: dict[tuple[str, str], EvidenceClaim], model: SystemModel) -> list[Gap]:
    """Say out loud how much resolved evidence did not end up in any IR element."""
    used: set[str] = set()
    for coll in (model.requirements, model.parameters, model.blocks, model.connections, model.signals,
                 model.interlocks, model.state_machines, model.scenarios):
        for el in coll:
            used.update(el.provenance.claim_ids)
    for b in model.blocks:
        for p in b.parameters:
            used.update(p.provenance.claim_ids)
    for sm in model.state_machines:
        for x in (*sm.states, *sm.transitions):
            used.update(x.provenance.claim_ids)
    for d in model.decisions:
        used.add(d.winner_claim_id)
        used.update(d.loser_claim_ids)
    unused: Counter[str] = Counter()
    for claim in winners.values():
        if claim.id not in used and claim.kind not in ("note", "supersession", "domain_hint"):
            unused[claim.kind] += 1
    return [
        Gap(
            id=f"GAP-UNUSED-{i:02d}",
            kind="unextracted",
            subject=kind,
            detail=f"{count} resolved '{kind}' claim(s) are not traced into any IR element",
            severity="warn" if kind in ("component", "connection", "state", "transition", "signal") else "info",
        )
        for i, (kind, count) in enumerate(sorted(unused.items()), 1)
    ]


def _priority(facts: dict[str, EvidenceClaim]) -> str:
    raw = str(facts["priority"].value).lower() if "priority" in facts else ""
    for p in ("must", "should", "may"):
        if p in raw:
            return p
    return "unknown"


_TITLE_ID = re.compile(r"\b[A-Z]{2,}-\d{2,}\b")


def _procedure_title(docs: list[Document]) -> str | None:
    """The title line of the acceptance procedure, wherever it happens to sit.

    Do NOT assume the title is the first block. Adapters legitimately reorder: the PDF reader
    emits a page's tables before its prose, so the first non-empty block of the acceptance
    procedure is a table header ("Item | Initial condition") and the real title sits third.
    Reading block[0] gave the scenario the id SCN-01 instead of BAT-09, and it was an adapter
    change on another branch -- not this code -- that moved it.

    So: look for a line carrying a record id anywhere in the document, preferring prose over
    tables, and fall back to the first non-empty line only if nothing matches.
    """
    for doc in docs:
        if doc.source.authority != AuthorityClass.TEST_PROCEDURE or not doc.blocks:
            continue
        prose = [b for b in doc.blocks if b.kind in ("heading", "paragraph")]
        for block in (*prose, *doc.blocks):
            for line in block.text.splitlines():
                if _TITLE_ID.search(line):
                    return line.strip()
        return next((b.text.splitlines()[0] for b in doc.blocks if b.text.strip()), None)
    return None


def _infer_name(docs: list[Document]) -> str:
    """The system name most document titles agree on: 'Spec - NaCl Evaporation Plant, Rev A'."""
    votes: Counter[str] = Counter()
    for d in docs:
        first = next((b.text.strip().splitlines()[0] for b in d.blocks if b.text and b.text.strip()), "")
        if " - " not in first:
            continue
        tail = first.split(" - ", 1)[1]
        tail = re.split(r",?\s*\bRev(?:ision)?\b", tail)[0].strip(" ,")
        if 3 <= len(tail) <= 60 and not re.fullmatch(r"[A-Z]?\d*", tail):
            votes[tail] += 1
    if votes:
        best = votes.most_common(1)[0][0]
        return "".join(w[:1].upper() + w[1:] for w in re.findall(r"[A-Za-z0-9]+", best))
    for d in docs:
        for b in d.blocks:
            if b.kind == "heading" and len(b.text) > 8:
                return ident(b.text[:60])
    return "ExtractedSystem"
