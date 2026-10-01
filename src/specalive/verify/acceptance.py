"""Score a simulation against the acceptance criteria extracted from the test procedure.

Event checks are primary; signal comparison is secondary and only quoted when the reference
data has passed every applicable consistency screen (conserved species, first-order
spin-up, energy direction). That ordering is not a convenience -- the
NaCl packet's reference trace is *not* mass-consistent (NaCl mass falls ~10% across the
evaporation phase), so an RMSE against it would be scoring against bad data. Detecting that and
saying so is worth more than a good-looking error number.

Owner: D, with C on the expression language.
"""

from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..ir.system import AcceptanceCheck, SystemModel
from .omc import crossing_time, read_result, sample_at


@dataclass
class CheckResult:
    check_id: str
    description: str
    passed: bool
    detail: str
    requirement_ids: list[str] = field(default_factory=list)
    observed: Any = None
    expected: Any = None
    #: False when the criterion could not be turned into a check at all -- it is then
    #: neither a pass nor a fail, and is reported separately rather than hidden.
    checkable: bool = True
    #: True when a MODEL wrote the check from the procedure's prose. Reported apart from
    #: checks derived from the evidence's own numbers, because a wrong translation can fail
    #: a model that behaved correctly, and the reader must be able to tell which is which.
    formalised: bool = False

    def icon(self) -> str:
        if not self.checkable:
            return "N/A "
        return "PASS" if self.passed else "FAIL"


@dataclass
class Scorecard:
    results: list[CheckResult] = field(default_factory=list)
    reference_consistent: bool | None = None
    reference_notes: list[str] = field(default_factory=list)
    signal_errors: dict[str, float] = field(default_factory=dict)
    #: What formalising the procedure's criteria did, for the report.
    notes: list[str] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed and r.checkable)

    @property
    def total(self) -> int:
        return sum(1 for r in self.results if r.checkable)

    @property
    def unchecked(self) -> int:
        return sum(1 for r in self.results if not r.checkable)

    @property
    def ok(self) -> bool:
        return self.total > 0 and self.passed == self.total

    def summary(self) -> str:
        own = [r for r in self.results if r.checkable and not r.formalised]
        prose = [r for r in self.results if r.checkable and r.formalised]
        parts = [f"{self.passed}/{self.total} acceptance checks passed"]
        if prose:
            parts.append(f"evidence checks {sum(r.passed for r in own)}/{len(own)}, "
                         f"procedure criteria (model-formalised) {sum(r.passed for r in prose)}/{len(prose)}")
        if self.unchecked:
            parts.append(f"{self.unchecked} criteria not machine-checkable")
        return "; ".join(parts)


# --------------------------------------------------------------------- expression language

#: Deliberately tiny and total. A check expression is data extracted from a document, so it
#: must never be able to execute anything. These five forms cover every acceptance criterion in
#: the NaCl packet and generalise to threshold/ordering criteria in any domain.
#:
#:   crosses(signal, value, rising|falling)          -> the event happens at all
#:   before(exprA, exprB)                            -> ordering between two events
#:   final(signal) op value                          -> end-state assertion
#:   at(signal, time) op value                       -> point assertion
#:   always(signal op value)                         -> invariant over the whole run
_CROSSES = re.compile(r"crosses\(\s*([\w.\[\]]+)\s*,\s*([-\d.eE+]+)\s*(?:,\s*(rising|falling)\s*)?\)")
_BEFORE = re.compile(r"^before\((.*)\)$", re.S)
_FINAL = re.compile(r"final\(\s*([\w.\[\]]+)\s*\)\s*(<=|>=|<|>|==|!=)\s*([-\d.eE+]+)")
_AT = re.compile(r"at\(\s*([\w.\[\]]+)\s*,\s*([-\d.eE+]+)\s*\)\s*(<=|>=|<|>|==|!=)\s*([-\d.eE+]+)")
_ALWAYS = re.compile(r"always\(\s*([\w.\[\]]+)\s*(<=|>=|<|>)\s*([-\d.eE+]+)\s*\)")
#: The forms a test procedure's criteria need beyond events and end states:
#:   during(signal op value, t0, t1)   -> an invariant over a window ("all valves closed
#:                                        from 220 s until 280 s")
#:   max(signal) op value / min(...)   -> an extreme over the run ("maximum CO2 <= 1000 ppm")
#:   approx(final(signal), value, rel) -> agreement within a relative tolerance ("within 1%
#:                                        of the analytic result"); also approx(at(s, t), ...)
#:   ratio(sigA, sigB) op value        -> a final-value ratio ("useful/core flux = 0.92")
_DURING = re.compile(r"during\(\s*([\w.\[\]]+)\s*(<=|>=|<|>|==)\s*([-\d.eE+]+)\s*,\s*([-\d.eE+]+)\s*,\s*([-\d.eE+]+)\s*\)")
_EXTREME = re.compile(r"(max|min)\(\s*([\w.\[\]]+)\s*\)\s*(<=|>=|<|>)\s*([-\d.eE+]+)")
_APPROX = re.compile(r"approx\(\s*(?:final\(\s*([\w.\[\]]+)\s*\)|at\(\s*([\w.\[\]]+)\s*,\s*([-\d.eE+]+)\s*\))"
                     r"\s*,\s*([-\d.eE+]+)\s*,\s*([-\d.eE+]+)\s*\)")
#:   approx(abs(final(COL)), VALUE, REL) -> magnitude agreement, for a procedure that says
#:                                        "magnitudes shall agree" and so does not fix a sign
_APPROX_ABS = re.compile(r"approx\(\s*abs\(\s*(?:final\(\s*([\w.\[\]]+)\s*\)|at\(\s*([\w.\[\]]+)\s*,\s*([-\d.eE+]+)\s*\))\s*\)"
                         r"\s*,\s*([-\d.eE+]+)\s*,\s*([-\d.eE+]+)\s*\)")
_RATIO = re.compile(r"ratio\(\s*([\w.\[\]]+)\s*,\s*([\w.\[\]]+)\s*\)\s*(<=|>=|<|>|==)\s*([-\d.eE+]+)")


#:   state(COL, T) OP VALUE            -> a discrete value at T, held (no interpolation: an
#:                                        integer state interpolated across a transition is
#:                                        a fraction that matches no state)
#:   exclusive(COL_A, COL_B)           -> two Boolean signals never true at the same time
_STATE = re.compile(r"state\(\s*([\w.\[\]]+)\s*,\s*([-\d.eE+]+)\s*\)\s*(<=|>=|<|>|==|!=)\s*([-\d.eE+]+)")
#:   enters(COL, K[, N])               -> event: the Nth time a discrete column becomes K.
#:                                        A threshold crossing is ambiguous on state numbers:
#:                                        pausing from state 3 into state 7 "crosses 5.5".
#:   elapsed(EVENT_A, EVENT_B) OP VALUE -> seconds from A to B ("after the 8 s delay")
_ENTERS = re.compile(r"enters\(\s*([\w.\[\]]+)\s*,\s*([-\d.eE+]+)\s*(?:,\s*(\d+)\s*)?\)")
_ELAPSED = re.compile(r"elapsed\((.*)\)\s*(<=|>=|<|>|==)\s*([-\d.eE+]+)", re.S)
_EXCLUSIVE = re.compile(r"exclusive\(\s*([\w.\[\]]+)\s*,\s*([\w.\[\]]+)\s*\)")
_NAME, _NUM, _OP = r"[\w.\[\]]+", r"[-\d.eE+]+", r"(?:<=|>=|<|>|==|!=)"
#: Every single (non-conjunctive) form, anchored. Used to refuse anything with trailing text.
_FORMS = re.compile(
    rf"\s*(?:"
    rf"before\(.*\)"
    rf"|crosses\(\s*{_NAME}\s*,\s*{_NUM}\s*(?:,\s*(?:rising|falling)\s*)?\)"
    rf"|final\(\s*{_NAME}\s*\)\s*{_OP}\s*{_NUM}"
    rf"|at\(\s*{_NAME}\s*,\s*{_NUM}\s*\)\s*{_OP}\s*{_NUM}"
    rf"|always\(\s*{_NAME}\s*{_OP}\s*{_NUM}\s*\)"
    rf"|during\(\s*{_NAME}\s*{_OP}\s*{_NUM}\s*,\s*{_NUM}\s*,\s*{_NUM}\s*\)"
    rf"|(?:max|min)\(\s*{_NAME}\s*\)\s*{_OP}\s*{_NUM}"
    rf"|approx\(\s*(?:final\(\s*{_NAME}\s*\)|at\(\s*{_NAME}\s*,\s*{_NUM}\s*\))\s*,\s*{_NUM}\s*,\s*{_NUM}\s*\)"
    rf"|approx\(\s*abs\(\s*(?:final\(\s*{_NAME}\s*\)|at\(\s*{_NAME}\s*,\s*{_NUM}\s*\))\s*\)\s*,\s*{_NUM}\s*,\s*{_NUM}\s*\)"
    rf"|ratio\(\s*{_NAME}\s*,\s*{_NAME}\s*\)\s*{_OP}\s*{_NUM}"
    rf")\s*", re.S)


def _split_conjunction(expr: str) -> list[str]:
    """Split on `&&` or ` and ` at bracket depth zero."""
    parts, depth, start, i = [], 0, 0, 0
    while i < len(expr):
        ch = expr[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0 and expr.startswith("&&", i):
            parts.append(expr[start:i]); i += 2; start = i; continue
        elif depth == 0 and expr[i:i + 5].lower() == " and ":
            parts.append(expr[start:i]); i += 5; start = i; continue
        i += 1
    parts.append(expr[start:])
    return [p.strip() for p in parts if p.strip()]


def referenced_signals(expr: str) -> list[str]:
    """Every result column an expression reads -- for checking a model-written expression
    against the columns that actually exist before it is ever evaluated."""
    out: list[str] = []
    for pat, groups in ((_CROSSES, (1,)), (_FINAL, (1,)), (_AT, (1,)), (_ALWAYS, (1,)),
                        (_DURING, (1,)), (_EXTREME, (2,)), (_APPROX, (1, 2)), (_RATIO, (1, 2)),
                        (_STATE, (1,)), (_EXCLUSIVE, (1, 2)), (_ENTERS, (1,)),
                        (_APPROX_ABS, (1, 2))):
        for m in pat.finditer(expr):
            out += [m.group(g) for g in groups if m.group(g)]
    return out

_OPS = {
    "<=": lambda a, b: a <= b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    ">": lambda a, b: a > b,
    # Equal to six significant figures, not to 1e-9 absolute: a simulated 1.909859e6 never
    # equals the stated 1909859 bit for bit, and an integer state (3.0 == 3) still does.
    "==": lambda a, b: abs(a - b) <= max(1e-9, 1e-6 * max(abs(a), abs(b))),
    "!=": lambda a, b: abs(a - b) >= 1e-9,
}


class ExpressionError(ValueError):
    pass


def evaluate(expr: str, cols: dict[str, list[float]], tolerance: float | None = None) -> tuple[bool, str, Any]:
    """Evaluate one acceptance expression. Returns (passed, human detail, observed value).

    Every form must account for the WHOLE expression. The patterns used to be matched as a
    prefix, so `during(a <= 0.5, 220, 280) && during(b <= 0.5, 220, 280)` evaluated the
    first clause, ignored the second, and could pass a criterion that was half violated.
    Conjunctions are now explicit -- `&&` / `and` at the top level, every part must pass --
    and anything left unparsed is an error, not a pass.
    """
    expr = expr.strip()
    times = cols.get("time") or []

    parts = _split_conjunction(expr)
    if len(parts) > 1:
        details, observed = [], []
        for part in parts:
            ok, detail, obs = evaluate(part, cols, tolerance)
            details.append(detail)
            observed.append(obs)
            if not ok:
                return False, f"{detail} (one of {len(parts)} required conditions)", observed
        return True, "; ".join(details), observed

    if m := _ENTERS.fullmatch(expr):
        sig, k, nth = m.group(1), float(m.group(2)), int(m.group(3) or 1)
        series = _series(cols, sig)
        entries = [times[i] for i in range(1, len(series))
                   if abs(series[i] - k) < 1e-9 and abs(series[i - 1] - k) >= 1e-9]
        if series and abs(series[0] - k) < 1e-9:
            entries.insert(0, times[0])
        if len(entries) < nth:
            return False, f"{sig} entered {k:g} only {len(entries)} time(s), needed {nth}", None
        return True, f"{sig} entered {k:g} (occurrence {nth}) at t={entries[nth - 1]:.1f}s", entries[nth - 1]

    if m := _ELAPSED.fullmatch(expr):
        try:
            first, second = _split_top_level(m.group(1))
        except ValueError as exc:
            raise ExpressionError(f"elapsed() needs exactly two events: {exc}") from exc
        op, val = m.group(2), float(m.group(3))
        t1, t2 = _event_time(first, cols), _event_time(second, cols)
        if t1 is None or t2 is None:
            return False, f"an event of elapsed() never occurred: {first if t1 is None else second}", None
        gap, tol = t2 - t1, (tolerance or 0.0)
        ok = abs(gap - val) <= max(tol, 1e-9) if op == "==" else _OPS[op](gap, val)
        return ok, f"elapsed {gap:.2f} s between the events, required {op} {val:g}" + (f" ±{tol:g}" if tol else ""), gap

    if m := _STATE.fullmatch(expr):
        sig, t, op, val = m.group(1), float(m.group(2)), m.group(3), float(m.group(4))
        series = _series(cols, sig)
        idx = max((i for i, tt in enumerate(times) if tt <= t + 1e-9), default=0)
        got = series[idx] if series else float("nan")
        return _OPS[op](got, val), f"{sig} at t={t:g}s (held) = {got:.4g}, required {op} {val}", got

    if m := _EXCLUSIVE.fullmatch(expr):
        a, b = m.group(1), m.group(2)
        sa, sb = _series(cols, a), _series(cols, b)
        both = [times[i] for i in range(min(len(sa), len(sb))) if sa[i] > 0.5 and sb[i] > 0.5]
        if both:
            return False, f"{a} and {b} both true at t={both[0]:.1f}s ({len(both)} samples)", both[0]
        return True, f"{a} and {b} never true together", None

    if not _FORMS.fullmatch(expr):
        raise ExpressionError(f"unsupported acceptance expression: {expr!r}")

    if m := _BEFORE.match(expr):
        try:
            first, second = _split_top_level(m.group(1))
        except ValueError as exc:
            raise ExpressionError(f"before() needs exactly two arguments: {exc}") from exc
        t1 = _event_time(first, cols)
        t2 = _event_time(second, cols)
        if t1 is None:
            return False, f"first event never occurred: {first}", None
        if t2 is None:
            return False, f"second event never occurred: {second}", None
        return t1 <= t2, f"t({first})={t1:.1f}s vs t({second})={t2:.1f}s", (t1, t2)

    if m := _CROSSES.match(expr):
        sig, val, sense = m.group(1), float(m.group(2)), (m.group(3) or "rising")
        series = _series(cols, sig)
        t = crossing_time(times, series, val, rising=(sense == "rising"))
        if t is None:
            peak = (max(series) if sense == "rising" else min(series)) if series else float("nan")
            return False, f"{sig} never crossed {val} ({sense}); extreme reached was {peak:.4g}", None
        return True, f"{sig} crossed {val} at t={t:.1f}s", t

    if m := _FINAL.match(expr):
        sig, op, val = m.group(1), m.group(2), float(m.group(3))
        series = _series(cols, sig)
        got = series[-1] if series else float("nan")
        ok = _OPS[op](got, val + (tolerance or 0.0) * (1 if op in ("<=", "<") else -1))
        return ok, f"final {sig}={got:.4g}, required {op} {val}", got

    if m := _AT.match(expr):
        sig, t, op, val = m.group(1), float(m.group(2)), m.group(3), float(m.group(4))
        got = sample_at(times, _series(cols, sig), t)
        return _OPS[op](got, val), f"{sig}(t={t})={got:.4g}, required {op} {val}", got

    if m := _DURING.match(expr):
        sig, op, val, t0, t1 = m.group(1), m.group(2), float(m.group(3)), float(m.group(4)), float(m.group(5))
        series = _series(cols, sig)
        window = [(times[i], v) for i, v in enumerate(series) if t0 <= times[i] <= t1]
        if not window:
            return False, f"no samples of {sig} between {t0:g} s and {t1:g} s", None
        bad = [(t, v) for t, v in window if not _OPS[op](v, val)]
        if bad:
            return False, (f"{sig} {op} {val} violated at t={bad[0][0]:.1f}s (value {bad[0][1]:.4g}) "
                           f"within {t0:g}-{t1:g} s"), bad[0][1]
        return True, f"{sig} {op} {val} held from {t0:g} s to {t1:g} s", None

    if m := _EXTREME.match(expr):
        fn, sig, op, val = m.group(1), m.group(2), m.group(3), float(m.group(4))
        series = _series(cols, sig)
        if not series:
            return False, f"no samples of {sig}", None
        got = max(series) if fn == "max" else min(series)
        at_t = times[series.index(got)] if times else float("nan")
        return _OPS[op](got, val), f"{fn}({sig}) = {got:.6g} at t={at_t:.1f}s, required {op} {val}", got

    if m := _APPROX_ABS.fullmatch(expr):
        sig = m.group(1) or m.group(2)
        series = _series(cols, sig)
        got = sample_at(times, series, float(m.group(3))) if m.group(2) else (series[-1] if series else float("nan"))
        want, rel = float(m.group(4)), float(m.group(5))
        err = abs(abs(got) - abs(want)) / max(abs(want), 1e-30)
        return err <= rel, f"|{sig}| = {abs(got):.6g}, expected {abs(want):.6g} within {rel:.2%} (off by {err:.2%})", got

    if m := _APPROX.match(expr):
        sig = m.group(1) or m.group(2)
        series = _series(cols, sig)
        got = sample_at(times, series, float(m.group(3))) if m.group(2) else (series[-1] if series else float("nan"))
        want, rel = float(m.group(4)), float(m.group(5))
        err = abs(got - want) / max(abs(want), 1e-30)
        return err <= rel, f"{sig} = {got:.6g}, expected {want:.6g} within {rel:.2%} (off by {err:.2%})", got

    if m := _RATIO.match(expr):
        a, b, op, val = m.group(1), m.group(2), m.group(3), float(m.group(4))
        sa, sb = _series(cols, a), _series(cols, b)
        if not sa or not sb or abs(sb[-1]) < 1e-30:
            return False, f"ratio {a}/{b} undefined at the end of the run", None
        got = sa[-1] / sb[-1]
        tol = tolerance or 0.0
        ok = abs(got - val) <= tol if op == "==" else _OPS[op](got, val)
        return ok, f"final {a}/{b} = {got:.6g}, required {op} {val}" + (f" ±{tol:g}" if tol else ""), got

    if m := _ALWAYS.match(expr):
        sig, op, val = m.group(1), m.group(2), float(m.group(3))
        series = _series(cols, sig)
        bad = [(times[i], v) for i, v in enumerate(series) if not _OPS[op](v, val)]
        if bad:
            return False, f"{sig} {op} {val} violated at t={bad[0][0]:.1f}s (value {bad[0][1]:.4g}), {len(bad)} samples", bad[0][1]
        return True, f"{sig} {op} {val} held for the whole run", None

    raise ExpressionError(f"unsupported acceptance expression: {expr!r}")


def _split_top_level(args: str) -> tuple[str, str]:
    """Split on the comma at bracket depth zero, so nested crosses(...) calls survive."""
    depth = 0
    for i, ch in enumerate(args):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            return args[:i].strip(), args[i + 1 :].strip()
    raise ValueError(f"no top-level comma in {args!r}")


def _event_time(expr: str, cols: dict[str, list[float]]) -> float | None:
    # An event is a crossing or an entry -- something that HAPPENS at a time. A conjunction
    # or an invariant has no time, and accepting one here made `before(A && B, C)` fail as
    # "the first event never occurred" instead of being rejected as malformed, which is a
    # false failure of a model that behaved correctly.
    if not (_CROSSES.fullmatch(expr.strip()) or _ENTERS.fullmatch(expr.strip())):
        raise ExpressionError(f"not an event (use crosses(...) or enters(...)): {expr!r}")
    ok, _, observed = evaluate(expr, cols)
    if not ok:
        return None
    return observed if isinstance(observed, (int, float)) else None


def _series(cols: dict[str, list[float]], name: str) -> list[float]:
    if name in cols:
        return cols[name]
    # Tolerate the dotted/underscored spelling drift between IR names and Modelica names.
    alt = name.replace("_", ".")
    if alt in cols:
        return cols[alt]
    alt2 = name.replace(".", "_")
    if alt2 in cols:
        return cols[alt2]
    raise ExpressionError(f"signal '{name}' is not in the simulation result")


# ----------------------------------------------------------------------------- the scorer


def score(
    model: SystemModel,
    result_csv: str | Path,
    *,
    reference_csv: str | Path | None = None,
    signal_map: dict[str, str] | None = None,
    router: Any | None = None,
    memory: Any | None = None,
) -> Scorecard:
    """Run every acceptance check, then optionally compare against a supplied reference trace.

    Procedure criteria with no expression yet are formalised first, against these columns
    (see verify/criteria.py); one that cannot be is reported as not machine-checkable.
    """
    cols = read_result(result_csv)
    card = Scorecard()
    from .criteria import formalise

    card.notes = formalise(model, cols, router=router, memory=memory)

    for scenario in model.scenarios:
        for chk in scenario.checks:
            if chk.kind == "procedure" and not chk.expression:
                card.results.append(CheckResult(
                    check_id=chk.id, description=chk.description, passed=False,
                    detail=chk.provenance.note or "not machine-checkable",
                    requirement_ids=chk.requirement_ids, checkable=False,
                ))
                continue
            try:
                ok, detail, observed = evaluate(chk.expression, cols, chk.tolerance)
            except ExpressionError as exc:
                ok, detail, observed = False, str(exc), None
            card.results.append(
                CheckResult(
                    check_id=chk.id,
                    description=chk.description,
                    passed=ok,
                    detail=detail,
                    requirement_ids=chk.requirement_ids,
                    observed=observed,
                    formalised=(chk.kind == "procedure"),
                )
            )

    if reference_csv:
        consistent, notes = screen_reference(reference_csv, model)
        card.reference_consistent = consistent
        card.reference_notes = notes
        if consistent and signal_map:
            card.signal_errors = compare_signals(cols, reference_csv, signal_map)
        elif signal_map:
            card.reference_notes.append(
                "signal-level comparison suppressed: the reference trace failed the "
                "conservation screen, so RMSE against it would not be meaningful"
            )
    return card


def screen_reference(
    path: str | Path, model: SystemModel | None = None
) -> tuple[bool, list[str]]:
    """Check a supplied reference trace for internal physical consistency before trusting it.

    Reference data is evidence like anything else, and it can be wrong. Scoring a model
    against a trace that violates conservation measures nothing but how well we reproduced
    someone's spreadsheet. Each screen below asks a different conservation question; a trace
    only earns a signal-level comparison if every applicable screen passes.

    Screens are opt-in by column naming: a trace with no recognisable speed columns simply
    does not get the rotational screen, and that is reported as "not applicable", never as a
    pass. Returns (trustworthy, notes).
    """
    cols = _load_columns(path)
    if not cols:
        return False, ["reference trace is empty"]

    # Some screens need to know something about the system, not just the numbers. Guessing
    # it from column names is fragile: omc eliminates a constant source torque as a parameter
    # alias, so `M1.tau` never appears in the result and a name-based check concludes there is
    # no constant drive. When the IR is available, ask it.
    facts = _system_facts(model)

    ok = True
    notes: list[str] = []
    applied = 0
    for screen in (_screen_solute, _screen_monotone_spinup, _screen_energy_sign):
        verdict, screen_notes, ran = screen(cols, facts)
        applied += ran
        ok = ok and verdict
        notes.extend(screen_notes)

    if applied == 0:
        notes.append(
            "no screen was applicable to these columns; the trace is neither endorsed nor "
            "rejected, so treat signal-level agreement with caution"
        )
        return True, notes
    if ok:
        notes.append(f"reference trace passed {applied} applicable consistency screen(s)")
    return ok, notes


def _system_facts(model: SystemModel | None) -> dict[str, Any]:
    """What the screens need to know about the system under test.

    `constant_drive` is tri-state on purpose: True means the IR shows a constant source,
    False means it shows a varying one, and None means we do not know and the screen must
    decide for itself whether to run.
    """
    if model is None:
        return {"constant_drive": None}
    sources = [
        b for b in model.blocks
        if b.modelica_class and ".Sources." in b.modelica_class
    ]
    if not sources:
        return {"constant_drive": None}
    constant = all(
        "Constant" in (b.modelica_class or "") or "Fixed" in (b.modelica_class or "")
        for b in sources
    )
    return {"constant_drive": constant}


def _load_columns(path: str | Path) -> dict[str, list[float]]:
    rows = list(csv.DictReader(Path(path).open(newline="", encoding="utf-8")))
    if not rows:
        return {}
    cols: dict[str, list[float]] = {k: [] for k in rows[0]}
    for r in rows:
        for k, v in r.items():
            try:
                cols[k].append(float(v))
            except (TypeError, ValueError):
                cols[k].append(float("nan"))
    return cols


def _pair_columns(cols: dict[str, list[float]], a_pat: str, b_pat: str) -> list[tuple[str, str, str]]:
    """Find (tag, col_a, col_b) triples where both columns belong to the same tag."""
    a_cols = [c for c in cols if re.search(a_pat, c, re.I)]
    b_cols = [c for c in cols if re.search(b_pat, c, re.I)]
    out: list[tuple[str, str, str]] = []
    for a in a_cols:
        tag = re.split(r"[_.]", a)[0]
        b = next((x for x in b_cols if x.startswith(tag)), None)
        if b:
            out.append((tag, a, b))
    return out


# ------------------------------------------------------------------ screen: conserved species


def _screen_solute(cols: dict[str, list[float]], facts: dict[str, Any]) -> tuple[bool, list[str], int]:
    """During a concentration phase, solute inventory must stay put.

    A concentration phase is a run where concentration rises while inventory falls -- solvent
    being removed. An ordinary tank drain also has falling inventory but flat concentration,
    so requiring both conditions avoids that false positive.
    """
    notes: list[str] = []
    ok, ran = True, 0
    for tag, lc, cc in _pair_columns(cols, r"level", r"(_w_|conc|fraction|_x_)"):
        lv, cv = cols[lc], cols[cc]
        window = _concentration_window(lv, cv)
        if window is None:
            continue
        ran += 1
        i0, i1 = window
        start_inv, end_inv = lv[i0] * cv[i0], lv[i1] * cv[i1]
        if start_inv <= 1e-9:
            continue
        change = (end_inv - start_inv) / start_inv
        if abs(change) > 0.05:
            ok = False
            notes.append(
                f"{tag}: during the concentration phase (samples {i0}-{i1}) the solute "
                f"inventory {'gains' if change > 0 else 'loses'} {abs(change):.0%} while "
                f"concentration rises {cv[i0]:.3f} -> {cv[i1]:.3f} and level falls "
                f"{lv[i0]:.3f} -> {lv[i1]:.3f}. Solute is not conserved, so signal-level "
                f"agreement with this trace is not evidence of correctness; score events."
            )
    return ok, notes, ran


def _concentration_window(level: list[float], conc: list[float]) -> tuple[int, int] | None:
    """Longest run where concentration rises and level falls. Returns (start, end) indices."""
    best: tuple[int, int] | None = None
    run_start: int | None = None
    for i in range(1, len(level)):
        if conc[i] > conc[i - 1] + 1e-9 and level[i] < level[i - 1] - 1e-9:
            if run_start is None:
                run_start = i - 1
        else:
            if run_start is not None:
                span = (run_start, i - 1)
                if best is None or (span[1] - span[0]) > (best[1] - best[0]):
                    best = span
                run_start = None
    if run_start is not None:
        span = (run_start, len(level) - 1)
        if best is None or (span[1] - span[0]) > (best[1] - best[0]):
            best = span
    return best if best and best[1] - best[0] >= 5 else None


# ------------------------------------------------------------------ screen: rotational

# Deliberately narrow. An earlier version used `_w_`, which matched `B5_w_NaCl` -- a NaCl
# mass fraction -- and reported a chemical composition as an impossible rotational overshoot.
# A speed column ends in `.w` or `_w`, or says so in words.
_SPEED = r"([._]w$|speed|omega|rpm|angular.?vel)"
_TORQUE = r"([._]tau$|torque|[._]trq)"
#: Columns that look like a speed by name but are something else entirely.
_NOT_SPEED = r"(conc|fraction|_x_|nacl|salt|solute|mass)"


def _is_constant(series: list[float], rel_tol: float = 1e-6) -> bool:
    values = [v for v in series if not math.isnan(v)]
    if not values:
        return False
    spread = max(values) - min(values)
    return spread <= rel_tol * max(abs(max(values, key=abs)), 1.0)


def _screen_monotone_spinup(cols: dict[str, list[float]], facts: dict[str, Any]) -> tuple[bool, list[str], int]:
    """A constant torque into an inertia with linear damping cannot overshoot.

    The response is first order, so speed rises monotonically to its asymptote. An overshoot
    in a supplied trace means either the torque was not constant or the trace is not a
    solution of the system it claims to describe. Only applied when the torque column really
    is constant, so a stepped or reversing drive is left alone.
    """
    notes: list[str] = []
    ok, ran = True, 0
    speeds = [
        c for c in cols
        if re.search(_SPEED, c, re.I) and not re.search(_NOT_SPEED, c, re.I) and c != "time"
    ]
    torques = [c for c in cols if re.search(_TORQUE, c, re.I)]
    if not speeds:
        return True, notes, 0

    # Apply only when a CONSTANT drive exists. Checking one arbitrary torque column is not
    # enough: internal flange torques vary throughout a transient by definition, so picking
    # `torques[0]` skipped the screen on our own drivetrain result. What matters is whether
    # any torque in the trace is constant, i.e. whether there is a constant source at all.
    if facts.get("constant_drive") is False:
        return True, notes, 0
    if facts.get("constant_drive") is None:
        if torques and not any(_is_constant(cols[t]) for t in torques):
            return True, notes, 0

    for name in speeds:
        series = [v for v in cols[name] if not math.isnan(v)]
        if len(series) < 10:
            continue
        ran += 1
        final = series[-1]
        peak = max(series, key=abs)
        if abs(final) < 1e-9:
            continue
        overshoot = (abs(peak) - abs(final)) / abs(final)
        if overshoot > 0.02:
            ok = False
            notes.append(
                f"{name}: peaks at {peak:.4g} then settles at {final:.4g}, a {overshoot:.0%} "
                f"overshoot. A constant torque into an inertia with linear damping is first "
                f"order and cannot overshoot, so this trace is not a solution of the stated "
                f"system."
            )
    return ok, notes, ran


# ------------------------------------------------------------------ screen: energy sign

_TEMP = r"(temp|_T$|_T_|degc|kelvin)"


def _screen_energy_sign(cols: dict[str, list[float]], facts: dict[str, Any]) -> tuple[bool, list[str], int]:
    """A vessel with cooling commanded on must not warm, and vice versa.

    Cheap, and it catches the most common synthesis error in a hand-made trace: a command
    column and the quantity it drives moving in opposite directions.
    """
    notes: list[str] = []
    ok, ran = True, 0
    for tag, tc, cmdc in _pair_columns(cols, _TEMP, r"(cool|chill)"):
        temps, cmds = cols[tc], cols[cmdc]
        active = [
            i for i in range(1, min(len(temps), len(cmds)))
            if cmds[i] > 0.5 and not math.isnan(temps[i]) and not math.isnan(temps[i - 1])
        ]
        if len(active) < 10:
            continue
        ran += 1
        warming = sum(1 for i in active if temps[i] > temps[i - 1] + 1e-6)
        if warming > 0.2 * len(active):
            ok = False
            notes.append(
                f"{tag}: temperature rises in {warming} of {len(active)} samples while the "
                f"cooler is commanded on. Energy is flowing the wrong way."
            )
    return ok, notes, ran


def compare_signals(
    cols: dict[str, list[float]], reference_csv: str | Path, signal_map: dict[str, str]
) -> dict[str, float]:
    """Normalised RMSE per mapped signal. Only meaningful when the reference passed screening."""
    ref = read_result(reference_csv)
    out: dict[str, float] = {}
    ref_t, sim_t = ref.get("time_s") or ref.get("time") or [], cols.get("time") or []
    for sim_name, ref_name in signal_map.items():
        if sim_name not in cols or ref_name not in ref:
            continue
        resampled = [sample_at(sim_t, cols[sim_name], t) for t in ref_t]
        errs = [(a - b) ** 2 for a, b in zip(resampled, ref[ref_name])]
        if not errs:
            continue
        rng = (max(ref[ref_name]) - min(ref[ref_name])) or 1.0
        out[sim_name] = round(math.sqrt(sum(errs) / len(errs)) / rng, 4)
    return out
