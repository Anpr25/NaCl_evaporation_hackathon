"""Resolved facts regrouped per subject, plus the small vocabularies the assembler reads them with.

After precedence has picked one winning claim per (subject, predicate), the assembler needs the
opposite view: *everything we believe about B5*. An `Entity` is that view. It never holds a
losing claim, so nothing downstream can accidentally build on a superseded value.

The vocabularies here are domain-general on purpose: equipment words, measurement words and SI
conversions that hold for a process plant, a drivetrain or a circuit alike. None of them names a
tag, a medium or a value from any particular packet.

Owner: B.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

from ..extract.claims import HEADER_SYNONYMS, normalise_header
from ..ir.evidence import EvidenceClaim


def norm(s: Any) -> str:
    """Case-, space- and punctuation-insensitive key: 'LIS-301' == 'lis_301' == 'LIS 301'."""
    return "".join(ch for ch in str(s).lower() if ch.isalnum())


def ident(raw: str) -> str:
    """A safe identifier that stays recognisable: 'Step10/11' -> 'Step10_11', 'M-301' -> 'M_301'."""
    out = re.sub(r"_+", "_", re.sub(r"[^A-Za-z0-9_]", "_", str(raw).strip())).strip("_")
    return out if out and not out[0].isdigit() else f"e_{out}"


def predicate_key(predicate: str) -> str:
    """Canonical grouping key for a predicate.

    A header like 'Guard/transition' reaches us as the slug 'guard_transition'. When every word
    of such a slug maps to the *same* canonical predicate it is that predicate, so two tables
    describing the same sequence with different header wording still compete for one fact.
    Ambiguous slugs ('from_port': from + port) keep their own name.
    """
    key = norm(predicate)
    if key in {norm(k) for k in HEADER_SYNONYMS}:
        return key
    parts = [p for p in re.split(r"[_/\s]+", str(predicate).lower()) if p]
    if len(parts) > 1:
        canon = {normalise_header(p) for p in parts}
        if len(canon) == 1 and None not in canon:
            return norm(canon.pop())
    return key


# --------------------------------------------------------------------------------- tags

#: An engineering tag: letters then digits, optionally hyphenated, and optionally with one or
#: two alphabetic qualifier segments in between. B5, K1, V20, LIS-301, PIS-1001, SRC-OA-201.
#:
#: The qualifier segments matter more than they look. A process packet tags by discipline and
#: number (LIS-301); an HVAC or building packet tags by function, service and number
#: (SRC-OA-201, GAIN-NORM-201), and the two-segment form was rejected outright -- so every
#: component in such a packet failed `looks_like_tag`, never became a part, and was re-invented
#: downstream as a `physical_only` boundary. That is the whole of why the IAQ packet emitted a
#: Modelica model with no components in it.
TAG_RE = re.compile(
    r"(?<![A-Za-z0-9_])([A-Z]{1,5}(?:[-_][A-Z]{1,5}){0,2})[-_]?(\d{1,4}[A-Z]?)(?![A-Za-z0-9_])"
)

#: A part identifier that carries no number at all: `CORE-L`, `ExcitingCoil`, `MagneticGround`.
#: Whole families of packets name components this way -- a magnetic circuit has a left leg and
#: an upper yoke, not a V-101 -- and a numbering convention is not a precondition for being a
#: component. Deliberately strict about *shape* (one compact token, no spaces, no sentence
#: punctuation) because the caller decides whether the fact-shape says "part"; this only rules
#: out prose, values and free text masquerading as an identifier.
PART_ID_RE = re.compile(r"[A-Za-z][A-Za-z0-9]{0,23}(?:[-_.][A-Za-z0-9]{1,24}){0,3}")

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def looks_like_tag(s: str) -> bool:
    return bool(TAG_RE.fullmatch(str(s).strip()))


def looks_like_part_id(s: str) -> bool:
    """Could this string be the identifier of a component, as opposed to prose or a value?

    Broader than `looks_like_tag` on purpose, and used only where the *shape of the facts*
    already says "this subject is a part" -- a row in a component schedule, or a name that
    another record uses as a connection endpoint. Shape alone never promotes anything here.
    """
    t = str(s).strip()
    if not (2 <= len(t) <= 48) or not PART_ID_RE.fullmatch(t):
        return False
    # A bare number, a time of day or a date is an index or a schedule row, never a part.
    return not re.fullmatch(r"[\d.:\-/]+", t)


def humanise(name: str) -> str:
    """'ExcitingCoil' -> 'Exciting Coil'; 'SRC-OA-201' -> 'SRC OA 201'.

    Retrieval and domain inference both work on words. An identifier written as one CamelCase
    token hides every word in it from a lexical index, so `ExcitingCoil` matched nothing in a
    catalog that holds `ElectroMagneticConverter` under the words "exciting" and "coil".
    """
    return re.sub(r"\s+", " ", _CAMEL.sub(" ", str(name or "").replace("-", " ").replace("_", " "))).strip()


def find_tags(text: str, known: dict[str, str]) -> list[str]:
    """Known ids mentioned in `text`, in order of first appearance. `known` maps norm -> id."""
    out: list[str] = []
    for m in TAG_RE.finditer(str(text or "")):
        hit = known.get(norm(m.group(0)))
        if hit and hit not in out:
            out.append(hit)
    return out


# --------------------------------------------------------------------------------- units

_UNIT_ALIAS = {
    "m^2": "m2", "m²": "m2", "sqm": "m2", "m^3": "m3", "m³": "m3",
    "°c": "degC", "degc": "degC", "deg c": "degC", "celsius": "degC", "°f": "degF", "degf": "degF",
    "bar(g)": "bar", "barg": "bar", "bar(a)": "bar", "bara": "bar",
    "sec": "s", "secs": "s", "second": "s", "seconds": "s",
}
#: unit -> (SI unit, scale, offset). value_SI = value * scale + offset.
_TO_SI: dict[str, tuple[str, float, float]] = {
    "degC": ("K", 1.0, 273.15),
    "degF": ("K", 5.0 / 9.0, 255.3722222222222),
    "bar": ("Pa", 1e5, 0.0), "mbar": ("Pa", 100.0, 0.0), "kPa": ("Pa", 1e3, 0.0),
    "MPa": ("Pa", 1e6, 0.0), "psi": ("Pa", 6894.757, 0.0),
    "kW": ("W", 1e3, 0.0), "MW": ("W", 1e6, 0.0), "mW": ("W", 1e-3, 0.0),
    "mm": ("m", 1e-3, 0.0), "cm": ("m", 1e-2, 0.0), "km": ("m", 1e3, 0.0),
    "L": ("m3", 1e-3, 0.0), "l": ("m3", 1e-3, 0.0), "mL": ("m3", 1e-6, 0.0),
    "min": ("s", 60.0, 0.0), "h": ("s", 3600.0, 0.0), "ms": ("s", 1e-3, 0.0),
    "kg/h": ("kg/s", 1 / 3600.0, 0.0), "g/s": ("kg/s", 1e-3, 0.0),
    "rpm": ("rad/s", 2 * math.pi / 60.0, 0.0),
    "mA": ("A", 1e-3, 0.0), "kV": ("V", 1e3, 0.0), "mV": ("V", 1e-3, 0.0),
    "kN": ("N", 1e3, 0.0), "kNm": ("N.m", 1e3, 0.0), "Nm": ("N.m", 1.0, 0.0),
    "kJ": ("J", 1e3, 0.0), "Wh": ("J", 3600.0, 0.0), "kWh": ("J", 3.6e6, 0.0),
    "uF": ("F", 1e-6, 0.0), "mF": ("F", 1e-3, 0.0), "mH": ("H", 1e-3, 0.0),
}


def clean_unit(unit: str | None) -> str | None:
    if unit is None:
        return None
    u = str(unit).strip()
    if not u:
        return None
    return _UNIT_ALIAS.get(u.lower(), u)


def to_si(value: Any, unit: str | None, *, temperature: bool = False) -> tuple[Any, str | None, str | None]:
    """Convert a number to SI. Returns (value, unit, note); note is None when nothing changed.

    A bare 'C' is a coulomb unless the caller says the quantity is a temperature -- a register
    that writes '25 C' next to a cooling setpoint means Celsius, a battery sheet does not.
    """
    u = clean_unit(unit)
    if u == "C" and temperature:
        u = "degC"
    if not isinstance(value, (int, float)) or isinstance(value, bool) or u not in _TO_SI:
        return value, u, None
    si, scale, offset = _TO_SI[u]
    out = round(value * scale + offset, 10)
    if isinstance(out, float) and out.is_integer() and scale >= 1 and offset == 0:
        out = int(out)
    return out, si, f"{value} {unit} -> {out} {si}"


def is_temperature_unit(unit: str | None) -> bool:
    return clean_unit(unit) in ("degC", "degF", "K")


# --------------------------------------------------------------------------------- vocabulary

#: Words that put a part in a physical domain. Deliberately short and unambiguous; a miss
#: leaves the domain 'unknown' (and the validator says so), a wrong hit would mislead binding.
DOMAIN_WORDS: dict[str, tuple[str, ...]] = {
    "fluid": ("tank", "vessel", "reservoir", "pump", "valve", "pipe", "condenser", "evaporator",
              "liquid", "water", "brine", "condensate", "vapor", "vapour", "steam", "fluid",
              "concentrate", "gas", "oil", "coolant", "duct", "compressor", "batch", "drum",
              # A ventilation packet is a fluid packet, but none of its words were here: its
              # parts are rooms, zones, ducts and supply/exhaust boundaries, so every one of
              # them inferred 'unknown' and was disqualified from being a part at all.
              "air", "room", "zone", "plenum", "fan", "damper", "ventilation", "exhaust",
              "supply", "trace substance", "co2", "humidity", "moist"),
    "thermal": ("heater", "heating", "cooler", "cooling", "condenser", "evaporator", "heat",
                "thermal", "boiler", "chiller", "furnace"),
    "electrical": ("resistor", "capacitor", "inductor", "battery", "voltage", "current", "motor",
                   "generator", "transformer", "breaker", "cable", "electrical", "coil",
                   "winding", "phasor", "ampere", "electric"),
    "magnetic": ("magnetic", "flux", "reluctance", "magnet", "yoke", "core", "air gap",
                 "airgap", "leakage", "mmf", "permeability", "pole", "phi", "magnetomotive",
                 "reluctance"),
    "rotational": ("shaft", "gear", "gearbox", "flywheel", "inertia", "torque", "agitator",
                   "clutch", "bearing", "rotor"),
    "translational": ("spring", "piston", "slider", "linear actuator", "mass-spring"),
    "signal": ("sensor", "measured", "command", "signal", "boolean", "transmitter", "setpoint",
               "controller", "gain", "schedule", "pid", "feedback", "limiter"),
}

#: Parts that sit *in series on a path* rather than being a node of their own: all of them
#: must pass flow (or current, or torque) for the path to conduct.
SERIES_WORDS = ("valve", "pump", "breaker", "switch", "contactor", "fuse", "clutch", "isolator")

#: Measurement word -> the conventional variable name in a lumped model of the measured part.
MEASUREMENT_VARS: tuple[tuple[str, str], ...] = (
    ("level", "level"), ("temperature", "T"), ("pressure", "p"), ("flow", "m_flow"),
    ("concentration", "w"), ("mass fraction", "w"), ("composition", "w"), ("voltage", "v"),
    ("current", "i"), ("speed", "w"), ("angle", "phi"), ("torque", "tau"), ("position", "s"),
    ("force", "f"), ("charge", "q"), ("energy", "E"),
)

MANUAL_WORDS = ("manual", "operator", "local", "hand")
PHYSICAL_ONLY_WORDS = ("physical-only", "physical only", "architecture only", "not simulated")
SIGNAL_MEDIUM_WORDS = ("measured", "command", "signal", "boolean", "real", "bundle")


def infer_domains(*texts: str | None) -> list[str]:
    """Physical domains any of these texts put a part in.

    CamelCase is split first. `ExcitingCoil` and `MagneticGround` carry their domain in words a
    word-boundary search cannot see while they are glued together, so a packet that names its
    components that way inferred 'unknown' for all of them -- and an unknown domain is what
    disqualified them from being parts.
    """
    blob = " ".join(humanise(t).lower() for t in texts if t)
    hits = [d for d, words in DOMAIN_WORDS.items() if any(re.search(rf"\b{re.escape(w)}", blob) for w in words)]
    return hits or ["unknown"]


def measurement_var(measurement: str) -> str | None:
    low = (measurement or "").lower()
    return next((var for word, var in MEASUREMENT_VARS if word in low), None)


def singular(word: str) -> str:
    w = (word or "").strip()
    if w.lower().endswith("ies"):
        return w[:-3] + "y"
    if w.lower().endswith("s") and not w.lower().endswith("ss"):
        return w[:-1]
    return w


# --------------------------------------------------------------------------------- entities


@dataclass
class Entity:
    """Everything that survived precedence about one subject."""

    key: str
    subject: str
    facts: dict[str, EvidenceClaim] = field(default_factory=dict)

    def get(self, *preds: str) -> EvidenceClaim | None:
        for p in preds:
            if (c := self.facts.get(norm(p))) is not None:
                return c
        return None

    def text(self, *preds: str) -> str:
        c = self.get(*preds)
        return "" if c is None or c.value is None else str(c.value).strip()

    def find(self, token: str) -> EvidenceClaim | None:
        """First fact whose predicate contains `token` -- for vocabularies we do not control."""
        t = norm(token)
        return next((c for k, c in self.facts.items() if t in k), None)

    def has(self, *preds: str) -> bool:
        return self.get(*preds) is not None

    @property
    def claim_ids(self) -> list[str]:
        return [c.id for c in self.facts.values()]

    @property
    def registered(self) -> bool:
        """True when at least one fact comes from a structured, deterministic source."""
        return any(c.extracted_by == "t0_deterministic" for c in self.facts.values())

    @property
    def sheet(self) -> str | None:
        """The table (sheet or section) most of this entity's row lives in, if any."""
        names = [c.locator.sheet or c.locator.section for c in self.facts.values()
                 if c.locator.cell and (c.locator.sheet or c.locator.section)]
        return max(set(names), key=names.count) if names else None

    def order(self) -> tuple[str, str, int]:
        """(source, table, row) of the entity's table row -- the author's own ordering."""
        best: tuple[str, str, int] | None = None
        for c in self.facts.values():
            if not c.locator.cell:
                continue
            row = int(re.sub(r"\D", "", c.locator.cell) or 0)
            key = (c.source_id, c.locator.sheet or c.locator.section or "", row)
            best = key if best is None or key < best else best
        return best or ("~", "", 0)


def build_entities(winners: dict[tuple[str, str], EvidenceClaim]) -> dict[str, Entity]:
    """Regroup resolved facts by subject."""
    out: dict[str, Entity] = {}
    subjects: dict[str, list[str]] = defaultdict(list)
    for (skey, pkey), claim in winners.items():
        ent = out.setdefault(skey, Entity(key=skey, subject=str(claim.subject).strip()))
        ent.facts[pkey] = claim
        subjects[skey].append(str(claim.subject).strip())
    for skey, names in subjects.items():
        # Display the spelling the deterministic sources use most, e.g. 'LIS-301' not 'lis 301'.
        out[skey].subject = max(set(names), key=names.count)
    return out


def claims_text(claims: Iterable[EvidenceClaim]) -> Iterable[tuple[EvidenceClaim, str]]:
    """Every claim that carries prose we can pattern-match, with that prose."""
    for c in claims:
        if isinstance(c.value, str) and c.value.strip():
            yield c, c.value
        elif c.quote:
            yield c, c.quote
