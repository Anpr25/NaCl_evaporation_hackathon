"""Whole-packet structural extraction: the one model call that reads the packet as a system.

Why this exists, given `claims.py` already extracts:

`claims.py` works a span at a time. That is the right shape for "what does this sentence
assert", and it is the wrong shape for "what are the parts of this plant". A component
schedule in a spreadsheet names a room; an interface matrix in a different sheet connects it
to a duct; a design note in a .docx says the duct is ideal and carries no storage; the P&ID
shows an exhaust boundary nobody tabulated. No chunk contains the system. The deterministic
path recovers the tabulated half of that and, on three of the four packets we test against,
recovers none of the untabulated half -- which is the half that decides whether the emitted
Modelica has components in it.

So this pass hands the whole packet to a long-context model at once and asks for the
skeleton: parts, what each one IS, what connects to what, and the Modelica class it should
bind to. Three rules keep it honest and keep it subordinate to the deterministic path:

  * everything comes back as an `EvidenceClaim` with a verbatim quote, and a claim whose
    quote is not in the packet is dropped before it reaches the reconciler;
  * claims carry a lower confidence than the deterministic ones, so wherever a register
    already states a fact, precedence keeps the register's version and this pass can only
    *add*;
  * a suggested Modelica class is verified against the harvested catalog and discarded if it
    does not exist, so the model cannot introduce a class the emitter would then fail on.

Owner: A/D.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from ..ingest.base import Document
from ..ir.evidence import EvidenceClaim, Locator
from ..llm.base import LLMError

#: How much of the packet goes into one call. Flash-class context is far larger than this;
#: the cap is about cost and about keeping the digest readable, not about the window.
MAX_DIGEST_CHARS = 180_000
#: Per-document share of the digest, so one 600-row CSV cannot crowd out fourteen other
#: sources. A packet's evidence is spread across its documents, and so is its budget.
MAX_DOC_CHARS = 18_000

#: Below the deterministic path's 0.95 and below the per-span text path's 0.6: this pass
#: sees the most context and gets the least benefit of the doubt, because a whole-packet
#: answer is the hardest one to check a quote against.
SKELETON_CONFIDENCE = 0.5

SKELETON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["parts", "connections"],
    "properties": {
        "system_name": {"type": "string"},
        "parts": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["tag", "kind", "quote"],
                "properties": {
                    "tag": {"type": "string", "description": "The identifier the packet uses."},
                    "name": {"type": "string"},
                    "kind": {"type": "string", "description": "What the part IS, in the packet's own words."},
                    "domain": {
                        "type": "string",
                        "enum": ["fluid", "thermal", "electrical", "magnetic", "rotational",
                                 "translational", "signal", "unknown"],
                    },
                    "modelica_class": {
                        "type": "string",
                        "description": "Fully qualified Modelica Standard Library class, or empty.",
                    },
                    "quote": {"type": "string"},
                },
            },
        },
        "connections": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["from", "to", "quote"],
                "properties": {
                    "id": {"type": "string"},
                    "from": {"type": "string"},
                    "to": {"type": "string"},
                    "from_port": {"type": "string"},
                    "to_port": {"type": "string"},
                    "medium": {"type": "string"},
                    "quote": {"type": "string"},
                },
            },
        },
    },
}

SKELETON_PROMPT = """\
You are reading a complete engineering packet for one system. Report its executable
structure: the parts, and what connects to what.

What counts as a part: anything that would be a component instance in a simulation model --
a vessel, a room volume, a duct, a flux tube, a coil, a source, a sink, a ground, a sensor, a
gain, a controller block. Include parts that only a diagram or an interface record mentions.
Do NOT include requirements, test cases, documents, revisions, people, dates or schedule rows.

Rules, in order of importance:
- `quote` must be copied verbatim from the packet below. If you cannot quote it, omit it.
- `tag` must be exactly the identifier the packet uses. Never invent, tidy or renumber a tag.
- `kind` is what the packet calls the part. Copy its words; do not paraphrase into your own.
- `modelica_class` is the fully qualified Modelica Standard Library class that realises this
  part, when you are confident one exists -- for example
  `Modelica.Electrical.Analog.Basic.Ground`. Leave it empty rather than guess: a wrong class
  is worse than none, and an empty one is filled in by catalog retrieval afterwards.
- `from` and `to` in a connection must both be tags you listed in `parts`.
- Report the system as the packet describes it, including parts the packet contradicts
  itself about. Contradictions are resolved later and are valuable.

{known}
PACKET
{digest}
"""

_KNOWN_BLOCK = """\
Already extracted deterministically from the packet's tables (do not repeat these, but DO
list any part they are missing, and DO give a `modelica_class` for one that has none):
{tags}
"""


def build_digest(docs: list[Document]) -> str:
    """One readable rendering of the whole packet, per-document budgeted."""
    parts: list[str] = []
    total = 0
    for d in docs:
        body = d.full_text(MAX_DOC_CHARS)
        if not body.strip():
            continue
        head = (f"\n===== SOURCE {d.source.id}: {d.source.filename} "
                f"({d.source.media_type}, authority {d.source.authority.value}) =====\n")
        chunk = head + body
        if total + len(chunk) > MAX_DIGEST_CHARS:
            break
        parts.append(chunk)
        total += len(chunk)
    return "".join(parts)


def _norm_tag(s: str) -> str:
    """Tag identity, insensitive to the punctuation a packet varies: B-5 == B5 == b_5."""
    return "".join(ch for ch in str(s).lower() if ch.isalnum())


def _normalise_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def extract_skeleton(
    docs: list[Document],
    router: Any,
    *,
    known_tags: Iterable[str] = (),
    described: Iterable[str] = (),
    index: Any | None = None,
    seq: Iterable[int] | None = None,
) -> tuple[list[EvidenceClaim], list[str]]:
    """One whole-packet call. Returns (claims, notes) and never raises on a model failure.

    `notes` is what to tell the reader: how many claims survived the quote check, how many
    suggested classes the catalog rejected. A silent extraction pass is not auditable, and
    this is the one pass whose output nothing downstream can independently confirm.
    """
    digest = build_digest(docs)
    if not digest.strip():
        return [], ["no readable text in the packet"]

    tags = sorted({t for t in known_tags if t})
    described_keys = {_norm_tag(t) for t in described if t}
    known = _KNOWN_BLOCK.format(tags=", ".join(tags)) if tags else ""
    haystack = _normalise_ws(digest)
    source_id = docs[0].source.id if docs else "packet"

    def validate(data: Any) -> tuple[bool, str]:
        parts = (data or {}).get("parts") or []
        if parts and not any(_normalise_ws(p.get("quote", "")) in haystack for p in parts):
            return False, "none of the quotes appear verbatim in the packet"
        return True, ""

    try:
        resp = router.run(
            "system_skeleton",
            SKELETON_PROMPT.format(known=known, digest=digest),
            schema=SKELETON_SCHEMA,
            validator=validate,
        )
    except LLMError as exc:
        return [], [f"whole-packet extraction unavailable: {exc}"]

    data = resp.data or {}
    counter = seq if seq is not None else _count_from(900_000)
    catalog_keys = [e.key for e in getattr(index, "entries", [])] if index is not None else None

    claims: list[EvidenceClaim] = []
    dropped_quote = 0
    dropped_class = 0
    rejected: list[str] = []
    corrected: list[str] = []
    listed: set[str] = set()

    def emit(subject: str, predicate: str, value: Any, quote: str, kind: str) -> None:
        claims.append(
            EvidenceClaim(
                id=f"CLM-S{next(iter(counter)):05d}",
                source_id=source_id,
                locator=Locator(section="whole-packet structural read"),
                kind=kind,  # type: ignore[arg-type]
                subject=subject,
                predicate=predicate,
                value=value,
                quote=quote[:300],
                confidence=SKELETON_CONFIDENCE,
                extracted_by=resp.tier,
            )
        )

    for p in data.get("parts") or []:
        tag = str(p.get("tag") or "").strip()
        quote = str(p.get("quote") or "")
        if not tag:
            continue
        if _normalise_ws(quote) not in haystack:
            dropped_quote += 1
            continue
        listed.add(tag)
        # Where a register already says what a part is, it says so with a locator and a
        # named authority, and this pass has neither. Competing with it would put a
        # whole-packet paraphrase into a precedence contest it has no business winning; the
        # Modelica class below is different, because no register in these packets states one
        # for the parts that need it most.
        if _norm_tag(tag) not in described_keys:
            kind = str(p.get("kind") or "").strip()
            # A `kind` that is just the tag again says nothing, and it is actively harmful:
            # it displaces the humanised spelling the assembler would otherwise derive, and
            # 'ExcitingCoil ExcitingCoil' is a worse retrieval query than 'exciting coil'.
            if kind and _norm_tag(kind) != _norm_tag(tag):
                emit(tag, "kind", kind, quote, "component")
            name = str(p.get("name") or "").strip()
            if name and _norm_tag(name) != _norm_tag(tag):
                emit(tag, "name", name, quote, "component")
        cls = str(p.get("modelica_class") or "").strip()
        if cls:
            # The catalog is the ground truth for what exists, and it is also the only thing
            # that can *correct* a near miss. A model that says
            # `Modelica.Magnetic.FluxTubes.Ground` when the class is
            # `Modelica.Magnetic.FluxTubes.Basic.Ground` has identified the right component
            # and mistyped the path; dropping that is throwing away the pass's best output.
            resolved = _resolve_class(cls, catalog_keys)
            if resolved is None:
                dropped_class += 1
                rejected.append(cls)
            else:
                emit(tag, "model class", resolved, quote, "component")
                if resolved != cls:
                    corrected.append(f"{cls} -> {resolved}")

    for c in data.get("connections") or []:
        src, dst = str(c.get("from") or "").strip(), str(c.get("to") or "").strip()
        quote = str(c.get("quote") or "")
        if not src or not dst or _normalise_ws(quote) not in haystack:
            dropped_quote += 1
            continue
        cid = str(c.get("id") or "").strip() or f"IF-{src}-{dst}"
        emit(cid, "from", src, quote, "connection")
        emit(cid, "to", dst, quote, "connection")
        for field, predicate in (("from_port", "from port"), ("to_port", "to port"),
                                 ("medium", "medium")):
            if v := str(c.get(field) or "").strip():
                emit(cid, predicate, v, quote, "connection")

    notes = [
        f"whole-packet read on {resp.tier} ({resp.model}): {len(listed)} part(s), "
        f"{len(data.get('connections') or [])} connection(s), {len(claims)} claim(s)"
    ]
    if dropped_quote:
        notes.append(f"dropped {dropped_quote} item(s) whose quote is not verbatim in the packet")
    if corrected:
        notes.append("corrected against the catalog: " + "; ".join(corrected[:5]))
    if dropped_class:
        notes.append(
            f"rejected {dropped_class} suggested Modelica class(es) absent from the catalog: "
            + ", ".join(rejected[:5])
        )
    return claims, notes


def _resolve_class(name: str, keys: list[str] | None) -> str | None:
    """The catalog key this suggestion means, or None if the catalog has nothing like it.

    Exact first, then a path suffix, then the leaf name alone. Among several matches the
    shallowest path wins -- the same deterministic tie-break the binder uses, so a suggestion
    and a declaration resolve to the same class.
    """
    if keys is None:
        return name
    if name in keys:
        return name
    leaf = name.rsplit(".", 1)[-1]
    for candidates in ([k for k in keys if k.endswith("." + name)],
                       [k for k in keys if k.rsplit(".", 1)[-1] == leaf]):
        if candidates:
            return min(candidates, key=lambda k: (k.count("."), k))
    return None


def _count_from(start: int) -> Iterable[int]:
    n = start
    while True:
        n += 1
        yield n
