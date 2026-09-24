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

    def icon(self) -> str:
        return "PASS" if self.passed else "FAIL"


@dataclass
class Scorecard:
    results: list[CheckResult] = field(default_factory=list)
    reference_consistent: bool | None = None
    reference_notes: list[str] = field(default_factory=list)
    signal_errors: dict[str, float] = field(default_factory=dict)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def ok(self) -> bool:
        return self.total > 0 and self.passed == self.total

    def summary(self) -> str:
        return f"{self.passed}/{self.total} acceptance checks passed"


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

_OPS = {
    "<=": lambda a, b: a <= b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    ">": lambda a, b: a > b,
    "==": lambda a, b: abs(a - b) < 1e-9,
    "!=": lambda a, b: abs(a - b) >= 1e-9,
}


class ExpressionError(ValueError):
    pass


def evaluate(expr: str, cols: dict[str, list[float]], tolerance: float | None = None) -> tuple[bool, str, Any]:
    """Evaluate one acceptance expression. Returns (passed, human detail, observed value)."""
    expr = expr.strip()
    times = cols.get("time") or []

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
) -> Scorecard:
    """Run every acceptance check, then optionally compare against a supplied reference trace."""
    cols = read_result(result_csv)
    card = Scorecard()

    for scenario in model.scenarios:
        for chk in scenario.checks:
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
