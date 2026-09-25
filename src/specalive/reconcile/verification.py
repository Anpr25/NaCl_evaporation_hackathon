"""Acceptance criteria written in prose, and the instrument bindings they depend on.

The NaCl packet states its acceptance criteria as a step table, so every check falls out of
the state machine: each threshold the sequence waits on becomes a check. A commissioning
sheet does not work like that. It states criteria in sentences against instrument tags --
"TT-2101 rises through 20.5 degC", "TT-2101 at end of test is at or below 21.5 degC" -- and
the HVAC packet extracted, bound, compiled and simulated perfectly while scoring 0/0, because
nothing turned those sentences into anything checkable. A model that runs and verifies
nothing is not evidence of very much.

Two things are needed and neither is packet-specific:

  * an instrument must be bound to a plant quantity, and documents almost never say so
    outright. A schedule calls TT-2101 the "zone air temperature transmitter"; the binding is
    in that phrase and nowhere else.
  * the handful of ways engineers write a pass/fail criterion must map onto the checking
    grammar. There are not many, and they are the same in every discipline.

Both are inferences, so both are declared, and an ambiguous binding is never guessed: it
becomes a gap, and the criteria that depended on it are reported unverifiable rather than
quietly dropped.

Owner: D.
"""

from __future__ import annotations

import math
import re

from ..ir.evidence import EvidenceClaim, Gap
from ..ir.system import AcceptanceCheck, Provenance, Signal, SystemModel
from .entities import ident, looks_like_mark, measurement_var, names_an_instrument, to_si

_WORD = re.compile(r"[a-z]+")

#: Words that say nothing about which component an instrument watches.
_STOPWORDS = frozenset({
    "the", "a", "an", "of", "for", "and", "or", "to", "in", "on", "at", "with",
    "transmitter", "sensor", "indicator", "gauge", "controller", "thermostat", "probe",
    "detector", "transducer", "element", "unit", "type", "mounted", "wall", "local",
})

_NUM = r"[-+]?\d*\.?\d+"
_UNIT = r"[A-Za-z°%/.]{0,8}"

#: The ways a criterion says "this quantity must pass this value going up".
_RISING = re.compile(
    rf"(?P<tag>[A-Za-z][\w\-]*)\s+(?:\w+\s+){{0,3}}?"
    rf"(?:rises?\s+(?:through|above|past)|reaches|exceeds|climbs?\s+(?:to|through)|"
    rf"goes?\s+above|attains)\s+(?P<n>{_NUM})\s*(?P<u>{_UNIT})",
    re.I,
)
#: ...and going down.
_FALLING = re.compile(
    rf"(?P<tag>[A-Za-z][\w\-]*)\s+(?:\w+\s+){{0,3}}?"
    rf"(?:falls?\s+(?:through|below|past|to)|drops?\s+(?:below|to)|cools?\s+to|"
    rf"goes?\s+below|decays?\s+to)\s+(?P<n>{_NUM})\s*(?P<u>{_UNIT})",
    re.I,
)
#: A statement about where the run ends, rather than about crossing.
_FINAL = re.compile(
    rf"(?P<tag>[A-Za-z][\w\-]*)\s+(?:at\s+)?(?:the\s+)?end\s+of\s+(?:the\s+)?test\s+"
    rf"is\s+(?P<dir>at\s+or\s+below|at\s+or\s+above|below|above|no\s+more\s+than|"
    rf"no\s+less\s+than)\s+(?P<n>{_NUM})\s*(?P<u>{_UNIT})",
    re.I,
)
#: "reaches X before it reaches Y" -- ordering, which the checker expresses with before().
_ORDER = re.compile(
    rf"(?P<tag>[A-Za-z][\w\-]*)\s+reaches\s+(?P<a>{_NUM})\s*(?P<ua>{_UNIT})\s+"
    rf"before\s+(?:it\s+)?reaches\s+(?P<b>{_NUM})\s*(?P<ub>{_UNIT})",
    re.I,
)

_FINAL_OPS = {
    "at or below": "<=", "no more than": "<=", "below": "<=",
    "at or above": ">=", "no less than": ">=", "above": ">=",
}


def _words(text: str) -> list[str]:
    return [w for w in _WORD.findall((text or "").lower()) if w not in _STOPWORDS]


def _best_block(model: SystemModel, text: str) -> tuple[str | None, bool]:
    """Which component an instrument description is talking about, and whether it was clear.

    Scored by inverse document frequency over the component descriptions, because a shared
    word decides nothing and a rare one decides everything: "zone air temperature" overlaps
    "Zone thermal mass" on *zone* and "Outdoor air" on *air*, a tie on raw counts, and only
    the fact that *zone* appears once and *air* twice says which is meant.
    """
    blocks = model.simulatable_blocks()
    if not blocks:
        return None, False

    # What a component *is* lives in its name; its description carries context, including
    # other components. The envelope's own comment says "zone to outdoor air", which makes it
    # the best textual match for a zone air transmitter and the wrong answer.
    names = {b.id: set(_words(f"{b.name} {b.kind}")) for b in blocks}
    descs = {b.id: set(_words(b.description or "")) - names[b.id] for b in blocks}

    n = len(blocks)
    freq: dict[str, int] = {}
    for bid in names:
        for w in names[bid] | descs[bid]:
            freq[w] = freq.get(w, 0) + 1

    # Instrument descriptions read qualifier first and device last -- "zone air temperature
    # transmitter" is about the zone, not about transmitters -- so an earlier word says more
    # about what is being measured.
    ordered = _words(text)
    position: dict[str, float] = {}
    for i, w in enumerate(ordered):
        position.setdefault(w, 1.0 / (1.0 + i))

    def weight(w: str) -> float:
        return position[w] * math.log(1 + n / freq[w])

    scores = {
        bid: sum(weight(w) for w in (position.keys() & names[bid]))
        + 0.3 * sum(weight(w) for w in (position.keys() & descs[bid]))
        for bid in names
    }
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    if not ranked or ranked[0][1] <= 0:
        return None, False
    clear = len(ranked) == 1 or ranked[0][1] > ranked[1][1] * 1.3
    return ranked[0][0], clear


def bind_instruments(model: SystemModel, entities: dict) -> list[Gap]:
    """Turn instrument rows into bound sensor signals, or say why we could not.

    Only acts on instruments that produced no signal already: a packet whose register gives
    instruments a location and a measured variable has said all this explicitly, and nothing
    here should second-guess it.
    """
    gaps: list[Gap] = []
    for e in entities.values():
        text = " ".join(
            x for x in (e.text("name"), e.text("description"), e.text("kind")) if x
        )
        if not looks_like_mark(e.subject) or not names_an_instrument(text):
            continue
        sid = ident(e.subject)
        if model.signal(sid) is not None:
            continue

        var = measurement_var(text)
        block, clear = _best_block(model, text)
        if var is None or block is None or not clear:
            gaps.append(
                Gap(
                    id=f"GAP-INST-{len(gaps) + 1:02d}",
                    kind="unextracted",
                    subject=e.subject,
                    detail=(
                        f"{e.subject} is described as an instrument (\"{text[:90]}\") but no "
                        f"document says what it reads. "
                        + (
                            "Its description does not name a measurable quantity."
                            if var is None
                            else f"Its description does not point clearly at one component "
                                 f"(best guess {block or 'none'}), so no binding was invented."
                        )
                    ),
                    severity="warn",
                    workaround="Ask which component and quantity this tag measures.",
                )
            )
            continue

        model.signals.append(
            Signal(
                id=sid,
                name=sid,
                role="sensor",
                datatype="real",
                binding=f"{block}.{var}",
                owner="controller",
                provenance=Provenance(
                    claim_ids=e.claim_ids,
                    note=(
                        f"binding inferred from the instrument's own description: it names "
                        f"{var!r} and points at {block}"
                    ),
                ),
            )
        )
    return gaps


def _si(raw: str, unit: str | None) -> float:
    value, _, _ = to_si(float(raw), unit or None, temperature=True)
    return float(value)


def checks_from_criteria(model: SystemModel, claims: list[EvidenceClaim]) -> list[Gap]:
    """Turn prose pass/fail criteria into acceptance checks against bound signals.

    Skipped entirely when the scenario already has checks: a packet that states its criteria
    structurally has said them better than any phrase matching could.
    """
    if not model.scenarios or model.scenarios[0].checks:
        return []
    scenario = model.scenarios[0]
    by_tag = {s.id.lower(): s for s in model.signals if s.binding}
    by_tag.update({s.id.replace("_", "-").lower(): s for s in model.signals if s.binding})

    gaps: list[Gap] = []
    unmatched: set[str] = set()
    seen: set[str] = set()

    def signal_for(tag: str) -> Signal | None:
        hit = by_tag.get(tag.lower()) or by_tag.get(tag.replace("-", "_").lower())
        if hit is None:
            unmatched.add(tag)
        return hit

    def add(cid: str, desc: str, kind: str, expr: str, claim: EvidenceClaim) -> None:
        if expr in seen:
            return
        seen.add(expr)
        scenario.checks.append(
            AcceptanceCheck(
                id=cid,
                description=desc,
                kind=kind,  # type: ignore[arg-type]
                expression=expr,
                provenance=Provenance(
                    claim_ids=[claim.id],
                    note="parsed from a criterion stated in prose",
                ),
            )
        )

    for c in claims:
        text = c.value if isinstance(c.value, str) else ""
        if not text:
            continue
        ref = str(c.subject).strip()

        for m in _ORDER.finditer(text):
            sig = signal_for(m.group("tag"))
            if sig is None:
                continue
            a = _si(m.group("a"), m.group("ua"))
            b = _si(m.group("b"), m.group("ub"))
            add(f"CHK-{ref}", text[:110], "ordering",
                f"before(crosses({sig.binding}, {a:g}, rising), "
                f"crosses({sig.binding}, {b:g}, rising))", c)

        for m in _FINAL.finditer(text):
            sig = signal_for(m.group("tag"))
            if sig is None:
                continue
            op = _FINAL_OPS[re.sub(r"\s+", " ", m.group("dir").lower())]
            add(f"CHK-{ref}", text[:110], "final_value",
                f"final({sig.binding}) {op} {_si(m.group('n'), m.group('u')):g}", c)

        if _ORDER.search(text) or _FINAL.search(text):
            continue  # an ordering or end-of-test clause is not also a bare crossing

        for rx, direction in ((_RISING, "rising"), (_FALLING, "falling")):
            for m in rx.finditer(text):
                sig = signal_for(m.group("tag"))
                if sig is None:
                    continue
                add(f"CHK-{ref}", text[:110], "threshold",
                    f"crosses({sig.binding}, {_si(m.group('n'), m.group('u')):g}, "
                    f"{direction})", c)

    if unmatched:
        gaps.append(
            Gap(
                id="GAP-CRIT-01",
                kind="unimplemented_requirement",
                subject=", ".join(sorted(unmatched)),
                detail=(
                    f"{len(unmatched)} acceptance criterion tag(s) could not be checked "
                    f"because no bound signal corresponds to them. The criteria are in the "
                    f"evidence and are not being quietly dropped; they are unverifiable "
                    f"until the tag is bound to a plant quantity."
                ),
                severity="warn",
                workaround="Bind the instrument, then re-run; the criteria need no rewriting.",
            )
        )
    return gaps
