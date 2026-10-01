"""Turn a test procedure's acceptance criteria into checks against the actual result.

A procedure states its criteria in engineering prose: "All valves shall be closed throughout
the STOP interval from 220 s until the START command at 280 s." Nothing deterministic turns
that into `during(controller.cmd_XV_101 <= 0.5, 220, 280)` -- it takes knowing that "all
valves" means three command signals and that a Boolean is logged as 0/1. A model can make
that translation; it cannot be trusted to make it correctly, so the design is:

  * the translation is done at VERIFY time, when the simulation's columns are known, and
    the model is shown only those columns -- it cannot name a variable that does not exist;
  * every expression it writes is evaluated against the real result before it is accepted,
    so one that does not parse, or reads a missing column, is rejected and the model is
    asked once more with the reason;
  * a criterion that still cannot be formalised is reported as NOT MACHINE-CHECKABLE --
    never silently passed, never silently dropped;
  * a translation that worked is remembered (catalog/memory.py) and reused on later runs,
    re-validated against that run's columns, so an offline run checks what an earlier
    cloud run learned to check.

Owner: D.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from ..ir.system import SystemModel
from .acceptance import ExpressionError, evaluate, referenced_signals

TRANSLATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["checkable", "expression", "reason"],
    "properties": {
        "checkable": {"type": "boolean"},
        "expression": {"type": "string"},
        "tolerance": {"type": "number"},
        "reason": {"type": "string"},
    },
}

TRANSLATE_PROMPT = """\
Translate ONE acceptance criterion from an engineering test procedure into a check over a
simulation result. Use ONLY the expression language and the column names below.

EXPRESSION LANGUAGE (one expression; nest only inside before())
  crosses(COL, VALUE, rising|falling)       the event happens; observed value = its time
  before(EVENT_A, EVENT_B)                  EVENT_A happens no later than EVENT_B (each a crosses(...))
  final(COL) OP VALUE                       value at the end of the run
  at(COL, TIME) OP VALUE                    value at a given time
  always(COL OP VALUE)                      holds for the whole run
  during(COL OP VALUE, T0, T1)              holds for every sample between T0 and T1 seconds
  max(COL) OP VALUE  /  min(COL) OP VALUE   extreme over the run
  approx(final(COL), VALUE, REL)            within relative tolerance REL (0.01 = 1%)
  approx(at(COL, TIME), VALUE, REL)
  approx(abs(final(COL)), VALUE, REL)       magnitude agreement -- use when the procedure or its
                                            context speaks of MAGNITUDES, which fixes no sign
  ratio(COL_A, COL_B) OP VALUE              final COL_A / final COL_B (set "tolerance" for ==)
  state(COL, TIME) OP VALUE                 a discrete value (state number, Boolean) at TIME, held
  enters(COL, K)  /  enters(COL, K, N)      event: the (Nth) time a discrete column becomes K
  elapsed(EVENT_A, EVENT_B) OP VALUE        seconds from EVENT_A to EVENT_B (events: crosses/enters)
  exclusive(COL_A, COL_B)                   two Boolean columns are never true at the same time
  EXPR && EXPR && ...                       every part must hold (use for "all valves closed")
  OP is one of <= >= < > == !=

HOW TO CHECK CONTROLLER BEHAVIOUR
  - "state X is active at time T": state(controller.s_main, T) == <number of X>; pick T a
    second or two after the event that should cause it, never exactly at the event.
  - "state X throughout T0..T1": during(controller.s_main == <number of X>, T0, T1).
  - "X happens before Y": before(EVENT_X, EVENT_Y), with enters(controller.s_main, K) for
    "state K is entered" -- never crosses() on a state number, which is ambiguous.
  - "after a D second delay": elapsed(EVENT_A, EVENT_B) >= D (set "tolerance" and use == to
    bound it from both sides).

FACTS
  - Boolean signals are logged as 0 (false) and 1 (true); test them with <= 0.5 or >= 0.5.
  - Values are in SI units: convert ppm, degC, mm, kPa etc. yourself before writing VALUE.
  - The controller scans every {scan:g} s, so a command takes effect within one scan of its
    stated time: check a commanded state 1 s AFTER the command, and start a "throughout"
    window 1 s after the event that opens it.
  - The run lasts {stop_time:g} s.
{state_map}{tag_map}{parameters}
COLUMNS AVAILABLE (the only names you may use)
{columns}

CRITERION ({cid})
{criterion}

If one expression in this language cannot check the criterion faithfully -- it is about
document content, logging format, a quantity no column carries, or several independent
conditions -- answer checkable=false and say why in `reason`. A faithful partial check is
NOT acceptable: an expression that checks something weaker than the criterion is worse
than none. Return JSON only.
"""


def _key(criterion: str) -> str:
    return hashlib.sha256(criterion.strip().lower().encode("utf-8")).hexdigest()[:16]


def _columns_for_prompt(cols: dict[str, list[float]], limit: int = 260) -> list[str]:
    """Columns worth showing: no derivatives, no solver internals, constants last."""
    names = [c for c in cols if c != "time" and not c.startswith(("der(", "$")) and "$" not in c]
    moving = [c for c in names if cols[c] and max(cols[c]) != min(cols[c])]
    still = [c for c in names if c not in moving]
    return (moving + still)[:limit]


def _context(model: SystemModel) -> tuple[str, str, str]:
    state_lines = []
    for sm in model.state_machines:
        for region in sm.regions:
            states = sm.states_in(region)
            mapping = ", ".join(f"{i}={s.name}" for i, s in enumerate(states))
            state_lines.append(f"  - controller.s_{region} is the active state: {mapping}")
    tags = []
    for s in model.signals:
        if s.role == "sensor" and s.binding:
            tags.append(f"  - {s.name} (instrument) reads column {s.binding}")
        elif s.role == "actuator":
            tags.append(f"  - {s.name} is the controller command column controller.{s.name}")
    params = [f"  - {p.id} = {p.quantity.value} {p.quantity.unit or ''}".rstrip()
              for p in model.parameters if p.status == "effective"][:40]
    return ("\n".join(state_lines) + "\n" if state_lines else "",
            ("  Tag map:\n" + "\n".join(tags) + "\n") if tags else "",
            ("  Effective parameters:\n" + "\n".join(params) + "\n") if params else "")


def formalise(
    model: SystemModel,
    cols: dict[str, list[float]],
    *,
    router: Any | None = None,
    memory: Any | None = None,
) -> list[str]:
    """Fill in the expression of every procedure check that has none. Returns notes.

    Mutates the checks in place: a translated one gets its expression (and tolerance); an
    untranslatable one keeps an empty expression and a reason in its provenance note, which
    the scorer reports as not machine-checkable.
    """
    notes: list[str] = []
    stop = (cols.get("time") or [0.0])[-1]
    names = set(cols)
    state_map, tag_map, params = _context(model)
    remembered = getattr(memory, "criteria", None) if memory is not None else None
    scan = model.state_machines[0].scan_period if model.state_machines else 0.1
    times = cols.get("time") or [0.0, 1.0]
    step = (times[-1] - times[0]) / max(len(times) - 1, 1)
    grace = round(2 * scan + 2 * step, 6)
    command_times = sorted({t for sc in model.scenarios for st in sc.stimuli
                            if st.kind == "pulses" for t in st.times})
    done = from_memory = 0

    for sc in model.scenarios:
        for chk in sc.checks:
            if chk.kind != "procedure" or chk.expression:
                continue
            text = chk.criterion or chk.description

            def works(expr: str, tol: float | None) -> tuple[bool, str]:
                missing = [c for c in referenced_signals(expr) if c not in names
                           and c.replace("_", ".") not in names and c.replace(".", "_") not in names]
                if missing:
                    return False, f"reads columns that are not in the result: {', '.join(missing[:4])}"
                try:
                    evaluate(expr, cols, tol)
                except ExpressionError as exc:
                    return False, str(exc)
                return True, ""

            # 1. A translation an earlier run proved -- used only when no model is available.
            # "It evaluates" is not "it is right": a loose translation made by a weak model
            # on one run must not be locked in for every run after it. With a model at hand
            # the criterion is translated afresh (the router's cache keeps that cheap) and
            # the memory is overwritten with the newer answer.
            if router is None and remembered is not None and (hit := remembered.get(_key(text))):
                ok, _ = works(hit["expression"], hit.get("tolerance"))
                if ok:
                    chk.expression, chk.tolerance = hit["expression"], hit.get("tolerance")
                    chk.provenance.note = f"formalised in an earlier run ({hit.get('by', 'model')})"
                    from_memory += 1
                    continue

            if router is None:
                chk.provenance.note = "not machine-checkable here: no model available to formalise it"
                continue

            # 2. Ask, validating against the real result; one retry with the reason.
            prompt = TRANSLATE_PROMPT.format(
                stop_time=stop, scan=scan, state_map=state_map, tag_map=tag_map, parameters=params,
                columns="\n".join(f"  {c}" for c in _columns_for_prompt(cols)),
                cid=chk.id, criterion=text,
            )

            def validate(data: Any) -> tuple[bool, str]:
                if not data.get("checkable"):
                    return True, ""
                return works(str(data.get("expression") or ""), data.get("tolerance"))

            try:
                resp = router.run("formalise_criterion", prompt, schema=TRANSLATE_SCHEMA, validator=validate)
            except Exception as exc:
                chk.provenance.note = f"not machine-checkable here: formalisation failed ({str(exc)[:120]})"
                continue
            data = resp.data or {}
            if not data.get("checkable") or not str(data.get("expression") or "").strip():
                chk.provenance.note = f"not machine-checkable: {str(data.get('reason') or '')[:200]}"
                continue
            chk.expression = _with_reaction_grace(str(data["expression"]).strip(), command_times, grace)
            chk.tolerance = data.get("tolerance")
            chk.provenance.note = f"formalised by {resp.tier} ({resp.model}): {str(data.get('reason') or '')[:160]}"
            done += 1
            if remembered is not None:
                remembered[_key(text)] = {"expression": chk.expression, "tolerance": chk.tolerance,
                                          "by": resp.model, "criterion": text[:200]}

    total = sum(1 for sc in model.scenarios for c in sc.checks if c.kind == "procedure")
    if total:
        notes.append(f"{done + from_memory}/{total} procedure criteria formalised"
                     + (f" ({from_memory} from earlier runs)" if from_memory else ""))
    return notes


def _with_reaction_grace(expr: str, command_times: list[float], grace: float) -> str:
    """Shift a check that samples exactly at a commanded instant to just after it.

    A procedure says what happens "at 220 s" when STOP is pressed at 220 s -- meaning the
    controller's immediate response, which arrives at its next scan, not in the same
    instant. A window opening at 220 s or a state read at 700 s therefore samples the moment
    BEFORE the command takes effect and fails a controller that responded correctly. Models
    asked to allow for this mostly do not, so it is done here, deterministically, and only
    where the time coincides with a command the scenario actually issues.
    """
    if not command_times or grace <= 0:
        return expr

    def is_command(t: float) -> bool:
        return any(abs(t - c) < 1e-6 for c in command_times)

    def shift(m: re.Match[str]) -> str:
        t = float(m.group(2))
        return f"{m.group(1)}{t + grace:g}" if is_command(t) else m.group(0)

    # during(..., T0, T1): the window's start; state(COL, T) and at(COL, T): the instant.
    expr = re.sub(r"(during\([^,]+,\s*)([-\d.eE+]+)", shift, expr)
    expr = re.sub(r"((?:state|at)\(\s*[\w.\[\]]+\s*,\s*)([-\d.eE+]+)", shift, expr)
    return expr
