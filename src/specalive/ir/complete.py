"""Fill in what the evidence does not say -- out loud.

Some numbers a simulation needs are simply not in the documents. The NaCl packet is a good
example: fifteen files say B1 is "initially charged with water" and B2 with "concentrated
brine", the register gives their area, height, maximum level and composition, and the legacy
Modelica declares them with no starting level at all. Nowhere does anyone say *how much*
liquid is in them.

There are three things you can do about that, and only one of them is honest:

  1. Guess silently. The run goes green and the report is a lie. (Our own hand-built
     reference IR did exactly this -- level_start=0.45 with no note -- which is why it scored
     11/12 while the extracted IR scored 0/10. The difference was mostly the undeclared
     guess, not extraction quality.)
  2. Refuse. The model runs with empty tanks and nothing happens, which is physically
     correct and completely useless to look at.
  3. Assume, mark the assumption in the generated source, and declare it as a gap so it
     reaches the report. That is what an engineer does: assume, write it down, and ask.

This module does (3). Every value it invents is visible in three places -- an `ASSUMPTION`
comment in the Modelica, a Gap in the IR, and a row in the report.

Owner: D.
"""

from __future__ import annotations

import re
from typing import Any

from .evidence import Gap
from .system import SystemModel

#: A charging vessel described as "initially charged" and not yet drawn from is assumed to
#: sit at this fraction of its stated maximum. Arbitrary but bounded, and stated everywhere
#: it is used, so a reviewer can disagree with one number rather than hunt for it.
STARTING_FILL_FRACTION = 0.8

#: Modelica convention: an initial condition is `<quantity>_start`. We only fill one when the
#: class also declares a *bound* for the same quantity, because without a bound there is
#: nothing to scale from and a bare guess would be unfounded. That rule also, usefully,
#: selects only the inventory parameter: `level_start` has `levelMax`, whereas `w_start` and
#: `T_start` have no matching bound and are therefore left alone.
_START_PARAM = re.compile(r"^(?P<base>\w+?)_start$")
_BOUND_CANDIDATES = ("{base}Max", "{base}_max", "max_{base}", "{base}Nominal", "height")


def _words(name: str) -> tuple[str, ...]:
    """Split an identifier into comparable words: 'max_level' and 'levelMax' both -> (level, max)."""
    parts = re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])", name.replace("_", " "))
    return tuple(sorted(p.lower() for p in parts if p))


def match_parameter(wanted: str, available: set[str]) -> str | None:
    """Find `wanted` among `available`, tolerating case and word order.

    Registers write "Max Level (m)"; Modelica classes write `levelMax`. Without this the
    extracted bound never reaches the model, and any assumption scaled from it is impossible.
    """
    if wanted in available:
        return wanted
    target = _words(wanted)
    for candidate in available:
        if _words(candidate) == target:
            return candidate
    return None



#: "Initial w_NaCl = 0.250" -- a stated fact that happens to live in a register's Comments
#: cell rather than its own column. Recovering it is not an assumption: the number is in the
#: evidence and we cite where. Matches `initial <base>... = <number>` for a `<base>_start`
#: parameter, so `w_start` finds "Initial w_NaCl", and a description with no such phrase
#: simply yields nothing.
def _stated_initial(base: str, text: str) -> float | None:
    pattern = (
        r"initial[^=\n]{0,40}"
        + re.escape(base)
        + r"[A-Za-z_]*[^=\n]{0,12}=\s*([-+]?[0-9]*[.]?[0-9]+)"
    )
    m = re.search(pattern, text or "", re.I)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def recover_stated_initial_values(model: SystemModel, index: Any | None) -> list[Gap]:
    """Pull initial conditions the evidence *does* state out of a block's own description.

    A register puts area and max level in their own columns and then writes "Initial
    w_NaCl = 0.250" in Comments. The column values reach the model; the comment did not, so
    B2 started as pure water and the recipe concentration was unreachable. This is fact
    recovery rather than assumption, so it is recorded as info with the text it came from.
    """
    if index is None:
        return []
    notes: list[Gap] = []
    for block in model.simulatable_blocks():
        entry = index.get(block.modelica_class or "")
        if entry is None or not block.description:
            continue
        for name in sorted(p.name for p in entry.params):
            m = _START_PARAM.match(name)
            if not m or name in block.modelica_modifiers:
                continue
            value = _stated_initial(m.group("base"), block.description)
            if value is None:
                continue
            block.modelica_modifiers[name] = repr(value)
            notes.append(
                Gap(
                    id=f"GAP-STATED-{len(notes) + 1:02d}",
                    kind="unextracted",
                    subject=f"{block.id}.{name}",
                    detail=(
                        f"{name} = {value} was stated in prose inside the register's comment "
                        f"for {block.id}, not in a column of its own, so column-based "
                        f"extraction missed it. Recovered from: "
                        f'"{block.description[:110]}"'
                    ),
                    severity="info",
                    workaround="Evidence-backed; no assumption involved.",
                )
            )
    return notes


#: Words that mark a vessel as holding stock at the start of the run. Deliberately read from
#: the *evidence* rather than inferred from the graph: B1 is fed by the condensate return, so
#: structurally it is not a source, yet the register calls it an "Initial pure-water charge"
#: vessel and the runbook says to confirm it is full before starting. A purely structural
#: test skipped it and the plant ran dry.
_CHARGED_WORDS = ("initial charge", "initially charged", "initial pure", "initial concentrated",
                  "charging tank", "charging vessel", "initial feed", "initial inventory",
                  "supply tank", "storage tank")


def _is_initially_charged(block: Any) -> bool:
    text = " ".join(str(x or "") for x in (block.name, block.kind, block.description)).lower()
    if any(w in text for w in _CHARGED_WORDS):
        return True
    return bool(re.search(r"initial(ly)?.{0,24}(charge|charged|fill|filled|stock)", text))


def fill_missing_initial_inventory(model: SystemModel, index: Any | None) -> list[Gap]:
    """Give supply vessels a stated starting inventory when the evidence omits one.

    A vessel qualifies when the evidence *describes* it as initially charged, or when nothing
    in the model feeds it at all. The description test is the one that matters: a charging
    tank on a recirculating plant has an inlet from the return line, so it is not a source in
    the graph, but it still has to start full or the first batch never happens.
    """
    if index is None:
        return []

    fed_by_model = {
        c.target.split(".", 1)[0]
        for c in model.connections
        if c.source.split(".", 1)[0] in {b.id for b in model.simulatable_blocks()}
    }

    gaps: list[Gap] = []
    for block in model.simulatable_blocks():
        if not block.modelica_class:
            continue
        if block.id in fed_by_model and not _is_initially_charged(block):
            continue
        entry = index.get(block.modelica_class)
        if entry is None:
            continue
        declared = {p.name for p in entry.params}
        known = dict(block.modelica_modifiers)
        # Anything the IR extracted counts as known even if it is not a modifier yet.
        for prm in block.parameters:
            hit = match_parameter(prm.name, declared)
            if hit and prm.quantity.value is not None:
                known.setdefault(hit, repr(prm.quantity.value))

        for name in sorted(declared):
            m = _START_PARAM.match(name)
            if not m or name in block.modelica_modifiers:
                continue
            base = m.group("base")
            bound_name = next(
                (
                    hit
                    for pattern in _BOUND_CANDIDATES
                    if (hit := match_parameter(pattern.format(base=base), declared))
                ),
                None,
            )
            if bound_name is None or bound_name not in known:
                continue
            try:
                bound = float(known[bound_name])
            except (TypeError, ValueError):
                continue

            value = round(bound * STARTING_FILL_FRACTION, 6)
            block.modelica_modifiers[name] = repr(value)
            block.modelica_modifiers.setdefault("__assumed__", "")
            gaps.append(
                Gap(
                    id=f"GAP-INIT-{len(gaps) + 1:02d}",
                    kind="deviation",
                    subject=f"{block.id}.{name}",
                    detail=(
                        f"The evidence describes {block.id} as an initially charged supply "
                        f"vessel but never states how much it holds -- fifteen documents give "
                        f"its area, height, maximum level and composition, and none gives a "
                        f"quantity. With no starting inventory it can supply nothing and the "
                        f"sequence stalls at the first transfer. Assumed "
                        f"{name} = {value} ({STARTING_FILL_FRACTION:.0%} of the stated "
                        f"{bound_name} = {bound:g}) so the batch can run."
                    ),
                    severity="warn",
                    workaround=(
                        "Ask the customer for the initial charge. Until then the value is "
                        "marked ASSUMPTION in the generated Modelica and is not evidence-backed."
                    ),
                )
            )
    return gaps
