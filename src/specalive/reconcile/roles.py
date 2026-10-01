"""What each part IS in the executable model, decided before anything is bound.

A register lists everything with a tag: tanks, valves, level transmitters, push-buttons, the
PLC. They are not the same kind of thing, and treating them the same way was the root of a
whole family of failures. A level transmitter sent to the catalog comes back as whatever
class scores best on the words "level transmitter" -- or as nothing -- when what the model
needs is a *reading* of the tank's level. A start push-button came back as a soft-start
controller for an AC converter. Neither is a component; both are signals.

So each part gets a role first:

  component    a physical or block-diagram element that becomes a component instance;
  boundary     a source, sink or ground at the edge of the system (still a component);
  instrument   a reading of a variable on another part -- becomes a sensor signal;
  operator     a manual command into the controller -- becomes a manual input signal;
  controller   a supervisory controller (PLC, DCS) whose behaviour is the state machine.

Decided from the shape of the evidence, in order of strength: what the register calls the
part, what it is connected to, and -- only where those are silent -- the whole-packet read's
classification. A block-diagram sensor that feeds a gain is a component, not an instrument:
the rule is about what the part is *used as*, not what it is called.

Owner: B.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Literal

from .entities import Entity, humanise, measurement_var, norm

Role = Literal["component", "boundary", "instrument", "operator", "controller"]

#: Words that say "this measures something". 'switch' is deliberately absent: a level
#: switch is an instrument but a hand switch is an operator input, and the word alone
#: cannot tell them apart; the ISA letter pattern below can.
_INSTRUMENT_WORDS = ("transmitter", "sensor", "indicator", "gauge", "meter", "analyser",
                     "analyzer", "probe", "thermocouple", "detector", "measurement")
_OPERATOR_WORDS = ("pushbutton", "push button", "push-button", "button", "selector",
                   "hand switch", "hmi", "operator command", "momentary", "e-stop",
                   "emergency stop", "keyswitch")
#: A supervisory controller runs the sequence; a feedback block (PID, PI, LimPID) is a
#: component of a block diagram and binds like any other.
_SUPERVISORY_WORDS = ("plc", "dcs", "programmable", "sequence controller", "logic solver",
                      "supervisory", "bms controller", "scada")
_FEEDBACK_WORDS = ("pid", "pi controller", "p controller", "feedback", "limpid", "regulator")
_BOUNDARY_WORDS = ("source", "sink", "boundary", "ground", "atmosphere", "ambient", "drain",
                   "supply header", "reservoir boundary")

#: ISA-5.1 instrument tags: a measured-variable letter, then readout/function letters.
#: LT, LIS, TT, PT, FT, QI, TIS, AE, FIC. `TK-101` (tank) and `PB-START` do not match:
#: K and B are not function letters.
_ISA_TAG = re.compile(
    r"^(?P<var>[ALFPTQWDSZ])(?P<fn>T|I|IT|IS|ISH|ISL|IC|E|R|IR|S|SH|SL)[-_]?\d", re.I
)
_ISA_VAR = {"L": "level", "T": "T", "P": "p", "F": "m_flow", "A": "w", "Q": "w", "W": "w",
            "D": "d", "S": "w", "Z": "s"}


@dataclass
class RoleDecision:
    role: Role
    basis: str
    #: For an instrument: the part it reads, and the variable on that part.
    host: str | None = None
    variable: str | None = None
    #: True when the decision is only the default, so a weaker source may override it.
    default: bool = False
    claim_ids: list[str] = field(default_factory=list)


def _text(e: Entity) -> str:
    return " ".join(
        humanise(e.text(p)) for p in ("type", "kind", "modelclass", "name", "role", "service")
    ).lower()


def _has(words: Iterable[str], text: str) -> bool:
    return any(re.search(rf"\b{re.escape(w)}\b", text) for w in words)


def classify_roles(
    entities: dict[str, Entity],
    part_keys: list[str],
    neighbours: dict[str, set[str]],
    known: dict[str, str],
) -> dict[str, RoleDecision]:
    """One decision per part key. `neighbours` maps a part key to the part keys it is
    connected to by physical or block-diagram connection records."""
    out: dict[str, RoleDecision] = {}
    supervisory: set[str] = set()
    for key in part_keys:
        e = entities[key]
        if _has(_SUPERVISORY_WORDS, f"{_text(e)} {humanise(e.subject).lower()}") or (
            "controller" in _text(e) and not _has(_FEEDBACK_WORDS, _text(e))
            and not neighbours.get(key)
        ):
            supervisory.add(key)

    for key in part_keys:
        e = entities[key]
        text = _text(e)
        peers = neighbours.get(key, set())
        # A part is *used as* a block when something other than a supervisory controller
        # consumes what it produces. That is what keeps an IAQ CO2 sensor feeding a gain a
        # component, and makes a tank's level transmitter wired only to the PLC a reading.
        feeds_blocks = bool(peers - supervisory)

        if key in supervisory:
            out[key] = RoleDecision("controller", "a supervisory controller; its behaviour is "
                                    "the extracted state machine", claim_ids=e.claim_ids)
            continue
        if _has(_OPERATOR_WORDS, text):
            out[key] = RoleDecision("operator", "a manual command into the controller, not a "
                                    "component", claim_ids=e.claim_ids)
            continue
        isa = _ISA_TAG.match(e.subject.strip())
        if (_has(_INSTRUMENT_WORDS, text) or isa) and not feeds_blocks:
            var = measurement_var(text) or (
                _ISA_VAR.get(isa.group("var").upper()) if isa else None
            )
            host, why = find_host(e, entities, part_keys, known)
            out[key] = RoleDecision(
                "instrument",
                f"reads a variable on another part ({why})" if host else
                "an instrument whose host part the evidence does not name",
                host=host, variable=var, claim_ids=e.claim_ids,
            )
            continue
        # What the part IS, not what it serves: a valve whose service is "TK-102 to drain"
        # is not a drain, and a gain whose role is "ACH to source mass flow" is not a source.
        what = " ".join(humanise(e.text(p)) for p in ("type", "kind", "modelclass")).lower()
        if _has(_BOUNDARY_WORDS, what):
            out[key] = RoleDecision("boundary", "a source, sink or ground at the system edge",
                                    claim_ids=e.claim_ids)
            continue
        out[key] = RoleDecision("component", "no evidence it is anything else",
                                default=True, claim_ids=e.claim_ids)
    return out


def find_host(
    instrument: Entity,
    entities: dict[str, Entity],
    part_keys: Iterable[str],
    known: dict[str, str],
) -> tuple[str | None, str]:
    """The part an instrument reads, and how we know. Strongest evidence first.

    1. its own `location` / `host` / `mounted on` fact names a part;
    2. a part's own row names the instrument -- 'TK-101 | ... | Signal / Sensor: LT-101';
    3. ISA loop numbering: LT-101 on the one part numbered 101. Weakest, and said so.
    """
    parts = {k: entities[k] for k in part_keys if k in entities and k != instrument.key}
    tag = norm(instrument.subject)

    for pred in ("location", "host", "mountedon", "installedon", "measures", "hostedby"):
        text = instrument.text(pred)
        if not text:
            continue
        hit = known.get(norm(text)) or next(
            (p.subject for p in parts.values() if norm(p.subject) in norm(text)), None
        )
        if hit:
            return hit, f"its own '{pred}' names {hit}"

    for p in parts.values():
        for pkey, c in p.facts.items():
            if not isinstance(c.value, str) or pkey in ("name", "comments", "notes"):
                continue
            tokens = {norm(t) for t in re.split(r"[\s,;/]+", c.value) if t}
            if tag in tokens:
                return p.subject, f"{p.subject}'s own record lists it under '{c.predicate}'"

    m = re.search(r"(\d{2,4})\s*$", instrument.subject)
    if m:
        same = [p for p in parts.values()
                if re.search(rf"(?<!\d){m.group(1)}\s*$", p.subject)
                and not _ISA_TAG.match(p.subject.strip())
                and not _has(_INSTRUMENT_WORDS + _OPERATOR_WORDS, _text(p))]
        if len(same) == 1:
            return same[0].subject, (f"ISA loop numbering: {same[0].subject} is the only "
                                     f"part numbered {m.group(1)}")
    return None, ""
