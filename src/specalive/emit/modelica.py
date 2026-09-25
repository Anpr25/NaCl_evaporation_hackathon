"""SystemModel IR -> executable Modelica, via the L0/L1/L2 binding cascade.

Binding happens first and separately from text generation, so that by the time a single line of
Modelica is written every block already points at a class whose existence and parameter list
were verified against the harvested catalog. Emission itself is then a deterministic template
walk that cannot invent an API.

  L0  bind to a harvested catalog class          (zero compile risk)
  L1  bind to a SpecAlive.* template             (low risk, covers process/lumped gaps)
  L2  ask a model for equations inside a fixed   (guarded by the repair loop)
      port skeleton

The reference output this must reproduce for the NaCl fixture lives at
benchmarks/nacl_evaporation/reference/GeneratedPlant.mo -- diff against it in tests.

Owner: C.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..catalog.retrieve import PICK_PROMPT, PICK_SCHEMA, CatalogIndex
from ..ir.assumptions import AssumptionLog
from ..ir.complete import (
    bind_sensors_to_resolved_setpoints,
    fill_missing_initial_inventory,
    find_setpoint_for_input,
    match_parameter,
    recover_stated_initial_values,
)
from ..ir.evidence import Gap
from ..ir.system import Block, StateMachine, SystemModel

IND = "  "

#: The input members each SpecAlive causal connector expects an upstream part to supply, and
#: the idealized value used when the part that should supply them is `physical_only` -- the
#: same defaults `SpecAlive.Sources.FixedSupply`/`Drain` use, folded in-line at the connector
#: instead of a separate instance. SpecAlive's connector vocabulary is closed and small (four
#: classes, all declared in modelica/SpecAlive.mo), so naming them here is exhaustive, not a
#: per-packet special case.
_BOUNDARY_DEFAULTS: dict[str, dict[str, str]] = {
    "SpecAlive.Interfaces.Suction": {"w": "0.0", "T": "293.15", "avail": "1.0"},
    "SpecAlive.Interfaces.Inlet": {"m_flow": "0.0", "w": "0.0", "T": "293.15"},
}


# --------------------------------------------------------------------------------- binding

#: Fallback templates when nothing in the catalog fits. Domain-keyed, not application-keyed,
#: so a new packet in a covered domain gets an L1 binding without any new code.
L1_TEMPLATES: dict[str, dict[str, Any]] = {
    "fluid.vessel": {
        "class": "SpecAlive.Vessels.Reservoir",
        "keywords": ["tank", "vessel", "reservoir", "drum", "sump", "buffer", "basin", "accumulator"],
        "params": ["area", "levelMax", "level_start", "w_start", "T_start", "nIn", "nOut"],
    },
    "fluid.vessel.heated": {
        "class": "SpecAlive.Vessels.Evaporator",
        "keywords": ["evaporator", "boiler", "reboiler", "still", "vaporiser", "vaporizer"],
        "params": ["area", "Q_heater", "eta_heat", "T_boil0", "k_bpe", "nIn", "nOut"],
    },
    "fluid.vessel.cooled": {
        "class": "SpecAlive.Vessels.CooledVessel",
        "keywords": ["cooler", "cooling tank", "chiller", "quench", "condensate cooler"],
        "params": ["area", "Q_cool", "T_floor", "nIn", "nOut"],
    },
    "fluid.transport": {
        "class": "SpecAlive.Transport.Path",
        "keywords": ["valve", "pipe", "line", "duct", "header", "transfer"],
        "params": ["m_flow_nominal", "dz", "dT_loss"],
    },
    "fluid.pump": {
        "class": "SpecAlive.Transport.Pump",
        "keywords": ["pump", "compressor", "blower", "fan"],
        "params": ["m_flow_nominal", "dp_nominal"],
    },
    "fluid.condenser": {
        "class": "SpecAlive.Transport.Condenser",
        "keywords": ["condenser", "cooler exchanger", "heat exchanger", "reflux"],
        "params": ["T_out", "h_vap"],
    },
    "fluid.junction": {
        "class": "SpecAlive.Transport.Junction",
        "keywords": ["junction", "manifold", "tee", "header", "node"],
        "params": ["nIn", "V"],
    },
    "fluid.source": {
        "class": "SpecAlive.Sources.FixedSupply",
        "keywords": ["boundary source", "ideal source", "fixed supply", "feed source", "makeup"],
        "params": ["w", "T"],
    },
    "fluid.sink": {
        "class": "SpecAlive.Sources.Drain",
        "keywords": ["boundary sink", "ideal sink", "drain", "vent", "overflow"],
        "params": ["nIn"],
    },
}

L2_SKELETON = """\
model {name} "{comment}"
  // L2 synthesis: ports, parameters and units are fixed by SpecAlive; only the equation
  // section below was model-authored. Review before trusting.
{ports}
{params}
{variables}
equation
{equations}
end {name};
"""

L2_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["variables", "equations", "explanation"],
    "properties": {
        "variables": {"type": "array", "items": {"type": "object"}},
        "equations": {"type": "array", "items": {"type": "string"}},
        "explanation": {"type": "string"},
    },
}

L2_PROMPT = """\
Write the equations for one Modelica component. The class declaration, its connectors and
its parameters are already written and are NOT yours to change.

{spec}

ALREADY DECLARED -- refer to these, do not redeclare them
{ports}
{params}

Your job is the `equation` section, plus any local variables it needs.

Rules:
- One equation per array entry, no trailing semicolon, plain Modelica.
- The system must be square: exactly one equation per unknown you introduce, plus one for
  each flow variable on a connector.
- Use `der(x)` for rates. Declare any state you differentiate as a variable with a `start`.
- Refer to a connector's members as `<connector>.<member>`.
- Do not invent parameters. If you need a constant that is not declared above, write it as a
  literal in the equation and say so in `explanation`.
- Physics before elegance: conserve mass and energy.
"""

L2_CRITIQUE_PROMPT = """\
Find the fault in this draft Modelica component. Assume there is one.

{spec}

DRAFT
{draft}

Check, in order:
1. Squareness -- is there exactly one equation per unknown? Count them.
2. Every connector's flow variable must appear in exactly one equation.
3. Conservation -- does mass in minus mass out equal the rate of accumulation? Same for energy.
4. Any variable used but never declared, or declared but never used.
5. Units -- are both sides of each equation dimensionally consistent?
6. Division by a quantity that can be zero at t=0.

List only faults that would make the model wrong or fail to compile. `must_fix` should be
empty if the draft is sound -- do not invent work.
"""

L2_REVISE_PROMPT = """\
Your draft was reviewed and these faults were found. Fix exactly these; change nothing else.

{spec}

ALREADY DECLARED
{ports}
{params}

YOUR DRAFT
{draft}

FAULTS TO FIX
{faults}

Return the corrected component in the same shape as before.
"""

L2_CRITIQUE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["must_fix"],
    "properties": {
        "must_fix": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Faults that would make the model wrong or uncompilable. Empty if sound.",
        },
        "notes": {"type": "string"},
    },
}


def _default_connector(p: Any) -> str:
    """Fallback connector for an L2 port whose IR never named a real one.

    Only sound for a scalar causal signal: `direction` picks which end of
    `Modelica.Blocks.Interfaces` it is. A physical domain (fluid, thermal, ...) needs its own
    two-way connector, which L2 cannot invent safely -- that case is expected to have been
    caught earlier, by an L1 template (`fluid.source`/`fluid.sink`, etc.).
    """
    return "Modelica.Blocks.Interfaces.RealOutput" if p.direction == "out" else "Modelica.Blocks.Interfaces.RealInput"


def _l2_variable(v: dict[str, Any]) -> str:
    start = f"(start = {v['start']})" if v.get("start") is not None else ""
    desc = str(v.get("description", ""))[:60].replace('"', "'")
    return f'  Real {v["name"]}{start} "{desc}";'


_L2_IDENT = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")
#: Modelica operators/functions an equation may call without declaring them as variables.
_L2_BUILTINS = {
    "der", "abs", "sqrt", "exp", "log", "log10", "sin", "cos", "tan", "asin", "acos", "atan",
    "atan2", "sinh", "cosh", "tanh", "min", "max", "sign", "mod", "rem", "div", "floor", "ceil",
    "noEvent", "smooth", "pre", "edge", "change", "reinit", "time", "if", "then", "else",
    "elseif", "and", "or", "not", "true", "false", "sum", "product", "size", "ones", "zeros",
}


def _undeclared_l2_names(equations: list[str], declared: set[str]) -> list[str]:
    """Names an equation uses that are neither a declared variable/port/parameter nor a builtin.

    Catches the failure mode a schema check cannot: the draft is syntactically fine JSON, each
    entry has an `=`, but one side names a variable the draft itself never declared -- `omc`
    would reject it as an undeclared identifier, and that costs a full compile-repair cycle to
    rediscover. Only the root before a `.` is checked, so `port_in.m_flow` is judged on
    `port_in`, never on the connector's own member names.
    """
    used: set[str] = set()
    for eq in equations:
        for m in _L2_IDENT.finditer(eq):
            used.add(m.group(0).split(".", 1)[0])
    return sorted(n for n in used if n not in declared and n not in _L2_BUILTINS and not n[0].isdigit())


def _usable_l2_variables(draft: dict[str, Any], port_names: set[str]) -> list[dict[str, Any]]:
    """Drop anything the model redeclared under a name the skeleton already owns.

    The prompt tells it not to redeclare a port or parameter, but a draft that does it anyway
    would otherwise produce two declarations of the same identifier -- a compile error the
    repair loop then has to spend an iteration rediscovering.
    """
    return [
        v for v in (draft.get("variables") or [])
        if isinstance(v, dict) and v.get("name") and v["name"] not in port_names
    ]


def _render_l2_body(draft: dict[str, Any], port_names: set[str] = frozenset()) -> str:
    """The draft as the critic sees it: variables and equations, nothing else."""
    lines = [_l2_variable(v) for v in _usable_l2_variables(draft, port_names)]
    lines.append("equation")
    lines += [f"  {e.rstrip(';')};" for e in (draft.get("equations") or [])]
    return "\n".join(lines)


@dataclass
class BindingResult:
    tier: str
    modelica_class: str | None
    modifiers: dict[str, str]
    rationale: str
    synthesised: str | None = None


class Binder:
    """Decides, per block, the cheapest tier that can realise it."""

    def __init__(self, index: CatalogIndex | None, router: Any | None = None) -> None:
        self.index = index
        self.router = router

    def bind(self, block: Block) -> BindingResult:
        for attempt in (self._try_l0, self._try_l1, self._try_l2):
            result = attempt(block)
            if result is not None:
                return result
        return BindingResult("unbound", None, {}, "no catalog entry, no template, no synthesis")

    # ------------------------------------------------------------------ L0
    def _try_l0(self, block: Block) -> BindingResult | None:
        if self.index is None:
            return None
        domain = next((d for d in block.domains if d != "unknown"), None)
        query = f"{block.name} {block.kind} {block.description or ''}"
        hits = self.index.search(query, k=12, domain=domain)
        # Modelica.Fluid's own connectors (pressure/enthalpy stream ports, array-sized with a
        # PortsData record per port) are a different convention from the causal
        # SpecAlive.Interfaces ports every other fluid-domain part in this plant binds to
        # (SpecAlive.Transport.*, SpecAlive.Sources.*). resolve_ports's array/count-modifier
        # logic is built for the latter; against the former it produced `connect(TK.ports,
        # ...)` to a nPorts=0 array and a fluid discharge wired to a thermal heatPort. A vessel
        # a hand-built SpecAlive template already covers should not be offered the mismatched
        # standard-library one at all.
        hits = [h for h in hits if not h.entry.key.startswith("Modelica.Fluid.")]
        if not hits:
            return None

        # A single dominant lexical hit is trusted without spending a token.
        if len(hits) == 1 or (len(hits) > 1 and hits[0].score > 2.5 * max(hits[1].score, 1e-6)):
            chosen = hits[0].entry
            return BindingResult(
                "L0",
                chosen.key,
                self._map_params(block, chosen),
                f"unambiguous catalog match (score {hits[0].score})",
            )
        if self.router is None:
            return None

        prompt = PICK_PROMPT.format(
            name=block.name,
            kind=block.kind,
            description=block.description or "(none)",
            parameters=", ".join(f"{p.name}={p.quantity.value}{p.quantity.unit or ''}" for p in block.parameters),
            ports=", ".join(f"{p.name}:{p.domain}" for p in block.ports),
            shortlist=self.index.render_shortlist(hits),
        )

        offered = {h.entry.key: h for h in hits}

        def validate(data: Any) -> tuple[bool, str]:
            choice = str((data or {}).get("choice", "")).strip()
            if not choice:
                return True, ""  # declining is a legitimate answer; we fall through to L1
            hit = offered.get(choice)
            if hit is None:
                # The model named something it was not shown. Reject rather than escalate on
                # a fabricated class -- this is the check that makes "cannot hallucinate an
                # API" literally true rather than merely likely.
                return False, f"'{choice}' was not in the candidate list"
            valid = {p.name for p in hit.entry.params}
            for src, dst in (data.get("parameter_map") or {}).items():
                if dst not in valid:
                    return False, f"parameter '{dst}' does not exist on {choice}"
            return True, ""

        try:
            resp = self.router.run("catalog_pick", prompt, schema=PICK_SCHEMA, validator=validate)
        except Exception:
            return None
        data = resp.data or {}
        choice = str(data.get("choice", "")).strip()
        if not choice or data.get("confidence", 0) < 0.5:
            return None
        hit = offered.get(choice)
        if hit is None:
            return None
        chosen = hit.entry
        mods = self._map_params(block, chosen, data.get("parameter_map") or {})
        return BindingResult("L0", chosen.key, mods, data.get("reason", "")[:300])

    @staticmethod
    def _map_params(block: Block, entry: Any, explicit: dict[str, str] | None = None) -> dict[str, str]:
        """Only ever emit modifiers that exist on the target class.

        Matching tolerates case and word order, because a register writes "Max Level (m)"
        and the class declares `levelMax`. An exact-match-only rule dropped that bound
        silently, and every assumption scaled from it became impossible to found.
        """
        valid = {p.name for p in entry.params}
        out: dict[str, str] = {}
        for p in block.parameters:
            wanted = (explicit or {}).get(p.name, p.name)
            target = match_parameter(wanted, valid)
            if target and p.quantity.value is not None:
                out[target] = _literal(p.quantity.value)
        return out

    # ------------------------------------------------------------------ L1
    def _try_l1(self, block: Block) -> BindingResult | None:
        text = f"{block.name} {block.kind} {block.description or ''}".lower()
        head = f"{block.name} {block.kind}".lower()
        best: tuple[tuple[bool, int, int], str, dict[str, Any]] | None = None
        for key, tpl in L1_TEMPLATES.items():
            hits = sum(1 for kw in tpl["keywords"] if kw in text)
            if not hits:
                continue  # specificity ranks matching templates; it is not itself a match
            # What the part *is* (name, kind) outranks what its description mentions ('decouples
            # mixing from evaporator availability' is not an evaporator); among those, a more
            # specific template (heated/cooled vessel) must win over the generic one.
            score = (any(kw in head for kw in tpl["keywords"]), key.count("."), hits)
            if best is None or score > best[0]:
                best = (score, key, tpl)
        if best is None:
            return None
        _, key, tpl = best
        allowed = set(tpl["params"])
        mods = {
            p.name: _literal(p.quantity.value)
            for p in block.parameters
            if p.name in allowed and p.quantity.value is not None
        }
        return BindingResult("L1", tpl["class"], mods, f"matched L1 template '{key}'")

    # ------------------------------------------------------------------ L2
    def _try_l2(self, block: Block) -> BindingResult | None:
        """C-AI-3. Author equations only, inside a skeleton whose ports and units we fixed.

        The last resort, reached only when the catalog has nothing (L0) and no template
        matches (L1). Three things keep it safe:

        * **The skeleton is ours.** Ports, their connector types, parameters and the class
          name are written by us from the IR. The model contributes an `equation` section and
          the local variables it needs -- nothing else. Connector balance, naming and units
          are out of its reach by construction.
        * **It criticises its own draft before the compiler sees it.** A second pass is asked
          to find the error in the first, against a fixed checklist. This is cheap next to a
          failed compile, and a model is markedly better at finding a fault in a candidate
          than at avoiding it while generating.
        * **`omc` is still the judge.** If the critique misses something, the repair loop
          catches it, and if that fails the block is declared as a gap. Nothing here can put
          a silently-wrong component into the model.
        """
        if self.router is None:
            return None

        name = f"Synth_{_mid(block.id)}"
        port_names = {_port_name(p.name) for p in block.ports}
        known_names = port_names | {_mid(p.name) for p in block.parameters}
        ports = "\n".join(
            f"  {p.connector_type or _default_connector(p)} {_port_name(p.name)}"
            f' "{p.direction} {p.domain}";'
            for p in block.ports
        )
        params = "\n".join(
            f"  parameter Real {_mid(p.name)} = {p.quantity.value}"
            f'{f" ({p.quantity.unit})" if p.quantity.unit else ""};'
            for p in block.parameters
            if isinstance(p.quantity.value, (int, float))
        )
        spec = (
            f"component: {block.name} ({block.kind})\n"
            f"description: {block.description or '(none)'}\n"
            f"domains: {', '.join(block.domains)}\n"
            f"connectors: {', '.join(f'{_port_name(p.name)} [{p.direction} {p.domain}]' for p in block.ports) or '(none)'}\n"
            f"parameters: {', '.join(_mid(p.name) for p in block.parameters) or '(none)'}"
        )

        draft = self._l2_call(L2_PROMPT.format(spec=spec, ports=ports, params=params), known_names)
        if draft is None:
            return None

        critique = self._l2_critique(spec, draft, port_names)
        if critique and critique.get("must_fix"):
            revised = self._l2_call(
                L2_REVISE_PROMPT.format(
                    spec=spec,
                    ports=ports,
                    params=params,
                    draft=_render_l2_body(draft, port_names),
                    faults="\n".join(f"  - {f}" for f in critique["must_fix"][:6]),
                ),
                known_names,
            )
            draft = revised or draft

        body = L2_SKELETON.format(
            name=name,
            comment=(block.description or block.name).replace('"', "'")[:90],
            ports=ports,
            params=params,
            variables="\n".join(_l2_variable(v) for v in _usable_l2_variables(draft, port_names)),
            equations="\n".join(f"  {e.rstrip(';')};" for e in (draft.get("equations") or [])),
        )
        why = (draft.get("explanation") or "")[:200]
        if critique and critique.get("must_fix"):
            why = f"{why} [self-critique raised {len(critique['must_fix'])}, revised]"
        return BindingResult("L2", name, {}, why or "L2 synthesis", synthesised=body)

    def _l2_call(self, prompt: str, known_names: set[str] = frozenset()) -> dict[str, Any] | None:
        def validate(data: Any) -> tuple[bool, str]:
            eqs = (data or {}).get("equations") or []
            if not eqs:
                return False, "no equations returned"
            for e in eqs:
                if not isinstance(e, str) or "=" not in e:
                    return False, f"not an equation: {str(e)[:60]!r}"
            declared = known_names | {
                v["name"] for v in (data.get("variables") or []) if isinstance(v, dict) and v.get("name")
            }
            missing = _undeclared_l2_names(eqs, declared)
            if missing:
                return False, f"used but never declared: {', '.join(missing[:6])}"
            return True, ""

        try:
            resp = self.router.run("equation_synthesis", prompt, schema=L2_SCHEMA, validator=validate)
        except Exception:
            return None
        return resp.data or None

    def _l2_critique(
        self, spec: str, draft: dict[str, Any], port_names: set[str] = frozenset()
    ) -> dict[str, Any] | None:
        """Ask for the fault in the draft, against a fixed checklist. Never asks 'is this ok?'."""
        try:
            resp = self.router.run(
                "equation_synthesis",
                L2_CRITIQUE_PROMPT.format(spec=spec, draft=_render_l2_body(draft, port_names)),
                schema=L2_CRITIQUE_SCHEMA,
            )
        except Exception:
            return None
        return resp.data or None


def _literal(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    return f'"{v}"'



# --------------------------------------------------------------------------- port resolution

#: Connector type suffixes that mark which end of a component a port is. Acausal domains use
#: an a/b convention with no physical direction; causal ones name the direction outright.
_IN_SIDE = ("inlet", "suction", "_a", "port_a", "flange_a", "positivepin", "pin_p", "plug_p",
            "input", "in")
_OUT_SIDE = ("outlet", "discharge", "_b", "port_b", "flange_b", "negativepin", "pin_n",
             "plug_n", "output", "out")
#: Parameters our templates use to size a connector array.
_COUNT_PARAM = {"inlet": ("nIn", "nPorts", "n"), "outlet": ("nOut", "nPorts", "n")}


#: Connector types that carry a control signal rather than a physical stream. These must be
#: kept out of the physical pools: `Path` declares `open:BooleanInput` before `port_a`, and a
#: substring match on "input" made the first process connection bind to the valve's command,
#: producing `connect(B1.outlet[1], L_V8.open)` -- two incompatible connectors.
_SIGNAL_TYPES = ("booleaninput", "booleanoutput", "realinput", "realoutput",
                 "integerinput", "integeroutput")


def _subscript(name: str) -> int:
    """The [n] on a connector reference, or 0 when it is a scalar."""
    m = re.search(r"\[(\d+)\]", name)
    return int(m.group(1)) if m else 0


def _side_of(name: str, type_name: str) -> str:
    """Which end of the component a connector belongs to: 'in', 'out', 'signal' or 'other'."""
    leaf = type_name.rsplit(".", 1)[-1].lower()
    if leaf in _SIGNAL_TYPES:
        return "signal"
    hay = f"{name} {leaf}"
    for suffix in _OUT_SIDE:
        if suffix in hay:
            return "out"
    for suffix in _IN_SIDE:
        if suffix in hay:
            return "in"
    return "other"


def resolve_ports(model: SystemModel, index: CatalogIndex | None) -> list[str]:
    """Rewrite each block port's `name` to a connector that the bound class really has.

    The IR keeps the document's own word for a port -- 'bottom port' -- because that is what
    the evidence says and the SysML model should show it. Modelica needs the class's actual
    connector, so the two are reconciled here, once, after binding:

      * connectors are grouped into in-side and out-side by name and by connector type;
      * the block's ports are assigned within their own side, in declaration order;
      * where the class sizes a connector array with nIn/nOut, the subscript is written and
        the count modifier is set to match, so the array is never too small.

    Port `id` is untouched: connections reference ids, and SysML keeps reporting the
    document's name. Returns a list of problems for the caller to declare as gaps.
    """
    problems: list[str] = []
    # A port only earns an array slot if something is actually wired to it. The IR lists every
    # port a register mentions, which is right for SysML, but sizing nIn/nOut from that count
    # leaves empty array elements whose inputs nothing defines -- an under-determined model.
    emitted = {b.id for b in model.simulatable_blocks()}
    wired: set[str] = set()
    for conn in model.connections:
        # A connection to a part we do not emit -- a utility header outside the plant
        # boundary, or a valve that was lowered into a series group -- is not a wire in the
        # executable model. Counting it would size an array for a slot nothing ever fills.
        ends = [ref.split(".", 1)[0] for ref in (conn.source, conn.target)]
        if not all(e in emitted for e in ends):
            continue
        wired.update((conn.source, conn.target))

    for block in model.simulatable_blocks():
        if not block.ports or not block.modelica_class:
            continue
        entry = index.get(block.modelica_class) if index else None
        if entry is None or not entry.ports:
            continue

        available: dict[str, list[str]] = {"in": [], "out": [], "signal": [], "other": []}
        for cp in entry.ports:
            available[_side_of(cp.name, cp.type)].append(cp.name)

        params = {prm.name for prm in entry.params}
        used: dict[str, int] = {}
        connected = [p for p in block.ports if f"{block.id}.{p.id}" in wired]
        dangling = [p for p in block.ports if p not in connected]
        for port in dangling:
            # Keep it in the IR (SysML should still show the port the register described)
            # but give it no Modelica *name*, so nothing tries to emit a connection to it.
            # Its connector class is still worth recording: when the neighbour that should
            # have wired it turns out to be architecture-only, the emitter idealizes this
            # dangling end as a boundary, and needs the real type to know which members to
            # set. Approximated by the first connector on the matching side -- SpecAlive's
            # own components never carry more than one per side, so there is no ambiguity
            # in practice.
            side = "signal" if port.domain in ("signal", "control") else (
                "in" if port.direction == "in" else "out" if port.direction == "out" else "other"
            )
            pool = available.get(side) or available.get("other") or []
            if not pool and side != "signal":
                pool = available["in"] + available["out"] + available["other"]
            connector = pool[0] if pool else None
            port.connector_type = next((cp.type for cp in entry.ports if cp.name == connector), None)
        # Resolution must be idempotent. A hand-built or previously-resolved IR already
        # names real connectors, and re-deriving them by direction gets it wrong: an
        # evaporator has two out-side connectors and the first out-port was reassigned from
        # `outlet` to `vapor`, swapping the concentrate and vapour streams. If the name is
        # already a connector this class declares, keep it and just count the slot.
        declared = {cp.name for cp in entry.ports}
        for port in connected:
            base = port.name.split("[")[0]
            if base in declared:
                used[base] = max(used.get(base, 0), _subscript(port.name))
                side_already = _side_of(base, next(c.type for c in entry.ports if c.name == base))
                used[side_already] = used.get(side_already, 0) + 1
                count_param = next((c for c in _COUNT_PARAM.get(base, ()) if c in
                                    {prm.name for prm in entry.params}), None)
                if count_param and _subscript(port.name):
                    block.modelica_modifiers[count_param] = str(used[base])
                continue
            if port.domain in ("signal", "control"):
                side = "signal"
            else:
                side = "in" if port.direction == "in" else "out" if port.direction == "out" else "other"
            pool = available.get(side) or available.get("other") or []
            if not pool and side != "signal":
                # Acausal components (a rotational flange) have no in/out sense at all, so
                # fall back to any PHYSICAL connector. Never fall back to a signal connector:
                # a stream must not be wired into a command input.
                pool = available["in"] + available["out"] + available["other"]
            if not pool:
                problems.append(f"{block.id}.{port.id}: {block.modelica_class} declares no connector")
                continue

            connector = pool[min(used.get(side, 0), len(pool) - 1)] if len(pool) > 1 else pool[0]
            count_params = [c for c in _COUNT_PARAM.get(connector, ()) if c in params]
            if count_params:
                # Subscript counts uses of THIS array, not ports on this side. An evaporator
                # has two out-side connectors, `vapor` and `outlet[]`; counting per side made
                # the first use of `outlet` come out as outlet[2] and sized the array to 2,
                # leaving outlet[1] undefined.
                idx = used.get(connector, 0) + 1
                port.name = f"{connector}[{idx}]"
                block.modelica_modifiers[count_params[0]] = str(idx)
                used[connector] = idx
            else:
                port.name = connector
            used[side] = used.get(side, 0) + 1

        # Any connector array the class declares but which nothing wired to must be sized 0,
        # or its elements are undefined.
        for connector, counts in _COUNT_PARAM.items():
            count_param = next((c for c in counts if c in params), None)
            if count_param and count_param not in block.modelica_modifiers:
                block.modelica_modifiers[count_param] = "0"

        for side in ("in", "out"):
            if used.get(side, 0) > len(available[side]) and not any(
                c in params for c in ("nIn", "nOut", "nPorts", "n")
            ):
                problems.append(
                    f"{block.id}: {used[side]} {side}-ports but {block.modelica_class} declares "
                    f"{len(available[side])} and is not an array"
                )
    return problems


# --------------------------------------------------------------------------------- emission


class ModelicaEmitter:
    def __init__(self, model: SystemModel, package: str = "GeneratedPlant",
                 index: Any | None = None, log: Any | None = None) -> None:
        self.m = model
        self.package = package
        self._index = index
        #: Where inferences made during emission are declared. Emission is the last place
        #: that can still invent a value, so it has to be able to say when it does.
        self._log = log
        self.lines: list[str] = []
        #: Every connector this emitter has already driven, by any route -- a signal
        #: binding, a series-group conjunction, a connect(). The gap pass consults this
        #: instead of trying to enumerate the ways a connector can acquire a value; it
        #: bound seven `L_*.open` a second time because it did not know about series
        #: lowering, and the model came out over-determined by exactly seven.
        self._driven: set[str] = set()

    def _w(self, depth: int, text: str = "") -> None:
        self.lines.append(f"{IND * depth}{text}" if text else "")

    def emit(self) -> str:
        self._w(0, f"package {self.package}")
        self._w(1, f'"Generated by SpecAlive from {len(self.m.sources)} evidence sources."')
        self._w(0)
        self._emit_synthesised()
        for sm in self.m.state_machines:
            self._emit_controller(sm)
        self._emit_plant()
        for sc in self.m.scenarios:
            self._emit_scenario(sc)
        self._w(0, f'  annotation (uses(Modelica(version = "4.0.0"), SpecAlive(version = "0.1.0")));')
        self._w(0, f"end {self.package};")
        return "\n".join(self.lines) + "\n"

    def _emit_synthesised(self) -> None:
        """C-AI-3. L2 components live inside the generated package, ahead of the Plant.

        Kept visibly separate and labelled in the source, because an engineer reviewing this
        file should be able to see at a glance which components came from a verified library
        and which were written by a model.
        """
        synth = [b for b in self.m.blocks if b.binding_tier == "L2" and b.synthesised_equations]
        if not synth:
            return
        self._w(1, "// ---- L2: equations below were model-authored inside a fixed skeleton.")
        self._w(1, "// ---- Ports, parameters and connector balance were not. Review before trusting.")
        for b in synth:
            for line in (b.synthesised_equations or "").splitlines():
                self._w(1, line)
            self._w(0)

    # ------------------------------------------------------------------ controller
    def _emit_controller(self, sm: StateMachine) -> None:
        """Lower any state machine to a sampled algorithmic FSM: one Integer per region.

        Domain-general on purpose. It is exactly how a PLC executes, it has no library
        dependency, it introduces no continuous state, and `pre()` on every region read keeps
        the discrete system acyclic -- which is what omc's alias elimination needs.
        """
        name = _mid(sm.name)
        self._w(1, f"block {name}")
        self._w(2, f'"Sequential controller lowered to a PLC scan model, one state per region."')
        self._w(2, f"parameter Modelica.Units.SI.Time Ts = {sm.scan_period} \"Scan period\";")
        for p in self.m.parameters:
            if p.scope in (None, "global", sm.id) and isinstance(p.quantity.value, (int, float)):
                unit = f' "{p.quantity.unit or ""}"' if p.quantity.unit else ""
                self._w(2, f"parameter Real {_mid(p.id)} = {p.quantity.value}{unit};")
        self._w(0)
        for s in self.m.signals:
            if s.role == "sensor":
                self._w(2, f'input {_mtype(s.datatype)} {_mid(s.name)} "{s.unit or ""}";')
        self._w(0)
        for s in self.m.signals:
            if s.role == "actuator":
                self._w(2, f"output {_mtype(s.datatype)} {_mid(s.name)};")
        self._w(0)

        order = {r: {s.id: i for i, s in enumerate(sm.states_in(r))} for r in sm.regions}
        for region in sm.regions:
            names = ", ".join(f"{i} {s.name}" for s, i in
                              ((s, order[region][s.id]) for s in sm.states_in(region)))
            self._w(2, f'Integer s_{_mid(region)}(start = 0, fixed = true) "{names}";')

        # A declared fallback (SA-05) fires on time spent in a step, so those regions need a
        # clock stamped at every entry. Only emit it where one is used -- an unused discrete
        # variable is noise in a model a judge is going to read.
        dwell_regions = sorted({
            (sm.state(t.source_state).region if sm.state(t.source_state) else "main")
            for t in sm.transitions if t.declared_fallback
        })
        for region in dwell_regions:
            self._w(2, f'discrete Real tEnter_{_mid(region)}(start = 0, fixed = true) '
                       f'"Time the active step in region {region} was entered";')
        self._w(0)

        self._w(1, "algorithm")
        self._w(2, "when sample(0, Ts) then")
        for region in sm.regions:
            self._w(3, f"// ---- region {region}")
            var = f"s_{_mid(region)}"
            first = True
            for st in sm.states_in(region):
                outgoing = [t for t in sm.transitions if t.source_state == st.id]
                if not outgoing:
                    continue
                kw = "if" if first else "elseif"
                first = False
                self._w(3, f"{kw} pre({var}) == {order[region][st.id]} then")
                # Specified transitions first, declared fallbacks last, so a guard the
                # customer wrote always wins when both are true in the same scan.
                for t in sorted(outgoing, key=lambda x: x.declared_fallback):
                    if t.declared_fallback:
                        self._w(4, f"// FALLBACK (SA-05): {t.fallback_for} is unreachable; "
                                   f"the specified guard above is unchanged and still wins")
                    guard = self._guard_to_modelica(t.guard, sm, order)
                    self._w(4, f"if {guard} then")
                    tgt_region = (sm.state(t.target_state) or st).region
                    self._w(5, f"s_{_mid(tgt_region)} := {order[tgt_region][t.target_state]};")
                    if _mid(tgt_region) in [_mid(r) for r in dwell_regions]:
                        self._w(5, f"tEnter_{_mid(tgt_region)} := time;")
                    for fork in t.forks:
                        fs = sm.state(fork)
                        if fs:
                            self._w(5, f"s_{_mid(fs.region)} := {order[fs.region][fork]};")
                            if _mid(fs.region) in [_mid(r) for r in dwell_regions]:
                                self._w(5, f"tEnter_{_mid(fs.region)} := time;")
                    self._w(4, "end if;")
            if not first:
                self._w(3, "end if;")
        self._w(2, "end when;")
        self._w(0)

        self._w(1, "equation")
        for s in self.m.signals:
            if s.role != "actuator":
                continue
            active = [
                (st.region, order[st.region][st.id])
                for st in sm.states
                if s.id in st.actions or s.name in st.actions
            ]
            expr = (
                " or ".join(f"(s_{_mid(r)} == {i})" for r, i in active) if active else "false"
            )
            for il in self.m.interlocks:
                if il.actuator in (s.id, s.name):
                    cond = self._guard_to_modelica(il.condition, sm, order)
                    expr = f"({expr}) and ({cond})" if il.sense == "permissive" else f"({expr}) and not ({cond})"
            self._w(2, f"{_mid(s.name)} = {expr};")
        self._w(1, f"end {name};")
        self._w(0)

    def _guard_to_modelica(self, guard: str, sm: StateMachine, order: dict[str, dict[str, int]]) -> str:
        """Rewrite IR guard syntax into Modelica, including state references used in joins."""
        out = guard.replace("&&", " and ").replace("||", " or ").replace("!", " not ")

        # dwell(<state>) -- seconds spent in the step. Only a declared fallback uses it, and
        # it reads the entry clock through pre() like every other discrete state in the scan,
        # so the discrete system stays acyclic.
        def _dwell(m: re.Match[str]) -> str:
            st = sm.state(m.group(1))
            region = _mid(st.region if st else "main")
            return f"(time - pre(tEnter_{region}))"

        out = re.sub(r"\bdwell\(\s*([A-Za-z_]\w*)\s*\)", _dwell, out)
        for region, states in order.items():
            for sid, idx in states.items():
                out = re.sub(rf"\bin\({sid}\)", f"pre(s_{_mid(region)}) == {idx}", out)
                out = re.sub(rf"\b{re.escape(sid)}\.active\b", f"pre(s_{_mid(region)}) == {idx}", out)
        for s in self.m.signals:
            if s.id != s.name:
                out = re.sub(rf"\b{re.escape(s.id)}\b", _mid(s.name), out)
        return re.sub(r"\s+", " ", out).strip()

    # ------------------------------------------------------------------ plant
    def _unbound_signal_inputs(self) -> list[tuple[str, str, str, Any]]:
        """Component signal inputs that nothing drives: (component, connector).

        A dangling `input` has no equation defining it, so omc reports the whole model as
        under-determined. We would rather emit a stated assumption than a model that cannot
        be built, so these are bound to their inert value and declared.

        Before assuming, though, we look for a number the evidence actually supplies. A
        utility outside the plant boundary is never a *block* that feeds anything, but its
        operating value is usually written down somewhere -- and binding the input to zero
        throws that away. Here it cost us the condenser: `SP-K1-CW = 0.1 kg/s` was extracted
        and then ignored, `K1.cw_flow` went to zero, nothing condensed, and two vessels never
        received the hot charge they were supposed to cool.
        """
        if self._index is None:
            return []
        wired = {r for c in self.m.connections for r in (c.source, c.target)}
        # An actuator signal bound to `B5.heater` drives that connector by equation, not by
        # connect(). Binding it again to 0 produced `B5.heater = 0.0` on a Boolean input.
        # Only actuators count. A *sensor* binding is a read: `FIS_801` reading `K1.cw_flow`
        # does not define it, and treating it as a drive left the connector with no equation
        # at all and the model under-determined.
        driven = {s.binding for s in self.m.signals if s.binding and s.role == "actuator"}
        out: list[tuple[str, str, str, Any]] = []
        for block in self.m.simulatable_blocks():
            entry = self._index.get(block.modelica_class or "")
            if entry is None:
                continue
            bound_here = {p.name for p in block.ports}
            for cp in entry.ports:
                leaf = cp.type.rsplit(".", 1)[-1].lower()
                if not leaf.endswith("input"):
                    continue
                ref = f"{block.id}.{cp.name}"
                if cp.name in bound_here or ref in wired or ref in driven or ref in self._driven:
                    continue
                if leaf.startswith("boolean"):
                    # A Boolean command has no numeric setpoint to find, and a stray match
                    # against one would be a type error dressed up as evidence.
                    out.append((block.id, cp.name, "false", None))
                    continue
                prm = find_setpoint_for_input(self.m, block.id, cp.name)
                if prm is not None:
                    out.append((block.id, cp.name, repr(float(prm.quantity.value)), prm))
                else:
                    out.append((block.id, cp.name, "0.0", None))
        return out

    def _layout(self) -> dict[str, str]:
        """Place components on the diagram canvas so OMEdit renders a block diagram.

        Without `Placement` annotations OMEdit shows an empty diagram and an engineer has to
        read Modelica source to see the topology -- which defeats the point of handing them a
        model to *review*. The layout is derived from the connection graph, not from any
        packet's coordinates, so it works on a domain nobody has seen.

        Components are ranked by longest path from a source (a block nothing feeds), which
        puts flow left-to-right in process order; siblings stack vertically within a rank.
        Crude next to a real graph-drawing library, and enormously better than nothing.
        """
        blocks = [b for b in self.m.simulatable_blocks() if b.modelica_class]
        ids = [b.id for b in blocks]
        if not ids:
            return {}
        known = set(ids)
        succ: dict[str, set[str]] = {i: set() for i in ids}
        indeg: dict[str, int] = {i: 0 for i in ids}
        for c in self.m.connections:
            s, t = c.source.split(".")[0], c.target.split(".")[0]
            if s in known and t in known and t not in succ[s]:
                succ[s].add(t)
                indeg[t] += 1

        # A process plant is not a DAG: this one recycles B6 -> B1 and B7 -> B2, and every
        # ranking scheme collapses on a cycle -- relaxation pushes all ranks up together,
        # Kahn never starts because nothing has indegree zero. So break the cycles first.
        # A DFS back-edge is exactly a recycle line, and dropping it from the *layout* graph
        # (never from the model) leaves the forward process order intact.
        colour: dict[str, int] = {i: 0 for i in ids}  # 0 white, 1 grey, 2 black
        back: set[tuple[str, str]] = set()

        def strip_cycles(root: str) -> None:
            stack: list[tuple[str, list[str]]] = [(root, sorted(succ[root]))]
            colour[root] = 1
            while stack:
                node, pending = stack[-1]
                if not pending:
                    colour[node] = 2
                    stack.pop()
                    continue
                nxt = pending.pop()
                if colour[nxt] == 1:  # points back into the current path: a recycle line
                    back.add((node, nxt))
                elif colour[nxt] == 0:
                    colour[nxt] = 1
                    stack.append((nxt, sorted(succ[nxt])))

        for start in sorted(ids, key=lambda i: (indeg[i], i)):
            if colour[start] == 0:
                strip_cycles(start)

        dag = {s: {t for t in succ[s] if (s, t) not in back} for s in ids}
        deg = {i: 0 for i in ids}
        for s in ids:
            for t in dag[s]:
                deg[t] += 1

        rank: dict[str, int] = {i: 0 for i in ids}
        queue = [i for i in ids if deg[i] == 0]
        while queue:
            s = queue.pop(0)
            for t in sorted(dag[s]):
                rank[t] = max(rank[t], rank[s] + 1)
                deg[t] -= 1
                if deg[t] == 0:
                    queue.append(t)

        columns: dict[int, list[str]] = {}
        for i in ids:
            columns.setdefault(rank[i], []).append(i)

        out: dict[str, str] = {}
        span_x, span_y, w, h = 34, 30, 22, 18
        for col, members in sorted(columns.items()):
            x = -100 + col * span_x
            top = (len(members) - 1) * span_y / 2
            for row, bid in enumerate(members):
                y = top - row * span_y
                out[bid] = (
                    f" annotation (Placement(transformation("
                    f"extent={{{{{x:.0f},{y - h / 2:.0f}}},{{{x + w:.0f},{y + h / 2:.0f}}}}})))"
                )
        # The controller is not in the flow graph; park it above the plant.
        for sm in self.m.state_machines:
            out[sm.id] = (
                " annotation (Placement(transformation(extent={{-20,70},{20,95}})))"
            )
        return out

    @staticmethod
    def _line(src: str, tgt: str, placement: dict[str, str]) -> str:
        """A straight run between two placed components, so OMEdit draws the edge."""
        def centre(bid: str) -> tuple[float, float] | None:
            anno = placement.get(bid)
            if not anno:
                return None
            nums = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", anno)]
            if len(nums) < 4:
                return None
            x1, y1, x2, y2 = nums[-4:]
            return (x1 + x2) / 2, (y1 + y2) / 2

        a, b = centre(src), centre(tgt)
        if a is None or b is None:
            return ""
        return (
            f" annotation (Line(points={{{{{a[0]:.0f},{a[1]:.0f}}},"
            f"{{{b[0]:.0f},{b[1]:.0f}}}}}, color={{0,127,255}}))"
        )

    def _emit_plant(self) -> None:
        self._w(1, f"model Plant \"{self.m.description or self.m.name}\"")
        placement = self._layout()
        # Record what actually gets an instance. The connection loop below MUST use this set
        # and not `simulatable_blocks()`: the two answer different questions, and treating
        # them as interchangeable is what produced `connect(SRC_101.port_out, ...)` against a
        # component the emitter had already skipped, and a model that could not compile.
        declared: set[str] = set()
        for b in self.m.simulatable_blocks():
            if b.binding_tier == "unbound" or not b.modelica_class:
                self._w(2, f"// GAP: block '{b.id}' ({b.kind}) has no binding; see report.")
                continue
            declared.add(b.id)
            assumed = b.modelica_modifiers.pop("__assumed__", None)
            mods = ", ".join(f"{k} = {v}" for k, v in sorted(b.modelica_modifiers.items()))
            if assumed is not None:
                self._w(2, f"// ASSUMPTION: {b.id} starting inventory is not stated in the "
                           f"evidence; see the declared gaps in the report.")
            decl = f"{b.modelica_class} {_mid(b.id)}"
            if mods:
                decl += f"({mods})"
            trace = " ".join(f"@trace {r}" for r in b.provenance.requirement_ids)
            anno = placement.get(b.id, "")
            self._w(2, f'{decl} "{b.description or b.name}{" " + trace if trace else ""}"{anno};')
        for sm in self.m.state_machines:
            anno = placement.get(sm.id, "")
            self._w(2, f"{_mid(sm.name)} {_mid(sm.id)}{anno};")
        self._w(0)
        self._w(1, "equation")
        for c in self.m.connections:
            ends = {c.source.split(".")[0], c.target.split(".")[0]}
            if not ends <= declared:
                # Either endpoint may be missing for two quite different reasons, and the
                # reader deserves to know which: an architecture-only part never had an
                # instance, whereas an unbound one should have had and did not.
                missing = sorted(ends - declared)
                why = ", ".join(
                    f"{m} is unbound" if self.m.block(m) and not self.m.block(m).physical_only
                    else f"{m} is architecture only"
                    for m in missing
                )
                self._w(2, f"// not connected: {c.id} ({c.source} -> {c.target}) -- {why}")
                # A part the evidence never described as equipment is, by the extractor's own
                # classification, "a supply/sink at the system boundary" -- so the surviving
                # neighbour's dangling connector is idealized the same way an explicit
                # FixedSupply/Drain would be, instead of being left short of an equation.
                if len(missing) == 1 and self.m.block(missing[0]).physical_only:
                    survivor = c.target if missing[0] == c.source.split(".")[0] else c.source
                    port = self.m.port(survivor)
                    defaults = _BOUNDARY_DEFAULTS.get(port.connector_type if port else None)
                    if defaults:
                        ref = self._ref(survivor)
                        self._w(2, f"// GAP: {missing[0]} is architecture only; idealizing "
                                   f"{ref} as a boundary (see the declared gaps in the report)")
                        for member, value in defaults.items():
                            self._w(2, f"{ref}.{member} = {value};")
                continue
            note = f"  // @series {', '.join(c.series_elements)}" if c.series_elements else ""
            line = self._line(c.source.split(".")[0], c.target.split(".")[0], placement)
            self._w(2, f"connect({self._ref(c.source)}, {self._ref(c.target)}){line};{note}")
        self._w(0)
        for sm in self.m.state_machines:
            ctrl = _mid(sm.id)
            for s in self.m.signals:
                if not s.binding:
                    continue
                path = ".".join(_mid(part) for part in s.binding.split("."))
                if s.role == "sensor":
                    self._w(2, f"{ctrl}.{_mid(s.name)} = {path};")
                else:
                    self._w(2, f"{path} = {ctrl}.{_mid(s.name)};")
                    self._driven.add(s.binding)
            self._w(0)
            self._emit_series_groups(ctrl)

            # Sensor inputs the IR could not bind to anything in the plant.
            for sig in self.m.signals:
                if sig.role == "sensor" and not sig.binding:
                    self._w(2, f"// {self._declare_inert(sig.id, sig.name, '0.0')}")
                    self._w(2, f"{ctrl}.{_mid(sig.name)} = 0.0;")

        # Component signal inputs nothing drives.
        for comp, connector, value, prm in self._unbound_signal_inputs():
            ref = f"{comp}.{connector}"
            if prm is not None:
                # Evidence-backed, so this is a recovered fact and not an assumption. Cite it.
                unit = f" {prm.quantity.unit}" if prm.quantity.unit else ""
                self._w(2, f"// {ref} driven from {prm.id} = {prm.quantity.value}{unit} "
                           f"({prm.description or 'stated in the evidence'})")
            else:
                self._w(2, f"// {self._declare_inert(ref, connector, value)}")
            self._w(2, f"{_mid(comp)}.{connector} = {value};")
        # A canvas wide enough for the ranked layout, or OMEdit clips the right-hand columns.
        ranks = max(1, len(set(re.findall(r"extent=\{\{(-?\d+)", "".join(placement.values())))))
        self._w(2, "annotation (Diagram(coordinateSystem(preserveAspectRatio = false,")
        self._w(3, f"extent = {{{{-110,-110}},{{{max(110, -100 + ranks * 34 + 40)},110}}}})));")
        self._w(1, "end Plant;")
        self._w(0)

    def _declare_inert(self, subject: str, label: str, value: str) -> str:
        """Bind an undriven input to its inert value, and say so in both places.

        Returns the source comment, and -- when a log is attached -- also files the
        assumption against SA-03 so it reaches the report. The comment alone was not enough:
        a reviewer reading only the report could not tell that eleven inputs had been
        invented, because the .mo is the one artefact nobody reads line by line.
        """
        if self._log is not None:
            self._log.assume(
                subject=subject,
                statement=f"{subject} is bound to {value}, its inert value",
                basis="SA-03-unbound-input-inert",
                what_was_missing=f"anything in the evidence that drives {label}",
                value=value,
            )
        return f"GAP: nothing drives {subject}; assuming {value} (ASM via SA-03)"

    def _ref(self, endpoint: str) -> str:
        """Resolve '<block_id>.<port_id>' to the concrete Modelica connector reference.

        A port's IR id is a stable handle ('out'); its `name` is what the bound Modelica class
        actually calls the connector ('outlet[1]'). Emission must use the name, and array
        subscripts have to survive identifier sanitisation.
        """
        bid, _, pid = endpoint.partition(".")
        blk = self.m.block(bid)
        port = next((p for p in blk.ports if p.id == pid), None) if blk else None
        return f"{_mid(bid)}.{_port_name(port.name) if port else _mid(pid)}"

    def _emit_series_groups(self, ctrl: str) -> None:
        """Lower each series element group to one conjunct command on its transfer path.

        Physically, elements in series must all be open for flow, so the group becomes a
        single AND. SysML keeps every individual element visible; only the executable model
        collapses them, and the @lowering comment records that so the two stay reconcilable.
        """
        by_path: dict[str, list[str]] = {}
        for c in self.m.connections:
            if not c.series_elements:
                continue
            for endpoint in (c.source, c.target):
                bid = endpoint.split(".")[0]
                blk = self.m.block(bid)
                if blk and blk.modelica_class and "Transport" in (blk.modelica_class or ""):
                    by_path.setdefault(bid, [])
                    for el in c.series_elements:
                        if el not in by_path[bid]:
                            by_path[bid].append(el)
                    break

        actuators = {s.name for s in self.m.signals if s.role == "actuator"}
        for path_id, elements in by_path.items():
            terms = []
            for el in elements:
                name = el if el in actuators else f"cmd_{el}"
                if name in actuators:
                    terms.append(f"{ctrl}.{_mid(name)}")
            if not terms:
                continue
            expr = " and ".join(terms)
            self._w(2, f"// @lowering series group {{{', '.join(elements)}}} -> one command")
            self._w(2, f"{_mid(path_id)}.open = {expr};")
            self._driven.add(f"{path_id}.open")

    def _emit_scenario(self, sc: Any) -> None:
        interval = sc.interval or max(sc.stop_time / 500.0, 1e-6)
        self._w(1, f"model {_mid(sc.name)} \"{sc.id}\"")
        self._w(2, "extends Plant;")
        self._w(2, "annotation (")
        self._w(
            3,
            f"experiment(StopTime = {sc.stop_time}, Interval = {interval}, Tolerance = {sc.tolerance}),",
        )
        self._w(3, f'__OpenModelica_simulationFlags(s = "{sc.solver}"));')
        self._w(1, f"end {_mid(sc.name)};")
        self._w(0)


def _port_name(raw: str) -> str:
    """Sanitise a connector name while preserving array subscripts like outlet[1]."""
    m = re.match(r"^([A-Za-z_]\w*)((?:\[\s*\d+\s*\])*)$", raw.strip())
    return f"{m.group(1)}{m.group(2)}" if m else _mid(raw)


def _mid(raw: str) -> str:
    out = re.sub(r"[^A-Za-z0-9_]", "_", raw.strip())
    return out if out and not out[0].isdigit() else f"m_{out}"


def _mtype(datatype: str) -> str:
    return {"real": "Real", "boolean": "Boolean", "integer": "Integer"}.get(datatype, "Real")


def emit_modelica(
    model: SystemModel,
    out_path: str | Path,
    *,
    index: CatalogIndex | None = None,
    router: Any | None = None,
    package: str = "GeneratedPlant",
) -> tuple[Path, dict[str, int]]:
    """Bind every block, then emit. Returns the path and a per-tier histogram for the report."""
    binder = Binder(index, router)
    tiers: dict[str, int] = {"L0": 0, "L1": 0, "L2": 0, "unbound": 0}
    for b in model.simulatable_blocks():
        if b.binding_tier != "unbound" and b.modelica_class:
            tiers[b.binding_tier] += 1  # already bound, e.g. loaded from a fixture IR
            continue
        res = binder.bind(b)
        b.binding_tier = res.tier  # type: ignore[assignment]
        b.modelica_class = res.modelica_class
        b.modelica_modifiers = res.modifiers
        b.binding_rationale = res.rationale
        b.synthesised_equations = res.synthesised
        tiers[res.tier] += 1

    # First recover what the evidence DOES state but column extraction missed, then
    # assume only what is genuinely absent. Order matters: a recovered fact must never
    # be overwritten by an assumption.
    log = AssumptionLog()
    model.gaps.extend(recover_stated_initial_values(model, index))
    model.gaps.extend(fill_missing_initial_inventory(model, index, log))
    # Resolve dangling instrument tags before emission, so a permissive that depends on one
    # is written against the plant rather than against an assumed zero.
    model.gaps.extend(bind_sensors_to_resolved_setpoints(model, index))

    # Reconcile the document's port vocabulary with the bound class's real connectors
    # BEFORE emitting. Skipping this writes `B1.bottom_port`, which no class declares.
    for problem in resolve_ports(model, index):
        model.gaps.append(
            Gap(id=f"GAP-PORT-{len(model.gaps):02d}", kind="unmapped_component",
                subject=problem.split(":")[0], detail=problem, severity="warn")
        )

    text = ModelicaEmitter(model, package, index, log).emit()
    # Attach AFTER emission: the emitter is the last stage that can invent a value, so
    # anything it assumed has to be in the IR before the report reads it.
    log.attach(model)
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    (p.parent / "binding_report.json").write_text(
        json.dumps(
            {
                "tiers": tiers,
                "blocks": [
                    {
                        "id": b.id,
                        "tier": b.binding_tier,
                        "class": b.modelica_class,
                        "why": b.binding_rationale,
                    }
                    for b in model.simulatable_blocks()
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return p, tiers
