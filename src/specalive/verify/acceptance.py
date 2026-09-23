"""Score a simulation against the acceptance criteria extracted from the test procedure.

Event checks are primary; signal comparison is secondary and only quoted when the reference
data has been shown to be physically consistent. That ordering is not a convenience -- the
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
        consistent, notes = screen_reference(reference_csv)
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


def screen_reference(path: str | Path) -> tuple[bool, list[str]]:
    """Check a supplied reference trace for internal physical consistency before trusting it.

    The screen looks for a *concentration phase*: a contiguous window where concentration rises
    while inventory falls, i.e. solvent is being removed. Across such a window the solute
    inventory must stay roughly constant. An ordinary tank drain also shows falling inventory
    but with flat concentration, so requiring both conditions avoids the obvious false positive.

    Today this covers conserved species. TODO(D): add charge and energy screens for the
    electrical and drivetrain benches -- the shape of the check is identical.
    """
    notes: list[str] = []
    rows = list(csv.DictReader(Path(path).open(newline="", encoding="utf-8")))
    if not rows:
        return False, ["reference trace is empty"]

    cols: dict[str, list[float]] = {k: [] for k in rows[0]}
    for r in rows:
        for k, v in r.items():
            try:
                cols[k].append(float(v))
            except (TypeError, ValueError):
                cols[k].append(float("nan"))

    level_cols = [c for c in cols if re.search(r"level", c, re.I)]
    conc_cols = [c for c in cols if re.search(r"(_w_|conc|fraction|_x_)", c, re.I)]
    ok = True
    checked = 0

    for lc in level_cols:
        tag = re.split(r"[_.]", lc)[0]
        cc = next((c for c in conc_cols if c.startswith(tag)), None)
        if not cc:
            continue
        lv, cv = cols[lc], cols[cc]
        window = _concentration_window(lv, cv)
        if window is None:
            continue
        i0, i1 = window
        checked += 1
        start_inv, end_inv = lv[i0] * cv[i0], lv[i1] * cv[i1]
        if start_inv <= 1e-9:
            continue
        change = (end_inv - start_inv) / start_inv
        if abs(change) > 0.05:
            ok = False
            direction = "gains" if change > 0 else "loses"
            notes.append(
                f"{tag}: during the concentration phase (samples {i0}-{i1}) the solute "
                f"inventory {direction} {abs(change):.0%} while concentration rises "
                f"{cv[i0]:.3f} -> {cv[i1]:.3f} and level falls {lv[i0]:.3f} -> {lv[i1]:.3f}. "
                f"Solute is not conserved, so signal-level agreement with this trace is not "
                f"evidence of correctness; score against events instead."
            )
    if checked == 0:
        notes.append("no concentration phase found; conservation screen not applicable")
        return True, notes
    if ok:
        notes.append(f"reference trace passed the conserved-species screen ({checked} vessel(s))")
    return ok, notes


def _concentration_window(level: list[float], conc: list[float]) -> tuple[int, int] | None:
    """Longest run where concentration rises and level falls. Returns (start, end) indices."""
    best: tuple[int, int] | None = None
    run_start: int | None = None
    for i in range(1, len(level)):
        rising_conc = conc[i] > conc[i - 1] + 1e-9
        falling_level = level[i] < level[i - 1] - 1e-9
        if rising_conc and falling_level:
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
    if best is None or best[1] - best[0] < 5:
        return None
    return best


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
