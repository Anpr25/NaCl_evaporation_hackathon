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
  * a SEPARATE model call then reviews the translation against the original prose, routed
    through a different tier first where possible -- the mechanical check above only proves
    the expression is valid and computable, never that it means the same thing as the
    criterion. A reviewer that disagrees reverts the translation to NOT MACHINE-CHECKABLE;
    one that cannot be reached leaves the translation exactly as unreviewed as it always was;
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
  - Modelica sign convention: a source's or converter's own flow variable (its i, Phi,
    m_flow) counts flow INTO its positive connector, so it is negative while it delivers.
    For a quantity the circuit carries (core flux, branch current), read the column of a
    passive element that carries it (a core, a gap, a resistor), not the source's.
  - Values are in SI units: convert ppm, degC, mm, kPa etc. yourself before writing VALUE.
    A column may carry a quantity in a scaled or normalised form (a mass fraction, a value
    normalised to a nominal); convert the criterion's number into THAT form using a factor
    the parameters below state, and say which factor in `reason`. A threshold thousands of
    times outside a column's range is rejected as unconverted.
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

_NUM = r"(-?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?)"
_COL = r"([A-Za-z_][\w.\[\]]*)"
_OP = r"(?:<=|>=|==|!=|<|>)"
#: (column, threshold) pairs a check compares, in every form the language allows.
_COMPARISONS = [
    re.compile(rf"(?:max|min|final|always|during)\(\s*{_COL}\s*\)?\s*{_OP}\s*{_NUM}"),
    re.compile(rf"\bat\(\s*{_COL}\s*,\s*{_NUM}\s*\)\s*{_OP}\s*{_NUM}"),
    re.compile(rf"approx\(\s*(?:abs\()?(?:final|at)\(\s*{_COL}[^)]*\)\)?\s*,\s*{_NUM}"),
    re.compile(rf"crosses\(\s*{_COL}\s*,\s*{_NUM}"),
]
#: How far apart a threshold and the column it is compared with may be before the check is
#: judged to compare different units. A tank level of 1 mm against a 2.5 m limit is 2.5e3.
_SCALE_LIMIT = 1e4


def scale_mismatch(expr: str, cols: dict[str, list[float]]) -> str:
    """Why a check compares a column with a threshold in some other unit, or ''.

    'Maximum room CO2 <= 1000 ppm' was formalised as `max(ZON_201.C) <= 1000` against a
    mass fraction that peaks at 1.5e-3: a check that cannot fail, reported as a pass. A
    threshold orders of magnitude outside everything the column ever did is not a
    requirement on that column; it is an unconverted unit.
    """
    for rx in _COMPARISONS:
        for m in rx.finditer(expr):
            col, val = m.group(1), float(m.groups()[-1])
            series = cols.get(col) or cols.get(col.replace("_", ".")) or []
            peak = max((abs(v) for v in series), default=0.0)
            if not val or not peak:
                continue
            ratio = max(abs(val) / peak, peak / abs(val))
            if ratio > _SCALE_LIMIT:
                return (f"threshold {val:g} is {ratio:.0e} times the scale of {col} (peak "
                        f"magnitude {peak:.4g}): the criterion's unit was not converted into "
                        f"the column's -- use a conversion the parameters state")
    return ""


VERIFY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["agrees", "reason"],
    "properties": {
        "agrees": {"type": "boolean"},
        "reason": {"type": "string"},
    },
}

VERIFY_PROMPT = """\
Someone else translated an acceptance criterion from a test procedure into a machine-checkable
expression. Check their work; do not write your own translation, only judge theirs.

CRITERION (the engineering prose, the ground truth)
{criterion}

PROPOSED EXPRESSION
{expression}

EXPRESSION LANGUAGE (for reference -- crosses/before/final/at/always/during/max/min/approx/
approx(abs(...))/ratio/state/enters/elapsed/exclusive, joined with && when the criterion has
more than one part; OP is one of <= >= < > == !=)

CONVENTIONS THE FIRST TRANSLATION WAS ALSO TOLD, SO THEY ARE NOT A DISAGREEMENT BY THEMSELVES
  - A Boolean column is logged as 0 (false) or 1 (true), never exactly mid-scale, so
    `open <= 0.5` IS "closed" and `open >= 0.5` IS "open" -- not a loosened, partial check.
  - A quantity may be converted into SI units or into a scaled/normalised form the column
    itself uses (a mass fraction, a value normalised to a nominal); a stated unit not
    matching the column's literally is not itself a disagreement, only a wrong NUMBER is.
  - A column's own name is often not descriptive (`CTL_CO2_201.y`, not `ach_command`). Use
    the context below -- state names, instrument tag bindings, and effective parameters --
    the same way the first translation did, before judging that a column is the wrong one.
{context}
Does the expression check EXACTLY what the criterion states -- same quantity, same direction,
same bound, same timing -- no more and no less, the conventions above aside? A partial match
(checks something related but weaker, omits part of a conjunctive criterion, or gets the
direction/sign backwards) is a disagreement, not a pass. Set `agrees` to true only if you
would have written the same check yourself from the criterion alone. Say why in `reason`, one
sentence. Return JSON only.
"""


def _independent_review(
    criterion: str, expression: str, context: str, router: Any
) -> tuple[bool, str] | None:
    """A second, independent model call that checks the first model's translation against
    the original prose, instead of trusting the pass that wrote it.

    Routed (config/models.yaml) through a different tier first than `formalise_criterion`
    uses first, so the common case is a different vendor's model reviewing the answer, not
    the same one re-reading its own work -- closer to a real second opinion than a second
    rendering of the first.

    `context` is the SAME state/tag/parameter text the first translation was shown
    (`_context(model)`). Without it, a column whose name does not read as what it is
    (`CTL_CO2_201.y` for "the ACH command") looks wrong to a reviewer who cannot see why it
    is right -- which is a gap in the reviewer's information, not a defect in the
    translation, and must not be allowed to masquerade as one.

    Never raises and never blocks: a review that could not be obtained (no router, a quota
    error, a malformed reply) is reported as None -- "not reviewed" -- and the original
    translation stands exactly as it did before this existed. Only an EXPLICIT disagreement
    changes anything.
    """
    try:
        resp = router.run(
            "verify_criterion",
            VERIFY_PROMPT.format(criterion=criterion, expression=expression, context=context),
            schema=VERIFY_SCHEMA,
        )
    except Exception:
        return None
    data = resp.data or {}
    if "agrees" not in data:
        return None
    return bool(data["agrees"]), str(data.get("reason") or "")[:200]


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
    # Part parameters too: the factor that turns a procedure's unit into a column's is
    # usually stated against the part that measures it ('nominal concentration 1.519e-3
    # kg/kg = 1000 ppm' on the CO2 sensor), not as a plant-wide constant.
    params += [f"  - {p.id} = {p.quantity.value} {p.quantity.unit or ''}".rstrip()
               for b in model.simulatable_blocks() for p in b.parameters
               if p.status == "effective" and isinstance(p.quantity.value, (int, float))][:40]
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
    done = from_memory = rejected_on_review = 0

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
                why = scale_mismatch(expr, cols)
                if why:
                    return False, why
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
            raw_expr = str(data["expression"]).strip()
            proposed_tol = data.get("tolerance")
            formalised_by = f"formalised by {resp.tier} ({resp.model}): {str(data.get('reason') or '')[:160]}"

            # 3. An independent second opinion, before the translation is trusted. The
            # mechanical checks in `works()` above only prove the expression is valid and
            # computable -- they cannot catch one that is syntactically fine and simply
            # means something else than the criterion. This is the only check on THAT.
            #
            # Reviewed as the model wrote it, BEFORE `_with_reaction_grace` below shifts a
            # command-instant time by one scan period. That shift is our own deterministic
            # convention, not something the model decided or the criterion's prose varies
            # on, and a reviewer shown '220.295' against a criterion that says '220 s' has
            # no way to know the 0.295 is intentional -- it correctly (by its own lights)
            # calls that a mismatch, and a provably right translation gets discarded. The
            # reviewer sees exactly the comparison that matters: what the model proposed
            # against what the criterion states.
            review = _independent_review(text, raw_expr, state_map + tag_map + params, router)
            if review is not None and not review[0]:
                chk.provenance.note = (
                    f"not machine-checkable: a translation was proposed ({raw_expr}) "
                    f"but an independent review disagreed -- {review[1]}"
                )
                rejected_on_review += 1
                continue

            proposed_expr = _with_reaction_grace(raw_expr, command_times, grace)
            chk.expression, chk.tolerance = proposed_expr, proposed_tol
            chk.provenance.note = formalised_by + (
                f"; independently confirmed ({review[1]})" if review else ""
            )
            done += 1
            if remembered is not None:
                remembered[_key(text)] = {"expression": chk.expression, "tolerance": chk.tolerance,
                                          "by": resp.model, "criterion": text[:200]}

    total = sum(1 for sc in model.scenarios for c in sc.checks if c.kind == "procedure")
    if total:
        notes.append(f"{done + from_memory}/{total} procedure criteria formalised"
                     + (f" ({from_memory} from earlier runs)" if from_memory else "")
                     + (f"; {rejected_on_review} rejected on independent review"
                        if rejected_on_review else ""))
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
