"""OpenModelica driver: check, compile, simulate, and parse diagnostics into structured form.

This module owns the hard gate. Everything it returns is designed to be fed straight back into
the repair loop, so diagnostics are parsed into objects with file/line/kind rather than left as
a wall of text a language model has to squint at.

Owner: C.
"""

from __future__ import annotations

import csv
import os
import platform
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal

DiagKind = Literal[
    "syntax",
    "unbalanced_connector",
    "missing_inner",
    "undeclared",
    "type_mismatch",
    "connect_mismatch",
    "singular",
    "unbalanced_system",
    "discrete_loop",
    "initialization",
    "unit",
    "build",
    "runtime",
    "other",
]


@dataclass
class Diagnostic:
    kind: DiagKind
    message: str
    file: str | None = None
    line: int | None = None
    column: int | None = None
    symbols: list[str] = field(default_factory=list)
    raw: str = ""

    def locate(self) -> str:
        return f"{self.file}:{self.line}" if self.file and self.line else "(no location)"


@dataclass
class OmcResult:
    ok: bool
    stage: Literal["load", "check", "build", "simulate"]
    diagnostics: list[Diagnostic] = field(default_factory=list)
    stdout: str = ""
    result_file: Path | None = None
    equation_count: int | None = None
    variable_count: int | None = None
    timings: dict[str, float] = field(default_factory=dict)

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.kind != "other" or "Error" in d.raw]

    def summary(self) -> str:
        if self.ok:
            extra = f" ({self.equation_count} eq / {self.variable_count} var)" if self.equation_count else ""
            return f"{self.stage}: OK{extra}"
        first = self.diagnostics[0].message if self.diagnostics else "unknown failure"
        return f"{self.stage}: FAILED -- {first}"


# --------------------------------------------------------------------------- locating omc

_WINDOWS_HINTS = (
    r"C:\Program Files\OpenModelica*\bin\omc.exe",
    r"C:\OpenModelica*\bin\omc.exe",
)


def find_omc(explicit: str | None = None) -> str:
    """Locate the compiler. Checks an explicit path, then $OPENMODELICAHOME, PATH, then guesses."""
    if explicit:
        return explicit
    env = os.getenv("SPECALIVE_OMC") or os.getenv("OMC_PATH")
    if env and Path(env).exists():
        return env
    home = os.getenv("OPENMODELICAHOME")
    if home:
        cand = Path(home) / "bin" / ("omc.exe" if platform.system() == "Windows" else "omc")
        if cand.exists():
            return str(cand)
    which = shutil.which("omc")
    if which:
        return which
    if platform.system() == "Windows":
        import glob

        for pattern in _WINDOWS_HINTS:
            matches = sorted(glob.glob(pattern), reverse=True)
            if matches:
                return matches[0]
    raise FileNotFoundError(
        "OpenModelica compiler not found. Install it, or set SPECALIVE_OMC to the omc executable."
    )


# --------------------------------------------------------------------------- diagnostics

_PATTERNS: tuple[tuple[DiagKind, re.Pattern[str]], ...] = (
    ("unbalanced_connector", re.compile(r"connector .* is not balanced", re.I)),
    ("missing_inner", re.compile(r"no 'inner' declaration|missing inner declaration", re.I)),
    ("undeclared", re.compile(r"(?:Variable|Class|Component) (\S+) not found", re.I)),
    ("connect_mismatch", re.compile(r"connect\(.*\).*(?:incompatible|mismatch|different)", re.I)),
    ("type_mismatch", re.compile(r"type mismatch|expected type|cannot be converted", re.I)),
    ("discrete_loop", re.compile(r"[Pp]urely discrete algebraic loops", re.I)),
    ("singular", re.compile(r"structurally singular|singular system", re.I)),
    ("unbalanced_system", re.compile(r"has (\d+) equation\(s\) and (\d+) variable\(s\)", re.I)),
    ("initialization", re.compile(r"initialization .*(failed|problem)|too many initial", re.I)),
    ("unit", re.compile(r"[Uu]nit .*(inconsistent|mismatch)", re.I)),
    ("syntax", re.compile(r"Parse error|syntax error|unexpected token", re.I)),
    ("build", re.compile(r"Failed to build model", re.I)),
    ("runtime", re.compile(r"Simulation (?:execution )?failed|solver failed|nonlinear system.*fail", re.I)),
)

_LOCATION = re.compile(r"\[?([A-Za-z]:[^:\]]+|/[^:\]]+):(\d+):(\d+)")
_SYMBOL_LINE = re.compile(r"^\s*([A-Za-z_][\w.\[\]]*)\s*$")


def parse_diagnostics(text: str) -> list[Diagnostic]:
    """Turn omc's output into structured findings the repair loop can act on."""
    out: list[Diagnostic] = []
    blocks = re.split(r"\n(?=(?:\[[^\]]+\]\s*)?(?:Error|Warning|Notification):)", text)
    for block in blocks:
        if "Error" not in block and "error" not in block:
            continue
        if "Notification:" in block and "Error" not in block:
            continue
        kind: DiagKind = "other"
        for k, pat in _PATTERNS:
            if pat.search(block):
                kind = k
                break
        loc = _LOCATION.search(block)
        symbols = [
            m.group(1)
            for m in (_SYMBOL_LINE.match(ln) for ln in block.splitlines())
            if m and "." in m.group(1)
        ]
        message = next(
            (ln.strip() for ln in block.splitlines() if "Error" in ln or "error" in ln), block[:200]
        )
        out.append(
            Diagnostic(
                kind=kind,
                message=message.strip(),
                file=loc.group(1) if loc else None,
                line=int(loc.group(2)) if loc else None,
                column=int(loc.group(3)) if loc else None,
                symbols=symbols[:20],
                raw=block.strip()[:4000],
            )
        )
    return out


# ------------------------------------------------------------------------------ the driver


class OmcRunner:
    """Stateless wrapper around `omc <script.mos>`.

    Scripted omc is used rather than OMPython on purpose: no extra dependency, no daemon to
    keep alive, identical behaviour on every machine, and the .mos file we ran is itself an
    artefact we can ship for reproducibility.
    """

    def __init__(self, omc: str | None = None, workdir: str | Path = "out/work") -> None:
        self.omc = find_omc(omc)
        self.workdir = Path(workdir)
        self.workdir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ low level
    def _script(self, body: str, timeout: int) -> str:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".mos", delete=False, dir=str(self.workdir), encoding="utf-8"
        ) as fh:
            fh.write(body)
            path = fh.name
        try:
            proc = subprocess.run(
                [self.omc, path],
                capture_output=True,
                text=True,
                cwd=str(self.workdir),
                timeout=timeout,
            )
            return proc.stdout + ("\n" + proc.stderr if proc.stderr else "")
        except subprocess.TimeoutExpired:
            return f"Error: omc timed out after {timeout}s"
        finally:
            Path(path).unlink(missing_ok=True)

    @staticmethod
    def _loads(files: Iterable[str | Path], libraries: Iterable[str]) -> str:
        lines = [f"loadModel({lib}); getErrorString();" for lib in libraries]
        lines += [f'loadFile("{Path(f).resolve().as_posix()}"); getErrorString();' for f in files]
        return "\n".join(lines)

    # ------------------------------------------------------------------ public API
    def check(
        self,
        model: str,
        files: Iterable[str | Path],
        libraries: Iterable[str] = ("Modelica",),
        timeout: int = 180,
    ) -> OmcResult:
        """Front-end check only: fast, and catches most structural defects before a C compile."""
        out = self._script(
            f"{self._loads(files, libraries)}\ncheckModel({model});\ngetErrorString();\n", timeout
        )
        ok = f"Check of {model} completed successfully" in out
        counts = re.search(r"has (\d+) equation\(s\) and (\d+) variable\(s\)", out)
        return OmcResult(
            ok=ok,
            stage="check",
            diagnostics=[] if ok else parse_diagnostics(out),
            stdout=out,
            equation_count=int(counts.group(1)) if counts else None,
            variable_count=int(counts.group(2)) if counts else None,
        )

    def simulate(
        self,
        model: str,
        files: Iterable[str | Path],
        *,
        libraries: Iterable[str] = ("Modelica",),
        stop_time: float = 1.0,
        interval: float | None = None,
        tolerance: float = 1e-6,
        solver: str = "dassl",
        prefix: str = "specalive",
        timeout: int = 900,
    ) -> OmcResult:
        """Build and run. This is the hard gate: it must return ok=True for a valid submission."""
        n = int(stop_time / interval) if interval else 500
        body = (
            f"{self._loads(files, libraries)}\n"
            f"simulate({model}, stopTime={stop_time}, numberOfIntervals={n}, "
            f'tolerance={tolerance}, method="{solver}", outputFormat="csv", '
            f'fileNamePrefix="{prefix}");\n'
            "getErrorString();\n"
        )
        out = self._script(body, timeout)
        ok = "The simulation finished successfully" in out
        result_file = self.workdir / f"{prefix}_res.csv"
        timings = {
            m.group(1): float(m.group(2))
            for m in re.finditer(r"time(\w+) = ([0-9.eE+-]+)", out)
        }
        return OmcResult(
            ok=ok,
            stage="simulate" if "Failed to build model" not in out else "build",
            diagnostics=[] if ok else parse_diagnostics(out),
            stdout=out,
            result_file=result_file if ok and result_file.exists() else None,
            timings=timings,
        )

    def version(self) -> str:
        proc = subprocess.run([self.omc, "--version"], capture_output=True, text=True, timeout=30)
        return proc.stdout.strip()


# ------------------------------------------------------------------------------ result I/O


@dataclass
class Liveness:
    """C10. Did the simulation actually do anything?

    `compiles` and `simulates` are the hard gate and they are necessary, but they are not
    sufficient, and the difference bit us: on a packet run without a reference IR the model
    compiled, simulated to completion and scored **0/10** on acceptance, because extraction
    had missed the heater and cooler commands. No heater command means no evaporation, so
    every threshold check fails -- while the run itself reports success.

    A model that integrates a system in which nothing moves is not a working model, and
    printing "HARD GATE MET" above "0/10" is the one place this repo reads as a silent pass.
    So the gate reports three states rather than two, and this is the third.

    Deterministic and domain-general: it asks whether state changed and whether any
    controller left its initial state. It makes no assumption about what the system *is*.
    """

    moved: int
    total: int
    #: Controller region -> highest state index reached. Empty when the model has no FSM,
    #: which is normal: the drivetrain bench is purely continuous.
    regions: dict[str, float] = field(default_factory=dict)
    #: Region -> highest state index that exists, from the IR. Without it we can only tell
    #: that a controller moved, not that it finished -- and "moved" is too weak a test: the
    #: failing NaCl run reached Step1 of 8 and stopped, which passes any did-anything check.
    expected: dict[str, int] = field(default_factory=dict)
    reason: str = ""

    @property
    def stalled(self) -> list[str]:
        """Regions that started their sequence and did not finish it."""
        return sorted(
            r for r, top in self.expected.items() if self.regions.get(r, -1) < top
        )

    @property
    def ok(self) -> bool:
        if self.moved == 0:
            return False
        if self.regions and max(self.regions.values(), default=0) <= 0:
            return False
        # The discriminating case. A batch controller that reaches Step1 of 8 and stops has
        # not run the process, however much continuous state drifted underneath it.
        if self.stalled:
            return False
        return True

    def summary(self) -> str:
        if self.total == 0:
            return "no result data to screen"
        pct = 100 * self.moved // max(self.total, 1)
        head = f"{self.moved}/{self.total} variables moved ({pct}%)"
        if self.regions:
            head += ", controller " + ", ".join(
                f"{r}={int(self.regions.get(r, -1))}/{self.expected.get(r, '?')}"
                for r in sorted(set(self.regions) | set(self.expected))
            )
        return head + (f" -- {self.reason}" if self.reason and not self.ok else "")


_STATE_COL = re.compile(r"(?:^|\.)s_(\w+)$")


def liveness(path: str | Path, model: Any = None, *, rel_tol: float = 1e-6) -> Liveness:
    """Screen a result file for movement and sequence completion.

    Streams the file: result CSVs run to hundreds of megabytes. `model` is a SystemModel;
    without it the sequence-completion test is skipped and only movement is checked.
    """
    p = Path(path)
    if not p.exists():
        return Liveness(0, 0, reason="no result file")

    expected: dict[str, int] = {}
    for sm in getattr(model, "state_machines", []) or []:
        for region in sm.regions:
            n = len(sm.states_in(region))
            if n > 1:
                expected[_ident_region(region)] = n - 1

    with p.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if not header:
            return Liveness(0, 0, reason="empty result file")
        idx = [i for i, name in enumerate(header) if name != "time"]
        lo = [float("inf")] * len(header)
        hi = [float("-inf")] * len(header)
        rows = 0
        for row in reader:
            rows += 1
            for i in idx:
                try:
                    v = float(row[i])
                except (ValueError, IndexError):
                    continue
                if v < lo[i]:
                    lo[i] = v
                if v > hi[i]:
                    hi[i] = v

    if rows < 2:
        return Liveness(0, 0, reason="result file has no trajectory")

    moved = 0
    regions: dict[str, float] = {}
    for i in idx:
        if hi[i] < lo[i]:
            continue
        span = hi[i] - lo[i]
        scale = max(abs(hi[i]), abs(lo[i]), 1e-12)
        if span / scale > rel_tol and span > 0:
            moved += 1
        if m := _STATE_COL.search(header[i]):
            regions[m.group(1)] = max(regions.get(m.group(1), 0.0), hi[i])

    live = Liveness(moved, len(idx), regions, expected)
    if moved == 0:
        live.reason = "nothing changed over the whole run"
    elif regions and max(regions.values(), default=0) <= 0:
        live.reason = "the controller never left its initial state, so no sequence ran"
    elif live.stalled:
        detail = ", ".join(
            f"{r} stopped at {int(regions.get(r, -1))} of {expected[r]}" for r in live.stalled
        )
        live.reason = f"the controller did not finish its sequence ({detail})"
    return live


def _ident_region(raw: str) -> str:
    """Region name as the Modelica emitter writes it into `s_<region>`."""
    out = re.sub(r"[^A-Za-z0-9_]", "_", raw.strip())
    return out if out and not out[0].isdigit() else f"m_{out}"


def read_result(path: str | Path, variables: list[str] | None = None) -> dict[str, list[float]]:
    """Read an omc CSV result into columns. Keeps only `variables` when given, to bound memory."""
    cols: dict[str, list[float]] = {}
    with Path(path).open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        wanted = variables or (reader.fieldnames or [])
        for name in wanted:
            cols[name] = []
        for row in reader:
            for name in wanted:
                raw = row.get(name)
                if raw is None:
                    continue
                try:
                    cols[name].append(float(raw))
                except ValueError:
                    cols[name].append(float("nan"))
    return cols


def sample_at(times: list[float], values: list[float], t: float) -> float:
    """Value at time t with linear interpolation. Used by acceptance checks."""
    if not times:
        return float("nan")
    if t <= times[0]:
        return values[0]
    if t >= times[-1]:
        return values[-1]
    for i in range(1, len(times)):
        if times[i] >= t:
            t0, t1 = times[i - 1], times[i]
            v0, v1 = values[i - 1], values[i]
            span = (t1 - t0) or 1.0
            return v0 + (v1 - v0) * (t - t0) / span
    return values[-1]


def crossing_time(times: list[float], values: list[float], threshold: float, rising: bool = True) -> float | None:
    """First time `values` crosses `threshold`. The backbone of event-level acceptance checks."""
    for i in range(1, len(values)):
        a, b = values[i - 1], values[i]
        if rising and a < threshold <= b:
            return times[i]
        if not rising and a > threshold >= b:
            return times[i]
    return None


def describe_environment(omc: str | None = None) -> dict[str, Any]:
    """Recorded in every report so a reviewer can reproduce the run exactly."""
    try:
        runner = OmcRunner(omc)
        return {"omc_path": runner.omc, "omc_version": runner.version(), "platform": platform.platform()}
    except FileNotFoundError as exc:
        return {"omc_path": None, "omc_version": None, "error": str(exc), "platform": platform.platform()}
