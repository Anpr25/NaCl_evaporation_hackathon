"""Documents -> typed EvidenceClaims.

Two paths, and the split is the whole point:

  T0 deterministic -- any table with a recognisable header, any key/value pair, any PlantUML
  edge, any Modelica declaration. Exact, free, offline. On the NaCl packet this alone produces
  the large majority of claims.

  T1/T2/T3 model -- only the prose that no parser can structure, chunked, schema-constrained,
  and always carrying the locator of the chunk it came from.

An extractor reports what a document *says*. It never decides what is *true*; that is the
reconciler's job, and keeping the two apart is what makes the decision log trustworthy.

Owner: A.  STATUS: deterministic path implemented; model path is scaffolded and marked TODO.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from ..ir.evidence import EvidenceClaim, Locator
from ..ingest.base import DocBlock, Document

# --------------------------------------------------------------------------- header matching

#: Column-header synonyms -> the IR predicate they populate. Domain-agnostic vocabulary: these
#: are the words engineering registers use regardless of whether the plant is chemical,
#: electrical or mechanical. Extend freely; a miss costs a claim, never a wrong claim.
HEADER_SYNONYMS: dict[str, tuple[str, ...]] = {
    "id": ("id", "tag", "item", "ref", "reference", "req id", "parameter id", "no", "number"),
    "name": ("name", "title", "description", "designation", "service"),
    "kind": ("type", "kind", "class", "category", "model class", "role", "equipment type"),
    "value": ("value", "setpoint", "setting", "nominal", "rating", "quantity", "target"),
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

    for r, row in enumerate(rows[best_idx + 1 :], start=best_idx + 2):
        subject = (row[id_col].strip() if id_col < len(row) else "")
        if not subject:
            continue
        for j, predicate in best_map.items():
            if j == id_col or j >= len(row):
                continue
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


def extract_claims(docs: list[Document], router: Any | None = None) -> list[EvidenceClaim]:
    """Run the deterministic path over everything, then the model path over unstructured prose."""
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

    # TODO(A): the model path.
    #   for doc in docs:
    #       for chunk, locator in doc.chunks():
    #           if _already_covered(chunk, out): continue      # do not pay twice for a table
    #           resp = router.run("extract_claim", EXTRACT_PROMPT.format(chunk=chunk),
    #                             schema=CLAIM_SCHEMA, validator=_quote_is_verbatim(chunk))
    #           out.extend(_to_claims(resp.data, doc, locator, resp.tier))
    #   Then the vision path for doc.images() via router.run("read_diagram", ..., images=[...]).
    #   The validator matters more than the prompt: reject any claim whose `quote` is not a
    #   literal substring of the chunk. That single check removes almost all small-model
    #   fabrication, and it is free.
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
