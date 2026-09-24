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
from ..ir.system import Block, StateMachine, SystemModel

IND = "  "


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
        """Only ever emit modifiers that exist on the target class."""
        valid = {p.name for p in entry.params}
        out: dict[str, str] = {}
        for p in block.parameters:
            target = (explicit or {}).get(p.name, p.name)
            if target in valid and p.quantity.value is not None:
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
        """Author equations only, inside a skeleton whose ports and units we fixed.

        TODO(C): wire the prompt and the balance check. The skeleton constrains the model to
        the one thing it is good at -- writing a handful of equations -- and keeps connector
        balance, unit declarations and naming out of its reach entirely.
        """
        if self.router is None:
            return None
        return None


def _literal(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    return f'"{v}"'


# --------------------------------------------------------------------------------- emission


class ModelicaEmitter:
    def __init__(self, model: SystemModel, package: str = "GeneratedPlant") -> None:
        self.m = model
        self.package = package
        self.lines: list[str] = []

    def _w(self, depth: int, text: str = "") -> None:
        self.lines.append(f"{IND * depth}{text}" if text else "")

    def emit(self) -> str:
        self._w(0, f"package {self.package}")
        self._w(1, f'"Generated by SpecAlive from {len(self.m.sources)} evidence sources."')
        self._w(0)
        for sm in self.m.state_machines:
            self._emit_controller(sm)
        self._emit_plant()
        for sc in self.m.scenarios:
            self._emit_scenario(sc)
        self._w(0, f'  annotation (uses(Modelica(version = "4.0.0"), SpecAlive(version = "0.1.0")));')
        self._w(0, f"end {self.package};")
        return "\n".join(self.lines) + "\n"

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
                for t in outgoing:
                    guard = self._guard_to_modelica(t.guard, sm, order)
                    self._w(4, f"if {guard} then")
                    tgt_region = (sm.state(t.target_state) or st).region
                    self._w(5, f"s_{_mid(tgt_region)} := {order[tgt_region][t.target_state]};")
                    for fork in t.forks:
                        fs = sm.state(fork)
                        if fs:
                            self._w(5, f"s_{_mid(fs.region)} := {order[fs.region][fork]};")
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
        for region, states in order.items():
            for sid, idx in states.items():
                out = re.sub(rf"\bin\({sid}\)", f"pre(s_{_mid(region)}) == {idx}", out)
                out = re.sub(rf"\b{re.escape(sid)}\.active\b", f"pre(s_{_mid(region)}) == {idx}", out)
        for s in self.m.signals:
            if s.id != s.name:
                out = re.sub(rf"\b{re.escape(s.id)}\b", _mid(s.name), out)
        return re.sub(r"\s+", " ", out).strip()

    # ------------------------------------------------------------------ plant
    def _emit_plant(self) -> None:
        self._w(1, f"model Plant \"{self.m.description or self.m.name}\"")
        for b in self.m.simulatable_blocks():
            if b.binding_tier == "unbound" or not b.modelica_class:
                self._w(2, f"// GAP: block '{b.id}' ({b.kind}) has no binding; see report.")
                continue
            mods = ", ".join(f"{k} = {v}" for k, v in sorted(b.modelica_modifiers.items()))
            decl = f"{b.modelica_class} {_mid(b.id)}"
            if mods:
                decl += f"({mods})"
            trace = " ".join(f"@trace {r}" for r in b.provenance.requirement_ids)
            self._w(2, f'{decl} "{b.description or b.name}{" " + trace if trace else ""}";')
        for sm in self.m.state_machines:
            self._w(2, f"{_mid(sm.name)} {_mid(sm.id)};")
        self._w(0)
        self._w(1, "equation")
        simulated = {b.id for b in self.m.simulatable_blocks()}
        for c in self.m.connections:
            ends = {c.source.split(".")[0], c.target.split(".")[0]}
            if not ends <= simulated:
                # An architecture-only part (a boundary, a manual valve) has no instance here.
                self._w(2, f"// architecture only: {c.id} ({c.source} -> {c.target}) is not simulated")
                continue
            note = f"  // @series {', '.join(c.series_elements)}" if c.series_elements else ""
            self._w(2, f"connect({self._ref(c.source)}, {self._ref(c.target)});{note}")
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
            self._w(0)
            self._emit_series_groups(ctrl)
        self._w(1, "end Plant;")
        self._w(0)

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

    text = ModelicaEmitter(model, package).emit()
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
