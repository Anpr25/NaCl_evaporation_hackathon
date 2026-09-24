"""Inline SVG plots for the report — D5.

Deliberately dependency-free: SVG is written by hand rather than through matplotlib. Three
reasons, in order of how much they matter.

  1. The report has to be **one self-contained file**. Matplotlib would mean either a PNG
     next to the HTML, which gets separated the moment anyone emails it, or a base64 blob
     that bloats the page.
  2. SVG scales and stays readable in both light and dark themes; a rasterised chart does
     not, and the report is read on whatever the judge happens to have open.
  3. Matplotlib on a fresh machine is a 50 MB install and a font cache rebuild that can add
     20 s to the first run. `specalive doctor` should not have to care.

The plots are small multiples: one panel per signal, shared time axis, acceptance thresholds
drawn as reference lines so the reader can see the criterion being met rather than take the
scorecard's word for it.

Owner: D.
"""

from __future__ import annotations

import html
import math
import re
from dataclasses import dataclass, field
from typing import Iterable, Sequence

#: Panel geometry, in user units. The viewBox scales to whatever width the page gives it.
W, H = 460, 150
PAD_L, PAD_R, PAD_T, PAD_B = 52, 12, 22, 28


@dataclass
class Series:
    name: str
    values: list[float]
    #: Horizontal reference lines: (value, label). Used for acceptance thresholds.
    thresholds: list[tuple[float, str]] = field(default_factory=list)
    unit: str | None = None


def _nice_bounds(lo: float, hi: float) -> tuple[float, float]:
    """Round the axis outwards to something a human would have chosen."""
    if not math.isfinite(lo) or not math.isfinite(hi):
        return 0.0, 1.0
    if hi - lo < 1e-12:
        pad = max(abs(hi) * 0.1, 0.5)
        return lo - pad, hi + pad
    span = hi - lo
    step = 10 ** math.floor(math.log10(span / 2))
    for mult in (1, 2, 2.5, 5, 10):
        if span / (step * mult) <= 4:
            step *= mult
            break
    return math.floor(lo / step) * step, math.ceil(hi / step) * step


def _fmt(v: float) -> str:
    if v == 0:
        return "0"
    if abs(v) >= 1000 or abs(v) < 0.01:
        return f"{v:.3g}"
    return f"{v:.4g}".rstrip("0").rstrip(".") or "0"


def _panel(times: Sequence[float], s: Series) -> str:
    finite = [v for v in s.values if math.isfinite(v)]
    if not finite or not times:
        return ""
    lo, hi = _nice_bounds(min(finite + [t for t, _ in s.thresholds]),
                          max(finite + [t for t, _ in s.thresholds]))
    t0, t1 = times[0], times[-1]
    tspan = (t1 - t0) or 1.0
    vspan = (hi - lo) or 1.0

    def px(t: float) -> float:
        return PAD_L + (t - t0) / tspan * (W - PAD_L - PAD_R)

    def py(v: float) -> float:
        return H - PAD_B - (v - lo) / vspan * (H - PAD_T - PAD_B)

    # Downsample: more points than horizontal pixels is wasted bytes, and a 600-point path
    # in a 460-unit panel is indistinguishable from a 400-point one.
    step = max(1, len(times) // 400)
    pts = " ".join(
        f"{px(times[i]):.1f},{py(s.values[i]):.1f}"
        for i in range(0, len(times), step)
        if math.isfinite(s.values[i])
    )

    grid: list[str] = []
    for frac in (0.0, 0.5, 1.0):
        v = lo + frac * vspan
        y = py(v)
        grid.append(
            f'<line class="g" x1="{PAD_L}" y1="{y:.1f}" x2="{W - PAD_R}" y2="{y:.1f}"/>'
            f'<text class="ax" x="{PAD_L - 6}" y="{y + 3.5:.1f}" text-anchor="end">{_fmt(v)}</text>'
        )
    for frac in (0.0, 0.5, 1.0):
        t = t0 + frac * tspan
        grid.append(
            f'<text class="ax" x="{px(t):.1f}" y="{H - 8}" text-anchor="middle">{_fmt(t)}</text>'
        )

    marks: list[str] = []
    for value, label in s.thresholds:
        if not (lo <= value <= hi):
            continue
        y = py(value)
        marks.append(
            f'<line class="th" x1="{PAD_L}" y1="{y:.1f}" x2="{W - PAD_R}" y2="{y:.1f}"/>'
            f'<text class="thl" x="{W - PAD_R - 3}" y="{y - 4:.1f}" text-anchor="end">'
            f"{html.escape(label)}</text>"
        )

    title = html.escape(s.name) + (f"  [{html.escape(s.unit)}]" if s.unit else "")
    return (
        f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{title}">'
        f'<text class="ti" x="{PAD_L}" y="13">{title}</text>'
        f"{''.join(grid)}{''.join(marks)}"
        f'<polyline class="ln" points="{pts}"/>'
        f"</svg>"
    )


PLOT_CSS = """
.plots{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px;margin:1em 0}
.plots svg{width:100%;height:auto;border:1px solid var(--line);border-radius:8px;
background:var(--card,transparent)}
.plots .ln{fill:none;stroke:var(--acc);stroke-width:1.6;stroke-linejoin:round}
.plots .g{stroke:var(--line);stroke-width:1}
.plots .th{stroke:var(--warn);stroke-width:1;stroke-dasharray:4 3}
.plots .ax{fill:var(--mut);font-size:9px;font-family:ui-monospace,monospace}
.plots .ti{fill:var(--fg);font-size:11px;font-weight:600}
.plots .thl{fill:var(--warn);font-size:9px}
"""


def thresholds_from_checks(checks: Iterable, signal: str) -> list[tuple[float, str]]:
    """Pull the numeric thresholds that mention `signal` out of the acceptance expressions.

    Drawing the criterion on the same axes as the signal is the point: the reader sees the
    requirement being met instead of trusting a PASS in a table.
    """
    out: list[tuple[float, str]] = []
    pattern = re.compile(rf"{re.escape(signal)}\s*,\s*([-\d.eE+]+)|{re.escape(signal)}\)?\s*(?:<=|>=|<|>)\s*([-\d.eE+]+)")
    for chk in checks:
        for m in pattern.finditer(getattr(chk, "expression", "")):
            raw = m.group(1) or m.group(2)
            try:
                out.append((float(raw), getattr(chk, "id", "")))
            except (TypeError, ValueError):
                continue
    # De-duplicate on value, keeping the first label.
    seen: dict[float, str] = {}
    for value, label in out:
        seen.setdefault(round(value, 9), label)
    return sorted(seen.items())


def pick_signals(columns: dict[str, list[float]], checks: Iterable, limit: int = 6) -> list[str]:
    """Plot what the acceptance checks actually talk about, then fill up with movers.

    A report that plots six arbitrary variables is decoration. One that plots the variables
    the criteria name is evidence.
    """
    named: list[str] = []
    for chk in checks:
        for token in re.findall(r"[A-Za-z_][\w.]*", getattr(chk, "expression", "")):
            if token in columns and token != "time" and token not in named:
                named.append(token)

    if len(named) < limit:
        def variation(name: str) -> float:
            vals = [v for v in columns[name] if math.isfinite(v)]
            if len(vals) < 2:
                return 0.0
            spread = max(vals) - min(vals)
            return spread / max(abs(max(vals, key=abs)), 1e-9)

        movers = sorted(
            (c for c in columns if _is_reportable(c) and c not in named),
            key=variation,
            reverse=True,
        )
        # Cap the fillers. Panels the criteria never mention are decoration, and two of them
        # is enough context; six turns the section into noise.
        room = min(limit - len(named), 2 if named else limit)
        named.extend(movers[:room])
    return named[:limit]


#: Solver bookkeeping, not physics. Ranking purely by "how much does it move" surfaces
#: derivatives and connector internals -- der(J1.w), J1.a, D1.flange_a.tau -- which tell a
#: reader nothing. A reportable variable is one an engineer would name: <component>.<quantity>.
_NOISE = re.compile(r"^der\(|^\$|\.flange|\.support|\.heatPort|_internal|\.state|\.aux")


def _is_reportable(name: str) -> bool:
    if name == "time" or not _NOISE.search(name) is None:
        return False
    # One dot: a component's own variable. Deeper paths are sub-component internals.
    return name.count(".") == 1 or "_" in name


def render_plots(
    columns: dict[str, list[float]], checks: Iterable = (), limit: int = 6
) -> str:
    """Return a ready-to-embed HTML fragment, or "" when there is nothing worth drawing."""
    times = columns.get("time") or []
    if not times:
        return ""
    checks = list(checks)
    panels = []
    for name in pick_signals(columns, checks, limit):
        panels.append(
            _panel(times, Series(name=name, values=columns[name],
                                 thresholds=thresholds_from_checks(checks, name)))
        )
    panels = [p for p in panels if p]
    if not panels:
        return ""
    return '<div class="plots">' + "".join(panels) + "</div>"
