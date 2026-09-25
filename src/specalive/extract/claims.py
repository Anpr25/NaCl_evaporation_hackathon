"""Documents -> typed EvidenceClaims.

Two paths, and the split is the whole point:

  T0 deterministic -- any table with a recognisable header, any key/value pair, any PlantUML
  edge, any Modelica declaration. Exact, free, offline. On the NaCl packet this alone produces
  the large majority of claims.

  T1/T2/T3 model -- only the prose that no parser can structure, chunked, schema-constrained,
  and always carrying the locator of the chunk it came from.

An extractor reports what a document *says*. It never decides what is *true*; that is the
reconciler's job, and keeping the two apart is what makes the decision log trustworthy.

Owner: A.  STATUS: deterministic path and model path (text + vision) both implemented.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Iterable

from ..ir.evidence import EvidenceClaim, Locator
from ..ingest.base import DocBlock, Document
from ..llm.base import LLMError

#: Block kinds the model text path is allowed to see. Everything else (table/keyvalue/graph/
#: code/image) is either already handled deterministically or goes through the vision path
#: instead -- sending it to the text model would be a wasted call at best and a source of
#: duplicate or garbled claims at worst.
_PROSE_KINDS: tuple[str, ...] = ("heading", "paragraph", "list")

# --------------------------------------------------------------------------- header matching

#: Column-header synonyms -> the IR predicate they populate. Domain-agnostic vocabulary: these
#: are the words engineering registers use regardless of whether the plant is chemical,
#: electrical or mechanical. Extend freely; a miss costs a claim, never a wrong claim.
HEADER_SYNONYMS: dict[str, tuple[str, ...]] = {
    # "mark" and "asset" are what building services and facilities call a tag; "equipment"
    # and "component" are what mechanical schedules call one. A vocabulary that only knows
    # process-plant words will read a perfectly ordinary HVAC schedule and find no equipment
    # in it at all, which is exactly what happened on the first run of that packet.
    "id": ("id", "tag", "item", "ref", "reference", "req id", "parameter id", "no", "number",
           "mark", "asset", "asset id", "equipment", "equipment id", "component", "device",
           "plant item", "loop", "point"),
    "name": ("name", "title", "description", "designation", "service", "function"),
    "kind": ("type", "kind", "class", "category", "model class", "role", "equipment type",
             "discipline"),
    "value": ("value", "setpoint", "setting", "nominal", "rating", "quantity", "target",
              "duty", "capacity", "magnitude"),
    "unit": ("unit", "units", "uom", "dimension"),
    "status": ("status", "state", "validity", "revision status"),
    "superseded_by": ("superseded by", "replaced by", "supersedes", "overrides"),
    "authority": ("authority", "source", "origin", "document", "issued by", "owner"),
    "requirement": ("requirement", "statement", "shall", "text"),
    "priority": ("priority", "criticality", "must/should"),
    "verification": ("verification", "verify", "test method", "acceptance"),
    "from": ("from", "source", "upstream", "start", "inlet"),
    "to": ("to", "target", "destination", "downstream", "end", "outlet"),
    "port": ("port", "connection", "terminal", "nozzle", "pin", "flange"),
    "medium": ("medium", "fluid", "item", "service", "material", "signal"),
    "guard": ("guard", "transition", "condition", "trigger", "completion condition"),
    "action": ("action", "actuation", "effect", "command", "required action"),
    "region": ("region", "branch", "thread", "parallel"),
    "next": ("next", "next state", "successor", "goto"),
    "ownership": ("ownership", "control source", "controlled by", "actuation type"),
    # A column that names the attribute each row is about. Its presence means the table is
    # long-format -- one row per (item, attribute, value) -- instead of one column per
    # attribute. Engineering schedules use both shapes freely.
    "attribute": ("parameter", "attribute", "property", "variable", "characteristic",
                  "parameter name", "field", "measure"),
}

_NUM = re.compile(r"^\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*([A-Za-z%/°.^0-9()·]*)\s*$")


def normalise_header(cell: str) -> str | None:
    c = re.sub(r"[^a-z0-9 /]", " ", (cell or "").lower()).strip()
    c = re.sub(r"\s+", " ", c)
    for predicate, synonyms in HEADER_SYNONYMS.items():
        if c in synonyms or any(c.startswith(s + " ") or c == s for s in synonyms):
            return predicate
    return None


def parse_value(raw: str) -> tuple[Any, str | None]:
    """'0.18 kg/kg' -> (0.18, 'kg/kg');  'Yes' -> (True, None);  'open' -> ('open', None)."""
    s = (raw or "").strip()
    if not s:
        return None, None
    if m := _NUM.match(s):
        num = float(m.group(1))
        unit = m.group(2) or None
        return (int(num) if num.is_integer() and "." not in m.group(1) else num), unit
    low = s.lower()
    if low in ("yes", "true", "y"):
        return True, None
    if low in ("no", "false", "n"):
        return False, None
    return s, None


# --------------------------------------------------------------------------- deterministic


#: Small tables are registers; long ones are datasets (a 600-row trace is not 600 facts).
_REGISTER_MAX_ROWS = 200
_HEADER_UNIT = re.compile(r"^(?P<base>.*?)\s*\((?P<unit>[^()]{1,12})\)\s*$")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")


def column_predicates(header: list[str]) -> tuple[dict[int, str], dict[int, str], int]:
    """Map every named column of a table to a predicate, not just the recognised ones.

    Returns (predicate per column, unit declared in the header per column, number of columns
    that matched the shared vocabulary). Three rules keep this lossless without guessing:

      * a header carrying its own unit, 'Area (m^2)', is a quantity and is named by its own
        words ('area'), never by a synonym that happens to share a first word;
      * an unrecognised header keeps its own name as the predicate, so a column the vocabulary
        has never seen still reaches the reconciler instead of being silently dropped;
      * two columns may not claim the same predicate: the exact synonym match keeps it and the
        other falls back to its own name ('From' -> from, 'From Port' -> from_port).
    """
    preds: dict[int, str] = {}
    units: dict[int, str] = {}
    exact: dict[str, int] = {}
    recognised = 0
    for j, raw in enumerate(header):
        raw = (raw or "").strip()
        if not raw:
            continue
        if m := _HEADER_UNIT.match(raw):
            units[j] = m.group("unit").strip()
            preds[j] = _slug(m.group("base")) or _slug(raw)
            continue
        canonical = normalise_header(raw)
        if canonical is None:
            preds[j] = _slug(raw)
            continue
        recognised += 1
        is_exact = _slug(raw).replace("_", " ") in HEADER_SYNONYMS[canonical]
        holder = exact.get(canonical)
        if holder is None:
            preds[j], exact[canonical] = canonical, j
        elif is_exact and _slug(header[holder]).replace("_", " ") not in HEADER_SYNONYMS[canonical]:
            preds[holder], preds[j], exact[canonical] = _slug(header[holder]), canonical, j
        else:
            preds[j] = _slug(raw)
    return preds, units, recognised


def claims_from_table(doc: Document, block: DocBlock, seq: Iterable[int]) -> list[EvidenceClaim]:
    """Lift one table into claims, one per non-empty cell under a named header.

    The subject of a row is its id column, or -- when no column is recognisably an id -- its
    first column, which is where every register we have seen puts the row's name.
    """
    rows = block.rows or []
    if len(rows) < 2 or (block.data or {}).get("role") == "timeseries":
        return []

    # Find the header row: the one with the most recognisable column names in the first 5 rows.
    best_idx, best_map, best_units, best_hits = 0, {}, {}, 0
    for i, row in enumerate(rows[:5]):
        preds, units, hits = column_predicates(row)
        if hits > best_hits:
            best_idx, best_map, best_units, best_hits = i, preds, units, hits
    if best_hits < 2:
        # Too few familiar headers to trust a vocabulary match. A short table still has a header:
        # by convention the first row with at least two named columns.
        if len(rows) > _REGISTER_MAX_ROWS:
            return []
        first = next((i for i, row in enumerate(rows[:5]) if sum(1 for c in row if (c or "").strip()) >= 2), None)
        if first is None:
            return []
        best_idx = first
        best_map, best_units, _ = column_predicates(rows[first])

    id_col = next((j for j, p in best_map.items() if p == "id"), None)
    if id_col is None:
        # An identifier has to identify: take the first column whose values are all distinct
        # ('Tank | B1', 'Tank | B2' is keyed by the second column, not the first).
        body = rows[best_idx + 1 :]
        for j in sorted(best_map):
            vals = [(r[j] or "").strip() for r in body if j < len(r) and (r[j] or "").strip()]
            if vals and len(vals) == len(set(vals)):
                id_col = j
                break
        if id_col is None:
            return []
    out: list[EvidenceClaim] = []
    sheet = (block.data or {}).get("sheet") or block.locator.sheet

    # Long-format: the attribute each row is about is named in a *cell*, not in the header.
    #
    #   Mark   | Parameter | Value | Unit          ZN-1 . C = 300 kJ/K
    #   ZN-1   | C         | 300   | kJ/K    -->   EF-1 . G = 450 W/K
    #   EF-1   | G         | 450   | W/K
    #
    # Read column-wise instead and every one of these rows says the same thing -- "value" --
    # about a different subject, and the attribute name is thrown away. Worse, the equipment
    # mark then looks like a parameter id, so the plant's components disappear into the
    # parameter table and the model comes out empty.
    attr_col = next((j for j, p in best_map.items() if p == "attribute"), None)
    value_col = next((j for j, p in best_map.items() if p == "value"), None)
    unit_col = next((j for j, p in best_map.items() if p == "unit"), None)
    long_format = attr_col is not None and value_col is not None

    for r, row in enumerate(rows[best_idx + 1 :], start=best_idx + 2):
        subject = (row[id_col].strip() if id_col < len(row) else "")
        if not subject:
            continue

        if long_format:
            attr = (row[attr_col] or "").strip() if attr_col < len(row) else ""
            raw = (row[value_col] or "").strip() if value_col < len(row) else ""
            if attr and raw:
                value, unit = parse_value(raw)
                if unit is None and unit_col is not None and unit_col < len(row):
                    unit = (row[unit_col] or "").strip() or None
                predicate = _slug(attr)
                out.append(
                    EvidenceClaim(
                        id=f"CLM-{next(iter(seq)):05d}",
                        source_id=doc.source.id,
                        locator=Locator(
                            sheet=sheet, cell=f"{_col_letter(value_col)}{r}",
                            page=block.locator.page, section=block.locator.section,
                        ),
                        kind="parameter",
                        subject=subject,
                        predicate=predicate,
                        value=value,
                        unit=unit,
                        quote=" | ".join(c for c in row if c)[:300],
                        confidence=0.95,
                        extracted_by="t0_deterministic",
                    )
                )

        for j, predicate in best_map.items():
            if j == id_col or j >= len(row):
                continue
            if long_format and j in (attr_col, value_col, unit_col):
                continue  # already emitted, under the attribute's own name
            cell = (row[j] or "").strip()
            if not cell:
                continue
            value, unit = parse_value(cell)
            if unit is None and j in best_units and isinstance(value, (int, float)):
                unit = best_units[j]
            out.append(
                EvidenceClaim(
                    id=f"CLM-{next(iter(seq)):05d}",
                    source_id=doc.source.id,
                    locator=Locator(
                        sheet=sheet, cell=f"{_col_letter(j)}{r}", page=block.locator.page,
                        section=block.locator.section,
                    ),
                    kind=_kind_for(predicate),
                    subject=subject,
                    predicate=predicate,
                    value=value,
                    unit=unit,
                    quote=" | ".join(c for c in row if c)[:300],
                    confidence=0.95,
                    extracted_by="t0_deterministic",
                )
            )
    return out


def claims_from_keyvalues(doc: Document, seq: Iterable[int]) -> list[EvidenceClaim]:
    out: list[EvidenceClaim] = []
    for b in doc.blocks:
        if b.kind != "keyvalue" or not b.data:
            continue
        path = str(b.data.get("path", ""))
        subject = path.split(".")[-1] if path else "document"
        value = b.data.get("value")
        out.append(
            EvidenceClaim(
                id=f"CLM-{next(iter(seq)):05d}",
                source_id=doc.source.id,
                locator=b.locator,
                kind="parameter",
                subject=subject,
                predicate=path,
                value=value,
                quote=b.text[:200],
                confidence=0.95,
                extracted_by="t0_deterministic",
            )
        )
    return out


def claims_from_graph(doc: Document, seq: Iterable[int]) -> list[EvidenceClaim]:
    """PlantUML and similar: edges are connection claims, exactly, with no interpretation."""
    out: list[EvidenceClaim] = []
    for b in doc.blocks:
        if b.kind != "graph" or not b.rows:
            continue
        for row in b.rows[1:]:
            if len(row) < 2:
                continue
            out.append(
                EvidenceClaim(
                    id=f"CLM-{next(iter(seq)):05d}",
                    source_id=doc.source.id,
                    locator=b.locator,
                    kind="connection",
                    subject=row[0],
                    predicate="connects_to",
                    value=row[1],
                    quote=" ".join(row),
                    confidence=0.9,
                    extracted_by="t0_deterministic",
                )
            )
    return out


SUPERSEDE_RE = re.compile(
    r"(?P<winner>[A-Z]{2,}[-\s]?\d{2,}|\b[A-Z][a-z]+ \d+\b).{0,80}?"
    r"\b(?:supersedes?|supersed(?:ing|ed)|overrides?|corrects?|replaces?)\b.{0,80}?"
    r"(?P<loser>[A-Z]{2,}[-\s]?\d{2,}|legacy \w+|archived \w+|the \w+ (?:note|extract|routing))",
    re.I | re.S,
)


def claims_from_supersession(doc: Document, seq: Iterable[int]) -> list[EvidenceClaim]:
    """Find explicit supersession statements anywhere in prose. These drive precedence rule P1.

    Cheap, high value and deterministic: the sentence that says "CR-017 supersedes the legacy
    routing" is the single most decisive piece of evidence in a packet like this.
    """
    out: list[EvidenceClaim] = []
    for b in doc.blocks:
        if b.kind not in ("paragraph", "heading", "table"):
            continue
        for m in SUPERSEDE_RE.finditer(b.text):
            out.append(
                EvidenceClaim(
                    id=f"CLM-{next(iter(seq)):05d}",
                    source_id=doc.source.id,
                    locator=b.locator,
                    kind="supersession",
                    subject=m.group("winner").strip(),
                    predicate="supersedes",
                    value=m.group("loser").strip(),
                    quote=b.text[max(0, m.start() - 60) : m.end() + 60],
                    confidence=0.8,
                    extracted_by="t0_deterministic",
                )
            )
    return out


# --------------------------------------------------------------------------- model path

CLAIM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["claims"],
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["kind", "subject", "predicate", "value", "quote"],
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": [
                            "requirement", "parameter", "component", "port", "connection",
                            "signal", "state", "transition", "interlock", "scenario",
                            "acceptance_check", "ownership", "supersession", "domain_hint", "note",
                        ],
                    },
                    "subject": {"type": "string"},
                    "predicate": {"type": "string"},
                    "value": {},
                    "unit": {"type": "string"},
                    "quote": {"type": "string"},
                    "confidence": {"type": "number"},
                },
            },
        }
    },
}

EXTRACT_PROMPT = """\
Extract engineering facts from the text below. One fact per claim.

Rules:
- `quote` must be copied verbatim from the text. If you cannot quote it, do not claim it.
- Never convert, round or infer a number that is not written down.
- `subject` is the tag or identifier the fact is about (e.g. a component tag, a parameter id).
- Report what the text SAYS, even if it contradicts something you believe. Contradictions are
  resolved later and are valuable; suppressing one loses information.
- If the text states that one document supersedes another, emit a claim of kind
  "supersession" with subject = the superseding record and value = the superseded record.

TEXT
{chunk}
"""

DIAGRAM_PROMPT = """\
You are reading an engineering diagram (a P&ID, schematic or similar image).

Rules:
- Extract only components, ports and connections you can actually see labelled in the image.
- `quote` must be the visible label or tag text next to the element -- never a description.
- If a label is not legible, do not invent one; omit that element instead.
- For a connection between two tags A and B, use predicate "connects_to" with subject = A and
  value = B.
- Only use kind: "component", "port", "connection", "domain_hint" or "note".
"""

_DIAGRAM_KINDS = {"component", "port", "connection", "domain_hint", "note"}

#: Model-reported confidence is neither calibrated nor trustworthy across providers; a fixed
#: value per path keeps EvidenceClaim.confidence meaningful (and always inside Pydantic's
#: [0, 1] bound) regardless of what a given model happened to put in the "confidence" field.
_TEXT_CONFIDENCE = 0.6
_VISION_CONFIDENCE = 0.4


def _normalise_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _quote_ok(quote: str, haystack: str) -> bool:
    """Whitespace-insensitive substring check: the actual fabrication guard.

    Whitespace is collapsed on both sides because a chunk joins several blocks with "\\n", so a
    real quote spanning that join (or containing an odd double space) would otherwise be a false
    negative. Nothing else is forgiven: an invented word, number or unit still fails.
    """
    q = _normalise_ws(quote)
    return bool(q) and q in _normalise_ws(haystack)


def _quote_is_verbatim(chunk: str) -> Callable[[Any], tuple[bool, str]]:
    """Router-level validator: only escalate/retry when a response is *entirely* useless.

    Per-claim rejection happens separately, after a response has already validated -- one
    fabricated quote among many good ones should not throw away the good ones and cost a second
    model call.
    """

    def validate(data: Any) -> tuple[bool, str]:
        claims = (data or {}).get("claims", [])
        if claims and not any(_quote_ok(c.get("quote", ""), chunk) for c in claims):
            return False, "none of the returned quotes are verbatim substrings of the source text"
        return True, ""

    return validate


def _diagram_claims_are_plausible(data: Any) -> tuple[bool, str]:
    for i, c in enumerate((data or {}).get("claims", [])):
        if c.get("kind") not in _DIAGRAM_KINDS:
            return False, f"claims[{i}]: kind '{c.get('kind')}' is not plausible from an image alone"
        if not str(c.get("quote") or "").strip():
            return False, f"claims[{i}]: empty quote (must cite the visible label)"
    return True, ""


def _to_claims(
    data: Any,
    doc: Document,
    locator: Locator,
    seq: Iterable[int],
    tier: str,
    confidence: float,
    quote_check: Callable[[str], bool] | None = None,
) -> tuple[list[EvidenceClaim], int]:
    """Convert a validated `{"claims": [...]}` payload into EvidenceClaims.

    `quote_check`, when given, drops individual claims that fail it (the verbatim check, applied
    per-claim rather than per-response) and returns how many were dropped, so the caller can
    record an honest warning instead of silently losing evidence.
    """
    claims: list[EvidenceClaim] = []
    dropped = 0
    for c in (data or {}).get("claims", []):
        subject = str(c.get("subject") or "").strip()
        quote = str(c.get("quote") or "")
        if not subject:
            dropped += 1
            continue
        if quote_check is not None and not quote_check(quote):
            dropped += 1
            continue
        claims.append(
            EvidenceClaim(
                id=f"CLM-{next(iter(seq)):05d}",
                source_id=doc.source.id,
                locator=locator,
                kind=c.get("kind", "note"),
                subject=subject,
                predicate=str(c.get("predicate") or ""),
                value=c.get("value"),
                unit=c.get("unit"),
                quote=quote,
                confidence=confidence,
                extracted_by=tier,
            )
        )
    return claims, dropped


def extract_claims(docs: list[Document], router: Any | None = None) -> list[EvidenceClaim]:
    """Run the deterministic path over everything, then the model path over unstructured prose
    and the vision path over any images (P&IDs, rasterised scanned pages)."""
    counter = _Counter()
    out: list[EvidenceClaim] = []

    for doc in docs:
        for block in doc.tables():
            out.extend(claims_from_table(doc, block, counter))
        out.extend(claims_from_keyvalues(doc, counter))
        out.extend(claims_from_graph(doc, counter))
        out.extend(claims_from_supersession(doc, counter))

    if router is None:
        return out

    # Tags the deterministic pass established. Topology extraction is grounded on exactly
    # this set, so a model can relate things the evidence named and nothing else.
    known: dict[str, str] = {}
    for c in out:
        if c.extracted_by == "t0_deterministic" and _looks_like_mark(c.subject):
            known.setdefault(_norm_tag(c.subject), c.subject.strip())
    if known and not any(c.kind == "connection" for c in out):
        # Only when nothing deterministic produced a graph. A packet that ships a PlantUML
        # or a connection register has already said how it is wired, exactly, for free.
        for doc in docs:
            out.extend(claims_from_topology(doc, router, known, counter))

    for doc in docs:
        for chunk, locator in doc.chunks(kinds=_PROSE_KINDS):
            try:
                resp = router.run(
                    "extract_claim",
                    EXTRACT_PROMPT.format(chunk=chunk),
                    schema=CLAIM_SCHEMA,
                    validator=_quote_is_verbatim(chunk),
                )
            except LLMError as exc:
                doc.warnings.append(f"extract_claim failed for a chunk: {exc}")
                continue
            claims, dropped = _to_claims(
                resp.data, doc, locator, counter, resp.tier, _TEXT_CONFIDENCE,
                quote_check=lambda q, chunk=chunk: _quote_ok(q, chunk),
            )
            out.extend(claims)
            if dropped:
                doc.warnings.append(f"dropped {dropped} non-verbatim claim(s) from a chunk")

        for block in doc.images():
            try:
                resp = router.run(
                    "read_diagram",
                    DIAGRAM_PROMPT,
                    schema=CLAIM_SCHEMA,
                    images=[block.image],
                    validator=_diagram_claims_are_plausible,
                )
            except LLMError as exc:
                doc.warnings.append(f"read_diagram failed for an image: {exc}")
                continue
            claims, dropped = _to_claims(
                resp.data, doc, block.locator, counter, resp.tier, _VISION_CONFIDENCE,
            )
            out.extend(claims)
            if dropped:
                doc.warnings.append(f"dropped {dropped} implausible claim(s) from a diagram")

    return out


class _Counter:
    """Shared id sequence. `next(iter(counter))` yields the next integer."""

    def __init__(self) -> None:
        self.n = 0

    def __iter__(self):
        while True:
            self.n += 1
            yield self.n


def _kind_for(predicate: str) -> str:
    return {
        "requirement": "requirement",
        "value": "parameter",
        "unit": "parameter",
        "from": "connection",
        "to": "connection",
        "port": "port",
        "guard": "transition",
        "action": "state",
        "next": "transition",
        "region": "state",
        "ownership": "ownership",
        "superseded_by": "supersession",
        "verification": "acceptance_check",
    }.get(predicate, "note")


def _col_letter(idx: int) -> str:
    out = ""
    idx += 1
    while idx:
        idx, rem = divmod(idx - 1, 26)
        out = chr(65 + rem) + out
    return out


# ----------------------------------------------------------------------------- topology

TOPOLOGY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["connections"],
    "properties": {
        "connections": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["from", "to", "quote"],
                "properties": {
                    "from": {"type": "string"},
                    "to": {"type": "string"},
                    "medium": {"type": "string"},
                    "quote": {"type": "string"},
                },
            },
        }
    },
}

TOPOLOGY_PROMPT = """\
List how these components are connected, using ONLY the tags given.

TAGS
{tags}

Rules:
- `from` and `to` must each be one of the TAGS above, copied exactly. Never invent a tag, and
  never use a name that is not in the list.
- One entry per connection. Direction matters: `from` is upstream, source, or the side that
  supplies; `to` is downstream, sink, or the side that receives.
- `quote` must be copied verbatim from the text and must be the words that state or draw this
  connection. If you cannot quote it, do not claim it.
- Include connections drawn in diagrams as well as ones written in sentences.
- A component described as a boundary or supply still connects to whatever it feeds.
- If something sits BETWEEN two others -- in a sketch, or in a phrase like "A loses heat
  through B to C" -- then it connects to each of them separately: A-B and B-C. Do NOT also
  connect A straight to C. The thing in the middle is there precisely because the two ends
  do not touch.
- Give each connection once. A and B joined is one entry, not two in opposite directions.
- If the text states no connections at all, return an empty list.

TEXT
{chunk}
"""


def claims_from_topology(
    doc: Document, router: Any, tags: dict[str, str], seq: Iterable[int]
) -> list[EvidenceClaim]:
    """Ask a model how the known components are wired, and accept nothing it invents.

    The NaCl packet ships a PlantUML graph, so the connection graph arrived for free from a
    deterministic reader and this path was never needed. Most packets are not so kind: an
    HVAC design basis draws its arrangement in an ASCII sketch and describes it in a
    sentence, and with no reader for either, every component came out correctly bound and
    completely unconnected -- a model with four parts and no equations, which will not even
    build.

    Two things keep this from becoming a fabrication engine. The tag list is supplied and
    both endpoints must come from it, so the model can only relate things the evidence
    already established; and the quote must be verbatim, so a connection nobody wrote down
    cannot survive. Anything else it returns is dropped and counted.
    """
    if router is None or not tags:
        return []
    out: list[EvidenceClaim] = []
    dropped = 0
    #: Pairs already claimed, in either order. An acausal connection has no direction, so
    #: A->B and B->A are one wire; emitting both declares the same junction twice.
    joined: set[frozenset[str]] = set()
    listing = "\n".join(f"- {t}" for t in sorted(tags.values()))

    for chunk, locator in doc.chunks(kinds=_PROSE_KINDS):
        try:
            resp = router.run(
                "extract_claim",
                TOPOLOGY_PROMPT.format(tags=listing, chunk=chunk),
                schema=TOPOLOGY_SCHEMA,
            )
        except LLMError as exc:
            doc.warnings.append(f"topology extraction failed for a chunk: {exc}")
            continue

        for item in (resp.data or {}).get("connections", []) or []:
            src = tags.get(_norm_tag(str(item.get("from", ""))))
            dst = tags.get(_norm_tag(str(item.get("to", ""))))
            quote = str(item.get("quote", ""))
            if not src or not dst or src == dst or not _quote_ok(quote, chunk):
                dropped += 1
                continue
            if frozenset((src, dst)) in joined:
                continue
            joined.add(frozenset((src, dst)))
            subject = f"LNK-{src}-{dst}"
            for predicate, value in (("from", src), ("to", dst),
                                     ("medium", str(item.get("medium", "") or "") or None)):
                if value is None:
                    continue
                out.append(
                    EvidenceClaim(
                        id=f"CLM-{next(iter(seq)):05d}",
                        source_id=doc.source.id,
                        locator=locator,
                        kind="connection",
                        subject=subject,
                        predicate=predicate,
                        value=value,
                        quote=quote[:300],
                        confidence=_TEXT_CONFIDENCE,
                        extracted_by=resp.tier,
                    )
                )
    if dropped:
        doc.warnings.append(
            f"dropped {dropped} connection(s) that used an unknown tag or an unquotable claim"
        )
    return out


def _norm_tag(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


#: Tag-shaped, or a short all-caps mark. Mirrors reconcile.entities.looks_like_mark; kept
#: local so the extractor does not import the reconciler.
_MARK_RE = re.compile(r"(?:[A-Z]{1,4}[-_]?\d{1,4}[A-Z]?|[A-Z]{2,5})")


def _looks_like_mark(s: str) -> bool:
    return bool(_MARK_RE.fullmatch(str(s).strip()))
