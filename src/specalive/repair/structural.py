"""Structural repair: the failures for which no edit to the .mo is the answer.

Why this file exists
--------------------
`RepairLoop` edits Modelica text, because the compiler points at Modelica text. That is the
right instrument for a missing semicolon or a `pre()` around a state read. It is the wrong
instrument for this:

    Too few equations, under-determined system. 15 equation(s) and 27 variable(s).
    // GAP: block 'SRC_101' has no binding

`_unrepairable_reason()` already recognises that shape and, correctly, refuses to spend a
model call on it -- no minimal diff conjures a component that was never bound, and a model
asked to try will invent one, which compiles and is therefore worse than failing.

But refusing is only half an answer. The defect is real and it has a location: the **IR**.
A block that never bound, or one the reconciler pushed out of the executable model, is an IR
fact, and the IR is upstream of both deliverables. So the honest response is not "declared
gap, stop" -- it is "declared gap *in the IR*, here is the correction, rebuild from it".
That is what this module produces: `IREdit`s, which `apply_ir_edits` folds into the model,
after which the pipeline re-emits SysML and re-derives the Modelica from it. Under
`--from-sysml` this is the *only* route by which such a fix can reach the code at all,
because that path reads the SysML and never sees our .mo edits.

The two-stage split, and why it is that way
-------------------------------------------
Stage 1 is deterministic and costs nothing. It answers the question *"which blocks must be in
the executable model?"* -- which is a graph question, not an engineering one:

    L_XV_101 --> TK_101 --> L_XV_102 --> TK_102 --> L_XV_103

`TK_101` arrived flagged `physical_only`, i.e. architecture-only. But it has a simulatable
neighbour on its inlet *and* a simulatable neighbour on its outlet, so it is an interior node
of the executable connection graph. Deleting an interior node severs the path and strands
both ends -- which is precisely the under-determined system the compiler reported. No
knowledge of what a tank is was needed to reach that conclusion, and none is used.

The same test leaves `PLC_101` alone, and that is the point of stating it as a graph rule
rather than a list of kinds: the controller is also flagged `physical_only`, but every edge
touching it is inbound. It is a terminal, not an interior node, so nothing about the flow
path depends on it existing as a component. A rule written as "materialise anything called a
tank" would have been wrong here in both directions.

Stage 2 is the agent, and it runs only on what stage 1 could not settle. Choosing *which*
Modelica class realises a block is a judgement: the block's own `kind` may be wrong (the
extractor called `TK_101` an "external boundary" -- it is an interior vessel, and the graph
says so), the vocabulary may not match the library's, and BM25 on a 1,402-class corpus is
5/10 top-1. That is the shape of problem a model is good at and a regex is not.

What keeps stage 2 safe is that it is multiple choice, not free generation:

  * one call for every unresolved block, not one per block -- the token cost does not scale
    with how broken the packet is;
  * candidates come from the harvested catalog, so a class that does not exist cannot be
    named. The validator rejects an off-list answer rather than escalating on it, the same
    check that makes `catalog_pick` honest;
  * the shortlist is *grounded in the graph*, not just in the block's own words: the library
    its bound neighbours came from, and the connector types it must actually mate with. That
    is what lets it find a vessel for a block the evidence mislabelled;
  * declining is a legitimate answer, and produces a declared gap rather than a guess.

Every edit this module emits is re-verified the only way that means anything: the pipeline
rebuilds and recompiles. Nothing here declares its own success.

Owner: C.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..ir.evidence import Gap
from .writeback import IREdit, _mid

#: Candidates offered per block. Small enough for a 4B to hold, wide enough that the right
#: answer is present when BM25 alone would have ranked it fourth.
SHORTLIST = 10

#: A library small enough to simply show the model in full. The in-house component library is
#: a dozen classes, and enumerating it is strictly better than retrieving from it: it removes
#: any chance that the one right answer is the one BM25 ranked eleventh. MSL is three orders
#: of magnitude too big for this, which is what the bound is for.
SMALL_LIBRARY = 60


@dataclass
class StructuralPlan:
    """What structural repair decided, and how much it cost."""

    edits: list[IREdit] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    #: "deterministic", "model", "both" or "none" -- surfaced in the report so the
    #: three-way tier breakdown stays honest at this stage too.
    method: str = "none"

    def __bool__(self) -> bool:
        return bool(self.edits)


# --------------------------------------------------------------------------- graph questions


def _simulatable_ids(model: Any) -> set[str]:
    return {b.id for b in model.blocks if not b.physical_only and b.abstracted_into is None}


def _edges(model: Any, block_id: str) -> tuple[list[str], list[str]]:
    """(blocks feeding this one, blocks it feeds). Endpoint ids only, direction preserved."""
    inbound: list[str] = []
    outbound: list[str] = []
    for c in model.connections:
        (sb, _), (tb, _) = c.endpoints()
        if tb == block_id:
            inbound.append(sb)
        if sb == block_id:
            outbound.append(tb)
    return inbound, outbound


def interior_architecture_blocks(model: Any) -> list[Any]:
    """Blocks excluded from the executable model that the executable model runs *through*.

    The test is deliberately narrow: a simulatable neighbour on each side. A block with edges
    on one side only is a terminal -- a controller, a boundary, a monitoring tap -- and
    excluding it costs the flow path nothing. A block with neighbours on both sides is load
    bearing, and its absence is exactly the under-determined system the compiler reports.
    """
    live = _simulatable_ids(model)
    out = []
    for b in model.blocks:
        if not b.physical_only or b.abstracted_into is not None:
            continue
        inbound, outbound = _edges(model, b.id)
        if any(s in live for s in inbound) and any(t in live for t in outbound):
            out.append(b)
    return out


def unbound_blocks(model: Any, *, extra_live: set[str] | None = None) -> list[Any]:
    """Blocks that will be emitted but have nothing to emit as.

    `extra_live` lets the caller include blocks it is about to materialise in this same plan,
    so both halves of the repair are decided in one pass and one model call.
    """
    live = _simulatable_ids(model) | (extra_live or set())
    return [b for b in model.blocks if b.id in live and not b.modelica_class]


# ------------------------------------------------------------------- catalog candidate search


def _neighbour_classes(model: Any, block_id: str) -> list[str]:
    """Modelica classes already bound to whatever this block connects to."""
    inbound, outbound = _edges(model, block_id)
    by_id = {b.id: b for b in model.blocks}
    return [
        by_id[n].modelica_class
        for n in (*inbound, *outbound)
        if n in by_id and by_id[n].modelica_class
    ]


def _connector_families(model: Any, block: Any, index: Any) -> set[str]:
    """The connector *packages* this block has to speak, read off its bound neighbours.

    Package, not type, and the distinction is the whole trick. Modelica connectors mate
    complementarily, not identically: in the in-house library a vessel's `Outlet` mates with
    a transport element's `Suction`, and its `Inlet` with a `Discharge` -- same variables,
    opposite causality, four different type names. Requiring a candidate to expose the same
    *types* as its neighbours therefore rejects every correct answer and accepts junk that
    happens to share a name.

    What does hold, in MSL and in any library that follows it, is that connectors which mate
    are declared side by side in one interfaces package. So `SpecAlive.Interfaces.Suction` on
    the neighbour tells us to look for a class exposing something from `SpecAlive.Interfaces`
    -- which `SpecAlive.Vessels.Reservoir` does, via `Inlet` and `Outlet`. No knowledge of
    what those four connectors mean is needed, and none is used.
    """
    out: set[str] = set()
    for cls in _neighbour_classes(model, block.id):
        entry = index.get(cls) if index else None
        if entry is None:
            continue
        for p in entry.ports:
            if "." in p.type:
                out.add(p.type.rsplit(".", 1)[0])
    return {f for f in out if _is_discriminating(f, index)}


#: A connector package on more than this share of the catalog tells us nothing about which
#: class we want. `Modelica.Blocks.Interfaces` is on 47% of MSL 4.1.0, because almost
#: everything takes a signal; matching on it returns the library rather than a shortlist.
#:
#: The number is placed from the measured distribution, not picked. On a 1,402-class harvest
#: the ordering is 0.466 Blocks, then 0.158 Electrical.Analog, 0.141 Thermal.HeatTransfer,
#: 0.076 Mechanics.Rotational, 0.031 Fluid, 0.006 for the in-house library. So there is one
#: genuine outlier and a long tail of real domain packages, and the cut belongs in the gap
#: between them: 0.30 drops Blocks with margin and keeps every domain package with more. A
#: tighter bound would start discarding electrical, which is a domain we bind in, not noise.
#:
#: Measured rather than named so it survives a machine with different libraries installed.
GENERIC_FAMILY_SHARE = 0.30


def _is_discriminating(family: str, index: Any) -> bool:
    cache = getattr(index, "_family_share", None)
    if cache is None:
        counts: dict[str, int] = {}
        for e in index.entries:
            for fam in {p.type.rsplit(".", 1)[0] for p in e.ports if "." in p.type}:
                counts[fam] = counts.get(fam, 0) + 1
        total = max(len(index.entries), 1)
        cache = {k: v / total for k, v in counts.items()}
        try:
            index._family_share = cache
        except Exception:
            pass  # a frozen index just recomputes; correctness does not depend on the cache
    return cache.get(family, 0.0) <= GENERIC_FAMILY_SHARE


def _required_connectors(model: Any, block: Any, index: Any) -> set[str]:
    """Exact connector types on the bound neighbours. Shown to the agent as context only.

    Kept separate from `_connector_families` because the two are used for different things:
    this is what the prompt prints so the model can reason about mating, and that is what the
    shortlist filters on. Conflating them is the bug this split exists to prevent.
    """
    types: set[str] = set()
    for cls in _neighbour_classes(model, block.id):
        entry = index.get(cls) if index else None
        if entry is None:
            continue
        types.update(p.type for p in entry.ports)
    return types


def candidates(model: Any, block: Any, index: Any) -> list[Any]:
    """Shortlist for one unresolved block: its own words, plus what the graph knows.

    Ordered by how much the signal is worth, because the list is capped and the cap should
    cost us the weakest source rather than an arbitrary one. The block's own text goes
    *last*: for every block that reaches this stage the tier cascade already tried exactly
    that and came back with nothing usable, and on a mislabelled block -- `TK_101` is filed
    as an "external boundary" when the graph plainly shows it is an interior vessel -- it is
    not merely weak but actively misleading. The graph-derived sources go first because they
    are independent of whatever the evidence chose to call this block.
    """
    if index is None:
        return []
    seen: dict[str, Any] = {}

    def take(entries: list[Any]) -> None:
        for e in entries:
            seen.setdefault(e.key, e)

    libs = {
        e.library
        for cls in _neighbour_classes(model, block.id)
        if (e := index.get(cls)) is not None
    }
    families = _connector_families(model, block, index)

    # No bound neighbour means no graph signal, and the shortlist would be pure lexical
    # noise -- the same search the tier cascade already ran and rejected. Offering it anyway
    # is worse than offering nothing: the model is asked to choose from a list whose right
    # answer is absent, and the likeliest outcome is a component that compiles and is wrong.
    # `LT_101` is the live example: its only neighbour is the controller, which is not a
    # component at all, so BM25 returns `Blocks.Math.Sqrt` for a level transmitter. Returning
    # empty here routes it to a declared gap and costs no tokens.
    if not libs and not families:
        return []

    # 1. Enumerate a small neighbour library outright. If the parts around this block came
    #    from a twelve-class library, the part that belongs here is almost certainly in it,
    #    and showing all twelve removes retrieval from the critical path entirely.
    for lib in sorted(libs):
        members = [e for e in index.entries if e.library == lib and e.restriction in ("model", "block")]
        if len(members) <= SMALL_LIBRARY:
            take(members)

    # 2. Connector-family compatibility, ranked by how much of the block's interface a
    #    candidate could actually serve. A block with two process ports wants a class with
    #    two; ranking by the count puts those above a single-port boundary without having to
    #    special-case either.
    if families:
        scored = [
            (sum(1 for p in e.ports if p.type.rsplit(".", 1)[0] in families), e)
            for e in index.entries
            if e.restriction in ("model", "block")
        ]
        ranked = sorted((s for s in scored if s[0] > 0), key=lambda s: -s[0])
        take([e for _, e in ranked[: SHORTLIST * 2]])

    # 3/4. Text, library-scoped first. Weakest here, kept because it is sometimes right and
    #      dropping it on the strength of one packet would be superstition.
    text = f"{block.name} {block.kind} {block.description or ''}".strip()
    for lib in sorted(libs):
        take([h.entry for h in index.search(text, k=SHORTLIST, library=lib)])
    take([h.entry for h in index.search(text, k=SHORTLIST)])

    # The cap bites the tail, and the tail is the text search -- which is deliberate. The
    # graph-derived sources are inserted first precisely so that trimming costs us the weakest
    # evidence rather than an arbitrary slice, and every token spent printing a class the
    # topology already rules out is a token not available to the rest of the run.
    return list(seen.values())[: SHORTLIST + 2]


# ------------------------------------------------------------------------------- the agent

BIND_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["decisions"],
    "properties": {
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["block", "action", "reason"],
                "properties": {
                    "block": {"type": "string", "description": "Exactly as listed below."},
                    "action": {
                        "type": "string",
                        "enum": ["bind", "decline"],
                        "description": "bind: name a class from that block's candidate list. "
                                       "decline: nothing offered is right.",
                    },
                    "modelica_class": {
                        "type": "string",
                        "description": "Required for 'bind'. Must be copied verbatim from the "
                                       "candidate list for that block.",
                    },
                    "reason": {"type": "string"},
                },
            },
        }
    },
}

BIND_PROMPT = """\
An OpenModelica build failed because these blocks have no Modelica component behind them.
Every equation they would have contributed is missing, so the system is under-determined.

COMPILER SAID
{diagnostic}

Your job: for each block below, pick the candidate class that realises it, or decline.

How to judge, in this order:
1. **Topology over vocabulary.** The connection graph is extracted mechanically and is
   reliable. The block's stated `kind` came from prose and may be wrong. A block with a
   supply on one side and a draw on the other is an interior component, whatever it is
   called -- do not pick a boundary/source/sink class for it.
2. **Connectors must mate.** The neighbours' connector types are given. Connectors mate
   complementarily, not identically: a supply-side connector pairs with an intake-side one.
   A class that cannot pair with the neighbours is wrong however well its name matches.
3. **Parameters the block carries** should mostly exist on the class you choose.

CLASSES (the only names you may use; ports are name:ConnectorType)
{library}

BLOCKS
{blocks}

Rules:
- `modelica_class` must be copied verbatim from that block's own `candidates` line. A class
  from another block's list, or one you recall from elsewhere, will be rejected.
- Decline rather than approximate. An unbound block is reported as a declared gap, which is a
  correct answer; a plausible wrong component is not, and it compiles.
- One decision per block. Answer JSON only.
"""


def _render_library(entries: dict[str, Any]) -> str:
    """Every offered class, once.

    Rendered as a shared table rather than inline under each block because the candidate sets
    overlap almost completely -- four blocks drawing on one twelve-class library repeated the
    same descriptions four times and pushed a single call past the per-minute token ceiling.
    The block entries below carry only the key names, which is all that differs.
    """
    lines = []
    for key in sorted(entries):
        e = entries[key]
        ports = ", ".join(f"{p.name}:{p.type.rsplit('.', 1)[-1]}" for p in e.ports[:6])
        if len(e.ports) > 6:
            ports += f", +{len(e.ports) - 6} more"
        prm = ", ".join(p.name for p in e.params[:6])
        what = (e.comment or "").strip().replace("\n", " ")[:90] or "(no description)"
        lines.append(f"  {key}\n    {what}\n    ports: {ports or '(none)'}   params: {prm or '(none)'}")
    return "\n".join(lines)


def _render_block(model: Any, block: Any, cands: list[Any], index: Any) -> str:
    inbound, outbound = _edges(model, block.id)
    by_id = {b.id: b for b in model.blocks}

    def describe(ids: list[str]) -> str:
        if not ids:
            return "(nothing)"
        return ", ".join(
            f"{i}[{by_id[i].modelica_class.rsplit('.', 1)[-1]}]"
            if i in by_id and by_id[i].modelica_class
            else f"{i}[unbound]"
            for i in ids
        )

    wanted = sorted(t.rsplit(".", 1)[-1] for t in _required_connectors(model, block, index))
    params = ", ".join(
        f"{p.name}={p.quantity.value}{p.quantity.unit or ''}" for p in block.parameters[:8]
    )
    position = "INTERIOR (connected on both sides)" if inbound and outbound else "TERMINAL (one side only)"
    return "\n".join(
        [
            f"### {_mid(block.id)}",
            f"  stated kind: {block.kind}   (from prose -- may be wrong)",
            f"  description: {(block.description or '(none)')[:120]}",
            f"  fed by: {describe(inbound)}   feeds: {describe(outbound)}",
            f"  position: {position}",
            f"  neighbour connectors to mate with: {', '.join(wanted) or '(unknown)'}",
            f"  parameters: {params or '(none)'}",
            f"  candidates: {', '.join(e.key for e in cands)}",
        ]
    )


def _agent_bindings(
    model: Any, blocks: list[Any], index: Any, router: Any, diagnostic: str
) -> tuple[list[IREdit], list[str]]:
    """One call, every unresolved block. Returns (edits, notes)."""
    offered: dict[str, dict[str, Any]] = {}
    rendered: list[str] = []
    library: dict[str, Any] = {}
    for b in blocks:
        cands = candidates(model, b, index)
        if not cands:
            continue
        offered[_mid(b.id)] = {c.key: c for c in cands}
        library.update({c.key: c for c in cands})
        rendered.append(_render_block(model, b, cands, index))
    if not rendered:
        return [], ["no catalog candidates could be offered for any unbound block"]

    def validate(data: Any) -> tuple[bool, str]:
        for d in (data or {}).get("decisions") or []:
            name = str(d.get("block", "")).strip()
            if name not in offered:
                return False, f"'{name}' is not one of the blocks you were asked about"
            if d.get("action") != "bind":
                continue
            cls = str(d.get("modelica_class", "")).strip()
            if cls not in offered[name]:
                # The one check that makes "cannot invent a class" literally true here.
                return False, f"'{cls}' was not in the candidate list for {name}"
        return True, ""

    try:
        resp = router.run(
            "catalog_pick",
            BIND_PROMPT.format(
                diagnostic=diagnostic[:600],
                library=_render_library(library),
                blocks="\n\n".join(rendered),
            ),
            schema=BIND_SCHEMA,
            validator=validate,
        )
    except Exception as exc:
        return [], [f"structural agent unavailable: {exc}"]

    edits: list[IREdit] = []
    notes: list[str] = []
    for d in (resp.data or {}).get("decisions") or []:
        name = str(d.get("block", "")).strip()
        reason = str(d.get("reason", ""))[:200]
        if d.get("action") != "bind":
            notes.append(f"{name}: declined -- {reason}")
            continue
        cls = str(d.get("modelica_class", "")).strip()
        if name not in offered or cls not in offered[name]:
            continue  # validator should have caught it; belt and braces
        edits.append(IREdit(kind="bind", old="unbound", new=cls, block=name, detail=reason))
    return edits, notes


# ------------------------------------------------------------------------------ orchestration


def plan_structural_repair(
    model: Any,
    diagnostic: str,
    *,
    index: Any | None = None,
    router: Any | None = None,
    allow_model: bool = True,
) -> StructuralPlan:
    """Decide what the IR has to change for this build to have a chance.

    Deterministic first and always: the graph argument is exact, free, and settles the case
    that actually breaks packets. The agent runs only on what is left, once, and only if a
    router was configured -- `--provider none` must keep working end to end, and on a packet
    whose blocks all bind there is nothing here to do anyway.
    """
    plan = StructuralPlan()

    # ---- stage 1: blocks the connection graph proves must exist -------------------------
    materialise = interior_architecture_blocks(model)
    for b in materialise:
        inbound, outbound = _edges(model, b.id)
        plan.edits.append(
            IREdit(
                kind="materialise",
                old="physical_only",
                new="simulatable",
                block=_mid(b.id),
                detail=(
                    f"interior node of the executable graph ({', '.join(inbound)} -> {b.id} -> "
                    f"{', '.join(outbound)}); excluding it severs the path"
                ),
            )
        )
        plan.notes.append(
            f"{b.id} was architecture-only but sits between simulatable blocks; materialised"
        )
    if materialise:
        plan.method = "deterministic"

    # ---- stage 2: whatever still has no component --------------------------------------
    # Newly materialised blocks are included here, so one model call settles both halves.
    pending = unbound_blocks(model, extra_live={b.id for b in materialise})
    if not pending:
        return plan

    if not (allow_model and router is not None and index is not None):
        for b in pending:
            plan.gaps.append(
                Gap(
                    id=f"GAP-STRUCT-{b.id}",
                    kind="unmapped_component",
                    subject=b.id,
                    detail=(
                        f"'{b.name}' ({b.kind}) bound to no Modelica component: the catalog "
                        f"had no match, no template applied, and structural repair ran without "
                        f"a model tier. The equations it would contribute are absent."
                    ),
                    severity="blocking",
                    workaround="re-run with a live provider, or add a catalog alias for this kind",
                )
            )
        plan.notes.append(
            f"{len(pending)} block(s) left unbound: no model tier available for structural repair"
        )
        return plan

    grounded = [b for b in pending if candidates(model, b, index)]
    ungrounded = [b for b in pending if b not in grounded]

    edits: list[IREdit] = []
    if grounded:
        edits, notes = _agent_bindings(model, grounded, index, router, diagnostic)
        plan.edits.extend(edits)
        plan.notes.extend(notes)
        if edits:
            plan.method = "both" if materialise else "model"

    decided = {e.block for e in edits}
    for b in grounded:
        if _mid(b.id) in decided:
            continue
        plan.gaps.append(
            Gap(
                id=f"GAP-STRUCT-{b.id}",
                kind="unmapped_component",
                subject=b.id,
                detail=(
                    f"'{b.name}' ({b.kind}) bound to no Modelica component. Structural repair "
                    f"offered the catalog candidates its neighbours' connectors imply and "
                    f"declined to choose one, rather than emit a component the evidence never "
                    f"named."
                ),
                severity="blocking",
                workaround="name the intended class in the packet, or add a catalog alias",
            )
        )
    for b in ungrounded:
        # Never went to the model, and the reason is worth stating separately: this is not a
        # model that could not decide, it is a block with no bound neighbour to reason from.
        # The fix is upstream -- bind what it connects to, or extract it as a signal rather
        # than a component -- and saying so is more use than a shortlist of noise.
        inbound, outbound = _edges(model, b.id)
        plan.gaps.append(
            Gap(
                id=f"GAP-STRUCT-{b.id}",
                kind="unmapped_component",
                subject=b.id,
                detail=(
                    f"'{b.name}' ({b.kind}) bound to no Modelica component, and structural "
                    f"repair had nothing to ground a candidate list on: none of its "
                    f"neighbours ({', '.join([*inbound, *outbound]) or 'it has no connections'}) "
                    f"is bound to a component either. No model call was made."
                ),
                severity="blocking",
                workaround=(
                    "bind its neighbours first, or extract it as a sensor signal bound into "
                    "the plant rather than as a block"
                ),
            )
        )
    if ungrounded:
        plan.notes.append(
            f"{len(ungrounded)} block(s) had no bound neighbour to ground a shortlist on "
            f"({', '.join(b.id for b in ungrounded)}); declared as gaps without a model call"
        )
    return plan
