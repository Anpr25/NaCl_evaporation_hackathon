"""Choose the connector families a plant is built from, before binding any part.

Binding one part at a time from a catalog of fourteen hundred classes cannot produce a
model whose parts connect, because the question "which class is right for this tank?" has
no answer in isolation. The standard library offers the same component several times over
-- a ground in `Magnetic.FluxTubes`, in `Magnetic.FundamentalWave`, in `QuasiStatic` -- and
the variants do not mate. Retrieval picks each part's best-scoring variant independently,
and the model comes out as a collection of good choices that cannot be wired together.

So the families are decided first, for the plant as a whole, and each part is then bound
inside them. The choice is a weighted set cover: every part contributes the connector
families of its plausible classes (declared, learned, template, retrieved), weighted by how
strong that evidence is; the family covering the most weight is taken, then the next for the
parts still uncovered, until every part that can be covered is. A multi-domain part -- a coil
that is both electrical and magnetic -- is covered by whichever family comes first, and its
class naturally carries the other.

Parts the evidence names a class for are not constrained -- the packet has decided -- but
they vote with the heaviest weight, which is what pulls the rest of the plant into their
library. Pure signal blocks (gains, setpoints) all speak `Modelica.Blocks.Interfaces` and
are left out of the vote.

Owner: C.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from ..ir.system import SystemModel

#: Stand-in family for a class whose connectors are all causal signals.
SIGNAL = "(signal)"
#: A family counts as covering a part when it offers a candidate at least this good,
#: relative to the part's best candidate.
_GOOD_FRACTION = 0.6


def physical_families(entry: Any) -> set[str]:
    """The packages of an entry's non-signal connectors, or {SIGNAL} if it has none."""
    from .modelica import _side_of  # local: modelica imports this module

    fams = {p.type.rsplit(".", 1)[0] for p in getattr(entry, "ports", [])
            if "." in p.type and not _side_of(p.name, p.type).startswith("signal")}
    return fams or {SIGNAL}


def plan_families(
    model: SystemModel, index: Any, binder: Any, memory: Any | None = None
) -> tuple[dict[str, set[str]], list[str]]:
    """Returns ({block id: required connector packages}, notes for the report)."""
    if index is None:
        return {}, []

    weights: dict[str, dict[str, float]] = {}
    exempt: set[str] = set()
    for b in model.simulatable_blocks():
        per: dict[str, float] = defaultdict(float)
        already = b.modelica_class if (b.binding_tier != "unbound" and b.modelica_class) else None
        binder._require = set()
        # Exempt only a declaration that actually resolves. One the binder will reject
        # (absent from the catalog, or in a package it cannot wire) decides nothing, and
        # exempting its part left that part unconstrained when the declaration fell away.
        if already or (b.declared_class and binder._try_declared(b) is not None):
            exempt.add(b.id)
        cands = [(already, 6.0, "bound")] if already else binder.candidates(b)
        for cls, w, _why in cands:
            entry = index.get(cls) if cls else None
            if entry is None:
                continue
            for fam in physical_families(entry):
                per[fam] = max(per[fam], w)
        if memory is not None:
            for fam in list(per):
                for d in b.domains:
                    per[fam] += 0.5 * memory.family_weight(d, fam)
        if not per:
            continue
        # A family covers this part only if it offers one of the part's GOOD candidates.
        # Retrieval returns eight hits spanning half the library, so nearly every part has
        # *some* candidate in every popular family -- and counting those let the first
        # family chosen claim everything: an electrical ground required into the magnetic
        # flux-tube library, a PID block required into a rotational one.
        best = max(per.values())
        per = {fam: w for fam, w in per.items() if w >= _GOOD_FRACTION * best}
        # A part whose best answer is a pure signal block speaks Modelica.Blocks and needs
        # no family decision.
        if SIGNAL in per and per[SIGNAL] >= best:
            continue
        per.pop(SIGNAL, None)
        if per:
            weights[b.id] = dict(per)

    uncovered = set(weights)
    order: list[str] = []
    while uncovered:
        totals: dict[str, tuple[float, int]] = {}
        for bid in uncovered:
            for fam, w in weights[bid].items():
                t = totals.get(fam, (0.0, 0))
                totals[fam] = (t[0] + w, t[1] + 1)
        if not totals:
            break
        fam = max(totals, key=lambda f: (totals[f][0], totals[f][1], f))
        order.append(fam)
        uncovered -= {bid for bid in uncovered if fam in weights[bid]}

    rank = {fam: i for i, fam in enumerate(order)}
    required: dict[str, set[str]] = {}
    counts: dict[str, int] = defaultdict(int)
    for bid, per in weights.items():
        fam = min(per, key=lambda f: rank.get(f, len(rank)))
        counts[fam] += 1
        blk = model.block(bid)
        if blk is not None:
            blk.connector_family = fam
        if bid not in exempt:
            required[bid] = {fam}

    notes = [f"connector families: " + ", ".join(
        f"{fam.rsplit('.', 1)[0] if fam.endswith('.Interfaces') else fam} ({counts[fam]} part(s))"
        for fam in order if counts[fam]
    )] if order else []
    return required, notes
