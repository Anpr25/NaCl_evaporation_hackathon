"""Connection records -> transfer paths with their series element groups (backlog B2).

A register describes plumbing (or wiring) hop by hop: B6 -> P2, P2 -> B1. The model wants it
node to node: B6 -> B1, through {P2, ...}. This module walks the hops, collapses every element
that merely sits *in series* on the way (valves, pumps, breakers, clutches), and records those
elements, in order, on the resulting connection.

Three sources of series membership, strongest first:

  1. the chain itself        -- the element is a hop on the path (P2);
  2. a direct mention        -- the hop's own note names the element ('uses V20/V24/V25');
  3. a named group           -- the note names a *group* ('plus B1 routing group'), resolved
                                from wherever the packet spells that group's members out.

Named groups are where routing traps live. A superseded record can still be the only place a
group's members are listed; using it for *membership* is sound because a change record that
re-pairs branches with destinations does not move valves. Every such derivation is written
down as a DecisionRecord so a reviewer can check the reasoning, and an unresolvable group is a
declared Gap, never a guess.

Owner: B.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from ..ir.evidence import DecisionRecord, EvidenceClaim, Gap
from .entities import (
    SERIES_WORDS,
    SIGNAL_MEDIUM_WORDS,
    TAG_RE,
    Entity,
    claims_text,
    find_tags,
    ident,
    norm,
)


@dataclass
class Edge:
    """One hop from a connection record."""

    id: str
    src: str
    dst: str
    src_port: str | None = None
    dst_port: str | None = None
    medium: str | None = None
    note: str = ""
    claim_ids: list[str] = field(default_factory=list)
    order: tuple = ()


@dataclass
class Path:
    """Node-to-node route after collapsing series elements."""

    src: str
    dst: str
    src_port: str | None
    dst_port: str | None
    medium: str | None
    elements: list[str] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    decision_ids: list[str] = field(default_factory=list)
    #: The elements that are hops of the chain itself; the rest were named in notes. A path
    #: with no hops is a plain connection that merely has elements recorded on it.
    hops: list[str] = field(default_factory=list)

    @property
    def claim_ids(self) -> list[str]:
        return [cid for e in self.edges for cid in e.claim_ids]

    @property
    def id(self) -> str:
        if not self.hops:
            return f"C_{ident(self.src)}_{ident(self.dst)}"
        if len(self.elements) == 1:
            return f"L_{ident(self.elements[0])}"
        return f"L_{ident(self.src)}_{ident(self.dst)}"


_TAGLIST = r"[A-Z]{1,4}[-_]?\d{1,4}(?:\s*[/,]\s*[A-Z]{1,4}[-_]?\d{1,4})*"
#: '... -> V18/V23/V22 + V1/V3 -> B1': the group written last before the destination is the
#: destination's own group.
_ARROW_GROUP = re.compile(rf"(?P<g1>{_TAGLIST})\s*\+\s*(?P<g2>{_TAGLIST})\s*->\s*(?P<dest>[A-Z]{{1,4}}[-_]?\d{{1,4}})")
#: 'The B7/P1 return branch opens V18,V23,V22,V1,V3'
_BRANCH_OPENS = re.compile(rf"(?P<branch>{_TAGLIST})\s+(?:\w+\s+){{0,3}}?branch\s+opens\s+(?P<members>{_TAGLIST})", re.I)
#: 'P1/B7->B1'
_ROUTE = re.compile(rf"(?P<branch>{_TAGLIST})\s*->\s*(?P<dest>[A-Z]{{1,4}}[-_]?\d{{1,4}})")
#: 'plus B1 routing group', 'corrected B2 return valve group'
GROUP_REF = re.compile(r"(?P<owner>[A-Z]{1,4}[-_]?\d{1,4})\s+(?:[a-z]+\s+){0,3}?group\b", re.I)


def is_series_element(ent: Entity | None) -> bool:
    if ent is None:
        return False
    blob = " ".join(
        ent.text(p) for p in ("type", "kind", "name", "modelservice", "ownership")
    ).lower() + " " + (ent.sheet or "").lower()
    return any(w in blob for w in SERIES_WORDS)


def is_signal_medium(medium: str | None) -> bool:
    low = (medium or "").lower()
    return bool(low) and any(w in low for w in SIGNAL_MEDIUM_WORDS)


def collect_edges(entities: dict[str, Entity], resolve) -> list[Edge]:
    """Every entity that has both a `from` and a `to` fact is one hop."""
    edges: list[Edge] = []
    for ent in entities.values():
        src_c, dst_c = ent.get("from"), ent.get("to")
        if src_c is None or dst_c is None:
            continue
        src_raw, dst_raw = str(src_c.value).strip(), str(dst_c.value).strip()
        edges.append(
            Edge(
                id=ent.subject,
                src=resolve(src_raw) or src_raw,
                dst=resolve(dst_raw) or dst_raw,
                src_port=ent.text("fromport", "sourceport") or None,
                dst_port=ent.text("toport", "targetport") or None,
                medium=ent.text("medium", "itemmedium", "item") or None,
                note=" ".join(
                    ent.text(p) for p in ("constraintnote", "note", "notes", "constraint", "comments")
                ).strip(),
                claim_ids=ent.claim_ids,
                order=ent.order(),
            )
        )
    return sorted(edges, key=lambda e: e.order)


class TopologyBuilder:
    """Walks hops into paths and resolves their series groups."""

    def __init__(self, entities: dict[str, Entity], claims: list[EvidenceClaim]) -> None:
        self.entities = entities
        self.claims = claims
        self.known: dict[str, str] = {k: e.subject for k, e in entities.items() if TAG_RE.fullmatch(e.subject)}
        self.decisions: list[DecisionRecord] = []
        self.gaps: list[Gap] = []
        self._seq = 0

    def resolve(self, name: str) -> str | None:
        return self.known.get(norm(name))

    def entity(self, tag: str) -> Entity | None:
        return self.entities.get(norm(tag))

    def inline(self, node: str) -> bool:
        return node in self.known.values() and is_series_element(self.entity(node))

    # ------------------------------------------------------------------ walk
    def paths(self, edges: list[Edge]) -> list[Path]:
        outgoing: dict[str, list[Edge]] = {}
        for e in edges:
            outgoing.setdefault(e.src, []).append(e)

        out: list[Path] = []
        for start in edges:
            if self.inline(start.src):
                continue
            chain, elements, cur, seen = [start], [], start, {start.src}
            ok = True
            while self.inline(cur.dst):
                if cur.dst in seen:
                    ok = False
                    break
                seen.add(cur.dst)
                elements.append(cur.dst)
                nxt = outgoing.get(cur.dst, [])
                if len(nxt) != 1:
                    ok = False
                    break
                cur = nxt[0]
                chain.append(cur)
            if not ok:
                self._gap(
                    "unresolved_conflict", cur.dst,
                    f"series element '{cur.dst}' on the route starting at {start.id} has "
                    f"{len(outgoing.get(cur.dst, []))} onward hop(s); cannot collapse it into one path",
                )
                continue
            medium = next((e.medium for e in chain if e.medium), None)
            out.append(Path(start.src, cur.dst, start.src_port, cur.dst_port, medium, elements, chain,
                            hops=list(elements)))

        # direct mentions first, for every path: the group resolver needs them all.
        for p in out:
            for e in p.edges:
                for tag in find_tags(_without_group_refs(e.note), self.known):
                    if tag not in p.elements and tag not in (p.src, p.dst) and self.inline(tag):
                        p.elements.append(tag)
        for p in out:
            for e in p.edges:
                for m in GROUP_REF.finditer(e.note):
                    owner = self.resolve(m.group("owner"))
                    if owner is None:
                        continue
                    members, did = self.group_members(owner, out, context=f"{p.src}->{p.dst}")
                    if did:
                        p.decision_ids.append(did)
                    for tag in members:
                        if tag not in p.elements:
                            p.elements.append(tag)
        return out

    # ------------------------------------------------------------------ named groups
    def group_members(self, owner: str, paths: list[Path], *, context: str = "") -> tuple[list[str], str | None]:
        """Members of '<owner> ... group', with the DecisionRecord id that justifies them."""
        cache = getattr(self, "_groups", {})
        self._groups = cache
        if owner in cache:
            return cache[owner]

        texts = list(claims_text(self.claims))

        # (a) explicit: '... + V1/V3 -> B1'
        for claim, text in texts:
            for m in _ARROW_GROUP.finditer(text):
                if self.resolve(m.group("dest")) != owner:
                    continue
                members = [t for t in find_tags(m.group("g2"), self.known) if self.inline(t)]
                if members:
                    did = self._decide(
                        owner, claim, [],
                        f"'{owner}' group is {', '.join(members)}: {claim.ref()} lists that group as "
                        f"the last one before '-> {owner}'. Valve membership is physical, so it holds "
                        f"even where the same sentence's branch pairing was later superseded.",
                    )
                    cache[owner] = (members, did)
                    return cache[owner]

        # (b) set difference: a branch's full valve list, minus the pump-side valves the current
        #     record keeps with that pump, leaves the destination-side group -- and the legacy
        #     route says which destination that branch served.
        pump_side: dict[str, list[str]] = {}
        for p in paths:
            for e in p.edges:
                direct = [t for t in find_tags(_without_group_refs(e.note), self.known) if self.inline(t)]
                for el in p.elements:
                    if el in (e.src, e.dst) and direct:
                        pump_side.setdefault(el, [])
                        pump_side[el] += [t for t in direct if t not in pump_side[el]]
        routes: list[tuple[set[str], str, EvidenceClaim]] = []
        for claim, text in texts:
            for m in _ROUTE.finditer(text):
                branch = set(find_tags(m.group("branch"), self.known))
                dest = self.resolve(m.group("dest"))
                if branch and dest:
                    routes.append((branch, dest, claim))
        for claim, text in texts:
            for m in _BRANCH_OPENS.finditer(text):
                branch = set(find_tags(m.group("branch"), self.known))
                members = [t for t in find_tags(m.group("members"), self.known) if self.inline(t)]
                served = [(d, rc) for b, d, rc in routes if b == branch]
                if not served or served[0][0] != owner:
                    continue
                keep = [t for el in branch for t in pump_side.get(el, [])]
                rest = [t for t in members if t not in keep and t not in branch]
                if keep and rest:
                    did = self._decide(
                        owner, claim, [served[0][1]],
                        f"'{owner}' group derived as {', '.join(rest)}: {claim.ref()} lists everything "
                        f"the {'/'.join(sorted(branch))} branch opened ({', '.join(members)}); "
                        f"{served[0][1].ref()} says that branch served {owner}; the current routing "
                        f"record keeps {', '.join(keep)} with the pump, so the remainder is {owner}'s "
                        f"own group. The source is superseded for routing, not for which valves sit "
                        f"at {owner}.",
                    )
                    cache[owner] = (rest, did)
                    return cache[owner]

        self._gap(
            "unresolved_conflict", f"{owner} group",
            f"a connection record ({context}) refers to the '{owner}' valve group, but no source lists "
            f"that group's members; the path carries only its explicitly named elements",
            workaround="state the group's members in the routing record or the valve register",
        )
        cache[owner] = ([], None)
        return cache[owner]

    # ------------------------------------------------------------------ records
    def _decide(self, owner: str, winner: EvidenceClaim, support: list[EvidenceClaim], rationale: str) -> str:
        self._seq += 1
        did = f"DER-GRP-{self._seq:02d}"
        self.decisions.append(
            DecisionRecord(
                id=did,
                subject=f"{owner} group",
                predicate="series_members",
                winner_claim_id=winner.id,
                loser_claim_ids=[c.id for c in support],
                rule_id="D-group-membership",
                rationale=rationale,
                failure_mode="F2-physical-layout-implies-function",
            )
        )
        return did

    def _gap(self, kind: str, subject: str, detail: str, workaround: str | None = None) -> None:
        self.gaps.append(
            Gap(id=f"GAP-TOP-{len(self.gaps) + 1:02d}", kind=kind, subject=subject, detail=detail,
                severity="warn", workaround=workaround)  # type: ignore[arg-type]
        )


def _without_group_refs(text: str) -> str:
    """'V20/V24/V25 plus B1 routing group' -> 'V20/V24/V25 plus ' (B1 is an owner, not a member)."""
    return GROUP_REF.sub(" ", text or "")


def connects_to_claims(claims: Iterable[EvidenceClaim]) -> list[EvidenceClaim]:
    """Raw edge claims from drawings and diagrams. Topology is many-valued, so these are read
    before precedence collapses 'B1 connects_to ...' to one winner."""
    return [
        c for c in claims
        if c.kind == "connection" and norm(c.predicate) in ("connectsto", "connectedto", "feeds", "flowsto")
        and isinstance(c.value, str)
    ]
