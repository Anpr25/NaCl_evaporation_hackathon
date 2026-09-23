"""The compile-repair loop.

Premise: most Modelica errors are mechanical, and mechanical errors should be fixed by code,
not by tokens. Only genuinely semantic failures reach a model, and when they do they get a
precise diagnostic, a narrow source window and an instruction to return a minimal diff.

That split is what makes free/local models sufficient here. A 3B cannot write a plant. Given
"line 214 references SP_B7_COOl which is not declared; here are the 30 surrounding lines", it
can return a one-line patch, and so can a free 70B, reliably.

Two invariants:
  * keep-best-so-far -- a repair that increases the error count is discarded, never applied;
  * bounded -- the loop stops and declares a gap rather than burning quota forever.

Owner: C, with D owning the router calls.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..verify.omc import Diagnostic, OmcResult, OmcRunner

# --------------------------------------------------------------------- deterministic fixes

Fixer = Callable[[str, Diagnostic], tuple[str, str] | None]
"""Takes (source, diagnostic) and returns (new_source, description) or None if not applicable."""


def fix_discrete_loop(src: str, diag: Diagnostic) -> tuple[str, str] | None:
    """Purely discrete algebraic loop: read region states through `pre()` inside the scan.

    This is the single most common failure in a generated FSM. omc's alias elimination rewrites
    `s == 1` into whichever output equals it, closing a cycle. `pre()` breaks it and is also
    the semantically correct thing for a scan-cycle controller.
    """
    if diag.kind != "discrete_loop":
        return None
    match = re.search(r"when sample\(.*?\) then(.*?)end when;", src, re.S)
    if not match:
        return None
    body = match.group(1)
    states = set(re.findall(r"^\s*(\w+)\s*:=", body, re.M))
    if not states:
        return None
    patched = body
    for name in states:
        patched = re.sub(rf"\b{re.escape(name)}\b(?!\s*:=)", f"pre({name})", patched)
    patched = patched.replace("pre(pre(", "pre((")
    if patched == body:
        return None
    return src.replace(body, patched, 1), f"read {', '.join(sorted(states))} via pre() inside the scan"


def fix_missing_inner(src: str, diag: Diagnostic) -> tuple[str, str] | None:
    """A component wants an `inner` that the enclosing model does not declare."""
    if diag.kind != "missing_inner":
        return None
    m = re.search(r"'?(\w+(?:\.\w+)*)'? *\.?(\w+)?", diag.message)
    known = {
        "world": "inner Modelica.Mechanics.MultiBody.World world;",
        "system": "inner Modelica.Fluid.System system;",
        "stateGraphRoot": "inner Modelica.StateGraph.StateGraphRoot stateGraphRoot;",
    }
    for key, decl in known.items():
        if key.lower() in diag.raw.lower():
            anchor = re.search(r"^(\s*)model\s+\w+.*$", src, re.M)
            if not anchor:
                return None
            insert_at = anchor.end()
            pad = anchor.group(1) + "  "
            return src[:insert_at] + f"\n{pad}{decl}" + src[insert_at:], f"added {decl.strip()}"
    return None


def fix_unbalanced_system(src: str, diag: Diagnostic) -> tuple[str, str] | None:
    """Over-determined by exactly the initial equations we added: drop redundant `fixed = true`.

    Conservative on purpose: only acts when the counts differ by a small amount and there are
    at least that many explicit `fixed = true` starts to relax.
    """
    m = re.search(r"has (\d+) equation\(s\) and (\d+) variable\(s\)", diag.raw)
    if not m:
        return None
    eqs, vars_ = int(m.group(1)), int(m.group(2))
    excess = eqs - vars_
    if not 0 < excess <= 3:
        return None
    fixed = list(re.finditer(r",\s*fixed\s*=\s*true", src))
    if len(fixed) < excess:
        return None
    out = src
    for hit in reversed(fixed[-excess:]):
        out = out[: hit.start()] + out[hit.end() :]
    return out, f"relaxed {excess} redundant 'fixed = true' initialisation(s)"


def fix_unit_annotation(src: str, diag: Diagnostic) -> tuple[str, str] | None:
    """Unit inconsistency on a literal: quantity types are stricter than plain Real."""
    if diag.kind != "unit":
        return None
    m = re.search(r"\b(\w+)\b", diag.message)
    if not m:
        return None
    name = m.group(1)
    pattern = rf"(\bModelica\.Units\.SI\.\w+\s+{re.escape(name)}\b)"
    if not re.search(pattern, src):
        return None
    return re.sub(pattern, f"Real {name}", src, count=1), f"relaxed '{name}' to Real to clear a unit clash"


def fix_undeclared_typo(src: str, diag: Diagnostic) -> tuple[str, str] | None:
    """An undeclared symbol that is one edit away from a declared one is a typo, not a design gap."""
    if diag.kind != "undeclared":
        return None
    m = re.search(r"(?:Variable|Class|Component) (\S+) not found", diag.message)
    if not m:
        return None
    missing = m.group(1).strip("'\" ")
    declared = set(re.findall(r"\b(?:Real|Integer|Boolean|parameter Real)\s+(\w+)", src))
    declared |= set(re.findall(r"^\s*(?:input|output)\s+\w+\s+(\w+)", src, re.M))
    close = difflib.get_close_matches(missing.split(".")[-1], sorted(declared), n=1, cutoff=0.85)
    if not close:
        return None
    return (
        re.sub(rf"\b{re.escape(missing)}\b", close[0], src),
        f"corrected '{missing}' to '{close[0]}' (single-edit typo)",
    )


DETERMINISTIC_FIXERS: tuple[Fixer, ...] = (
    fix_discrete_loop,
    fix_missing_inner,
    fix_undeclared_typo,
    fix_unbalanced_system,
    fix_unit_annotation,
)


# ----------------------------------------------------------------------------- model repair

REPAIR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["replacements", "explanation"],
    "properties": {
        "replacements": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["find", "replace"],
                "properties": {"find": {"type": "string"}, "replace": {"type": "string"}},
            },
        },
        "explanation": {"type": "string"},
    },
}

REPAIR_PROMPT = """\
An OpenModelica compilation failed. Produce the smallest possible edit that fixes it.

DIAGNOSTIC
  kind:     {kind}
  location: {location}
  message:  {message}

RAW COMPILER OUTPUT
{raw}

SOURCE WINDOW (lines {start}-{end} of {path})
{window}

{catalog_note}

Rules:
- Return replacements as exact substrings of the source window. Each `find` must appear
  verbatim, exactly once, inside the window shown above.
- Change as little as possible. Do not reformat, rename or restructure anything unrelated.
- Do not invent Modelica classes, parameters or connectors. If the fix needs a class you were
  not shown, say so in `explanation` and return an empty `replacements` list.
- Answer JSON only.
"""


@dataclass
class RepairStep:
    iteration: int
    kind: str
    method: str
    description: str
    errors_before: int
    errors_after: int
    accepted: bool


@dataclass
class RepairOutcome:
    ok: bool
    source: str
    iterations: int
    steps: list[RepairStep] = field(default_factory=list)
    final: OmcResult | None = None

    def summary(self) -> str:
        det = sum(1 for s in self.steps if s.method == "deterministic" and s.accepted)
        llm = sum(1 for s in self.steps if s.method == "model" and s.accepted)
        return (
            f"{'repaired' if self.ok else 'unrepaired'} after {self.iterations} iteration(s): "
            f"{det} deterministic fix(es), {llm} model-authored fix(es)"
        )


class RepairLoop:
    def __init__(
        self,
        runner: OmcRunner,
        router: Any | None = None,
        *,
        max_iterations: int = 6,
        window: int = 15,
    ) -> None:
        self.runner = runner
        self.router = router
        self.max_iterations = max_iterations
        self.window = window

    def run(
        self,
        model_name: str,
        target: str | Path,
        support_files: list[str | Path],
        *,
        stop_time: float | None = None,
        catalog_note: str = "",
    ) -> RepairOutcome:
        """Iterate until the model checks (and optionally simulates), or the budget runs out."""
        target = Path(target)
        source = target.read_text(encoding="utf-8")
        best_source, best_errors = source, None
        steps: list[RepairStep] = []
        last: OmcResult | None = None

        for it in range(self.max_iterations + 1):
            target.write_text(source, encoding="utf-8")
            files = [target, *support_files]
            last = self.runner.check(model_name, files)
            if last.ok and stop_time:
                last = self.runner.simulate(model_name, files, stop_time=stop_time)
            n_errors = 0 if last.ok else max(len(last.diagnostics), 1)

            if best_errors is None or n_errors < best_errors:
                best_source, best_errors = source, n_errors
            if last.ok:
                return RepairOutcome(True, source, it, steps, last)
            if it == self.max_iterations:
                break

            diag = _most_actionable(last.diagnostics)
            if diag is None:
                break

            patched, method, desc = self._attempt(source, diag, target, catalog_note)
            if patched is None or patched == source:
                steps.append(RepairStep(it, diag.kind, method, desc or "no fix found", n_errors, n_errors, False))
                break

            # Evaluate the candidate before committing to it.
            target.write_text(patched, encoding="utf-8")
            probe = self.runner.check(model_name, files)
            after = 0 if probe.ok else max(len(probe.diagnostics), 1)
            accepted = after < n_errors or probe.ok
            steps.append(RepairStep(it, diag.kind, method, desc or "", n_errors, after, accepted))
            if accepted:
                source = patched
            else:
                # Regression: roll back and stop rather than thrash.
                target.write_text(source, encoding="utf-8")
                break

        target.write_text(best_source, encoding="utf-8")
        return RepairOutcome(False, best_source, len(steps), steps, last)

    # ------------------------------------------------------------------ one repair attempt
    def _attempt(
        self, source: str, diag: Diagnostic, path: Path, catalog_note: str
    ) -> tuple[str | None, str, str]:
        for fixer in DETERMINISTIC_FIXERS:
            try:
                result = fixer(source, diag)
            except Exception:
                continue
            if result is not None:
                return result[0], "deterministic", result[1]

        if self.router is None:
            return None, "deterministic", "no deterministic fixer matched and no router configured"

        lines = source.splitlines()
        centre = (diag.line or len(lines) // 2) - 1
        start = max(0, centre - self.window)
        end = min(len(lines), centre + self.window)
        window = "\n".join(f"{i + 1:5d}| {lines[i]}" for i in range(start, end))
        prompt = REPAIR_PROMPT.format(
            kind=diag.kind,
            location=diag.locate(),
            message=diag.message,
            raw=diag.raw[:1500],
            start=start + 1,
            end=end,
            path=path.name,
            window=window,
            catalog_note=catalog_note or "(no catalog context supplied)",
        )
        window_text = "\n".join(lines[start:end])

        def validate(data: Any) -> tuple[bool, str]:
            reps = data.get("replacements") or []
            for r in reps:
                if window_text.count(r["find"]) != 1:
                    return False, f"'find' text does not occur exactly once in the window: {r['find'][:60]!r}"
            return True, ""

        try:
            resp = self.router.run("repair_modelica", prompt, schema=REPAIR_SCHEMA, validator=validate)
        except Exception as exc:
            return None, "model", f"router failed: {exc}"

        data = resp.data or {}
        reps = data.get("replacements") or []
        if not reps:
            return None, "model", data.get("explanation", "model declined to patch")[:200]
        patched = source
        for r in reps:
            patched = patched.replace(r["find"], r["replace"], 1)
        return patched, "model", data.get("explanation", "")[:200]


#: Fix the errors most likely to be causing the others first.
_PRIORITY = (
    "syntax",
    "undeclared",
    "type_mismatch",
    "connect_mismatch",
    "unbalanced_connector",
    "missing_inner",
    "discrete_loop",
    "unbalanced_system",
    "singular",
    "initialization",
    "unit",
    "build",
    "runtime",
    "other",
)


def _most_actionable(diags: list[Diagnostic]) -> Diagnostic | None:
    if not diags:
        return None
    return sorted(diags, key=lambda d: _PRIORITY.index(d.kind) if d.kind in _PRIORITY else 99)[0]
