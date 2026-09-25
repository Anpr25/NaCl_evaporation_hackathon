"""C-AI-5. Break a working model in known ways, then measure what the repair loop recovers.

Why this exists. A packet that happens to compile exercises none of the repair code, so the
fallback is untested, and an untested fallback is not a fallback. Fault injection makes the
failure paths run on demand, and it turns "we have AI repair" into two numbers:

    deterministic only :  n/N recovered
    with the agent     :  m/N recovered,  the rest declared as gaps

Each fault is a real defect we have either hit in this repo or proved is reachable, not a
synthetic mutation. Several deliberately pass `omc checkModel` and fail later, because that
is the gap C-AI-1 exists to close.

Run:  specalive faults out/nacl/GeneratedPlant.mo --model GeneratedPlant.BAT09
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

#: (source) -> mutated source, or None when the pattern is absent from this model.
Mutator = Callable[[str], str | None]


@dataclass(frozen=True)
class Fault:
    id: str
    description: str
    #: Where it surfaces: "check" (omc checkModel catches it) or "build" (it passes check
    #: and dies later). The "build" ones are invisible to a repair loop gated on check.
    surfaces_at: str
    #: Whether a deterministic fixer should handle it without any model call.
    deterministic_expected: bool
    apply: Mutator


def _sub_once(pattern: str, repl: str, flags: int = 0) -> Mutator:
    def go(src: str) -> str | None:
        new, n = re.subn(pattern, repl, src, count=1, flags=flags)
        return new if n else None

    return go


def _drop_line(pattern: str) -> Mutator:
    def go(src: str) -> str | None:
        lines = src.splitlines()
        for i, ln in enumerate(lines):
            if re.search(pattern, ln):
                return "\n".join(lines[:i] + lines[i + 1 :]) + "\n"
        return None

    return go


FAULTS: tuple[Fault, ...] = (
    Fault(
        # Applies only to acausal Modelica.Fluid models, so it reports n/a on our Tier-1
        # causal ones. Kept because it is the first thing that breaks in a Tier-2 (C6) model
        # and because a fault that honestly says "not applicable here" is better than one
        # tuned until it always fires.
        "F01-missing-inner",
        "`inner Modelica.Fluid.System system` removed; every outer reference dangles.",
        "check", True,
        _drop_line(r"^\s*inner\s"),
    ),
    Fault(
        "F09-dropped-connection",
        "A connect() is deleted: the model still compiles but a stream goes nowhere.",
        "check", False,
        _drop_line(r"^\s*connect\("),
    ),
    Fault(
        "F02-renamed-connector",
        "A connect() references a connector the class does not declare.",
        "check", False,
        _sub_once(r"(connect\(\s*\w+\.)(\w+)", r"\1nonexistent_port"),
    ),
    Fault(
        "F03-undeclared-symbol",
        "A parameter reference is misspelled by one character -- a typo, not a design gap.",
        "check", True,
        _sub_once(r"\bSP_(\w+)\b", r"SP_\1X"),
    ),
    Fault(
        "F04-partial-type",
        "A component bound to a partial class. Passes checkModel, dies at build (C-07).",
        "build", True,
        _sub_once(
            r"^(\s*)([\w.]+\s+\w+\s*\([^)]*\)\s*\"[^\"]*\";)$",
            r"\1Modelica.Thermal.HeatTransfer.Interfaces.Element1D injected_partial;\n\1\2",
            re.M,
        ),
    ),
    Fault(
        "F05-discrete-loop",
        "An actuator equation folded back into the scan, closing a discrete algebraic loop.",
        "check", True,
        _sub_once(r"\bpre\((s_\w+)\)", r"\1"),
    ),
    Fault(
        "F06-dropped-semicolon",
        "A syntax error: one statement loses its terminator.",
        "check", False,
        _sub_once(r"^(\s*parameter Real \w+ = [\d.]+[^;\n]*);$", r"\1", re.M),
    ),
    Fault(
        "F07-unknown-class",
        "A component bound to a class that does not exist in any loaded library.",
        "check", False,
        _sub_once(r"^(\s*)SpecAlive\.Vessels\.Reservoir\b", r"\1SpecAlive.Vessels.Resevoir", re.M),
    ),
    Fault(
        "F08-wrong-parameter",
        "A modifier names a parameter the bound class does not have.",
        "check", False,
        _sub_once(r"\(area = ", r"(surfaceArea = "),
    ),
)


def inject(source: str, fault: Fault) -> str | None:
    """Apply one fault, or None if this model has nothing to break that way."""
    try:
        return fault.apply(source)
    except Exception:
        return None
