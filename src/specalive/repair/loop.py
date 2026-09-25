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
from typing import Any, Callable, Iterable

from ..verify.omc import Diagnostic, OmcResult, OmcRunner
from .writeback import IREdit

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


def fix_partial_type_binding(src: str, diag: Diagnostic) -> tuple[str, str] | None:
    """C-AI-1. A partial class cannot be instantiated -- and `checkModel` does not say so.

    This is the failure C-07 documented: `checkModel` reports success (the equation/variable
    counts come back unbalanced, but that is not an error) and the build then dies with
    `Component 'x' has partial type 'Y'`. Because the repair loop used to gate on check alone,
    the whole family escaped repair and surfaced at simulate.

    There is no local edit that makes a partial class instantiable, so the honest repair is to
    comment the component out and leave a GAP marker the report picks up, rather than invent a
    substitute class the evidence never named.
    """
    if diag.kind not in ("build", "type_mismatch", "other"):
        return None
    m = re.search(r"Component '?(\w+)'? has partial type '?([\w.]+)'?", diag.message)
    if not m:
        return None
    comp, cls = m.group(1), m.group(2)
    pattern = rf"^(\s*)([\w.]*{re.escape(cls.split('.')[-1])}\s+{re.escape(comp)}\b[^\n]*)$"
    if not re.search(pattern, src, re.M):
        return None
    return (
        re.sub(pattern, rf"\1// GAP: '{comp}' bound to partial class {cls}; see report.\n\1// \2",
               src, count=1, flags=re.M),
        f"removed '{comp}': {cls} is partial and cannot be instantiated; declared as a gap",
    )


def fix_missing_initial_condition(src: str, diag: Diagnostic) -> tuple[str, str] | None:
    """C-AI-1. Underdetermined initialisation: a state with no start value pinned.

    Passes `checkModel` (the counts balance) and fails at initialisation. The fix is
    mechanical -- mark the reported variable's start value as fixed -- so it should never
    cost a model call.
    """
    if diag.kind not in ("initialization", "singular", "build"):
        return None
    m = re.search(r"\b([\w.]+)\b[^.]*?(?:not fixed|underdetermined|no start value|initial)", diag.message, re.I)
    if not m:
        return None
    var = m.group(1).split(".")[-1]
    pattern = rf"(\b(?:Real|Integer|Boolean)\s+{re.escape(var)}\s*\(\s*start\s*=\s*[^)]*?)\)"
    if not re.search(pattern, src) or "fixed" in (re.search(pattern, src) or [""])[0]:
        return None
    return (
        re.sub(pattern, r"\1, fixed = true)", src, count=1),
        f"pinned '{var}' with fixed = true to close an underdetermined initialisation",
    )


def fix_missing_semicolon(src: str, diag: Diagnostic) -> tuple[str, str] | None:
    """C5. `Missing token: SEMICOLON`.

    omc reports the position of the token it *did* find, which is the start of the next
    statement, so the terminator belongs on the previous non-blank line -- not the one the
    diagnostic points at. Getting that offset wrong is why this looked like a semantic
    failure and was going to a model.
    """
    if "SEMICOLON" not in diag.message.upper() or not diag.line:
        return None
    lines = src.splitlines()
    i = diag.line - 2  # -1 for 0-based, -1 again for "the line before the reported token"
    while i >= 0 and not lines[i].strip():
        i -= 1
    if i < 0:
        return None
    text = lines[i].rstrip()
    if not text or text.endswith((";", "{", "}", "(", ",")) or text.lstrip().startswith("//"):
        return None
    lines[i] = text + ";"
    return "\n".join(lines) + "\n", f"added the missing semicolon on line {i + 1}"


DETERMINISTIC_FIXERS: tuple[Fixer, ...] = (
    fix_discrete_loop,
    fix_missing_inner,
    fix_undeclared_typo,
    fix_partial_type_binding,
    fix_missing_initial_condition,
    fix_missing_semicolon,
    fix_unbalanced_system,
    fix_unit_annotation,
)


# ------------------------------------------------------------------ catalog-grounded fixes
#
# C5. These need the harvested catalog, so they take it as a third argument and run after the
# plain fixers. The reason they belong in code rather than in a prompt: the compiler names the
# thing it could not find, and the catalog holds the verified list of what *does* exist. A
# closest-match lookup against ground truth is exact, free and offline -- and a model asked the
# same question can only recall the list, which is the one thing it is worst at.
#
# Each of these was recovered by the model before, at a round trip apiece. Every one moved here
# is a model call never made.

CatalogFixer = Callable[[str, Diagnostic, Any], "tuple[str, str, IREdit] | None"]
"""Returns (new_source, description, edit).

Unlike a deterministic fixer, a catalog fixer also says what the correction means in IR
terms, so the same repair can be folded back upstream and the next emission does not
reproduce the fault. See `repair/writeback.py`.
"""


def _closest(name: str, options: Iterable[str], cutoff: float = 0.8) -> str | None:
    """Nearest name, by case, then containment, then edit distance.

    Edit distance alone is the wrong instrument and it is worth saying why: `surfaceArea` and
    `area` score 0.53, below any cutoff you would trust, yet the intent is unmistakable --
    one name contains the other. Containment catches the rename-with-a-prefix case that pure
    ratio misses, and checking it before the ratio means the cutoff can stay strict.
    """
    opts = sorted(set(options))
    if not opts:
        return None
    lower = name.lower()
    for o in opts:
        if o.lower() == lower:
            return o
    contained = [o for o in opts if o.lower() in lower or lower in o.lower()]
    if len(contained) == 1:
        return contained[0]
    if contained:
        return max(contained, key=len)
    hit = difflib.get_close_matches(name, opts, n=1, cutoff=cutoff)
    return hit[0] if hit else None


def _observed_pairs(src: str, index: Any) -> dict[str, set[str]]:
    """Connector-type pairs this file already uses, learned from its own working connects.

    Used instead of hardcoding which connector mates with which. The model under repair is
    full of `connect()` statements that *do* compile; reading the connector types off both
    ends of those gives the compatibility relation for whatever domain this is, without the
    fixer knowing anything about fluids, flanges or heat ports.
    """
    pairs: dict[str, set[str]] = {}
    for a_comp, a_port, b_comp, b_port in re.findall(
        r"connect\(\s*(\w+)\.(\w+)(?:\[\d+\])?\s*,\s*(\w+)\.(\w+)(?:\[\d+\])?\s*\)", src
    ):
        ta = _connector_type(src, index, a_comp, a_port)
        tb = _connector_type(src, index, b_comp, b_port)
        if ta and tb:
            pairs.setdefault(ta, set()).add(tb)
            pairs.setdefault(tb, set()).add(ta)
    return pairs


def _connector_type(src: str, index: Any, component: str, port: str) -> str | None:
    cls = _declared_class_of(src, component)
    entry = index.get(cls) if cls and index else None
    if entry is None:
        return None
    return next((p.type for p in entry.ports if p.name == port), None)


def _declared_class_of(src: str, component: str) -> str | None:
    """The Modelica class a component was declared with, read back out of the source."""
    m = re.search(rf'^\s*([\w.]+)\s+{re.escape(component)}\s*[(\[;"]', src, re.M)
    return m.group(1) if m else None


def fix_unknown_class(src: str, diag: Diagnostic, index: Any) -> tuple[str, str] | None:
    """`Class SpecAlive.Vessels.Resevoir not found in scope Plant.`

    The catalog knows every class that exists. A single-edit distance from one of them is a
    typo, and correcting it against the catalog cannot invent a class -- the replacement is
    by construction one we harvested.
    """
    if index is None:
        return None
    m = re.search(r"Class ([\w.]+) not found", diag.message)
    if not m:
        return None
    missing = m.group(1)
    keys = [e.key for e in getattr(index, "entries", [])]
    best = _closest(missing, keys, cutoff=0.85)
    if not best or best == missing:
        return None
    return (
        re.sub(rf"(?<![\w.]){re.escape(missing)}(?![\w.])", best, src),
        f"corrected class '{missing}' to '{best}' (nearest in the catalog)",
        IREdit("class", missing, best, detail="not in the harvested catalog"),
    )


def fix_wrong_modifier(src: str, diag: Diagnostic, index: Any) -> tuple[str, str] | None:
    """`Modified element surfaceArea not found in class Reservoir.`

    omc gives the class's short name, so the full path comes from the declaring line, and the
    catalog then gives the real parameter list. Scoped to that one line: the same modifier
    name may be correct on a different class elsewhere in the file.
    """
    if index is None or not diag.line:
        return None
    m = re.search(r"Modified element (\w+) not found in class ([\w.]+)", diag.message)
    if not m:
        return None
    bad = m.group(1)
    lines = src.splitlines()
    i = diag.line - 1
    if not 0 <= i < len(lines) or bad not in lines[i]:
        return None
    cls = re.match(r"\s*([\w.]+)\s+(\w+)\s*\(", lines[i])
    entry = index.get(cls.group(1)) if cls else None
    if entry is None:
        return None
    best = _closest(bad, [p.name for p in entry.params])
    if not best:
        return None
    lines[i] = re.sub(rf"\b{re.escape(bad)}\b(\s*=)", rf"{best}\1", lines[i], count=1)
    return (
        "\n".join(lines) + "\n",
        f"renamed modifier '{bad}' to '{best}' on {cls.group(1)} (from the catalog)",
        IREdit("modifier", bad, best, block=cls.group(2), detail=cls.group(1)),
    )


def fix_unknown_connector(src: str, diag: Diagnostic, index: Any) -> tuple[str, str] | None:
    """`Variable B1.nonexistent_port[1] not found in scope Plant.`

    Find what class B1 was declared with, ask the catalog for its real connectors, take the
    nearest. The array subscript is preserved: `inlet[1]` and `inlet` are the same connector.
    """
    if index is None:
        return None
    m = re.search(r"Variable ([A-Za-z_]\w*)\.([A-Za-z_]\w*)(\[\d+\])? not found", diag.message)
    if not m:
        return None
    comp, port, sub = m.group(1), m.group(2), m.group(3) or ""
    cls = _declared_class_of(src, comp)
    entry = index.get(cls) if cls else None
    if entry is None:
        return None
    names = [p.name for p in entry.ports]

    # Prefer type compatibility over name similarity. `nonexistent_port` resembles neither
    # `inlet` nor `outlet`, so a fuzzy match would either guess or give up -- but the peer on
    # the other side of the connect has a type, and the file's own working connects say which
    # types mate. When that leaves exactly one candidate the answer is not a guess.
    best: str | None = None
    peer = re.search(
        rf"connect\(\s*{re.escape(comp)}\.{re.escape(port)}(?:\[\d+\])?\s*,\s*(\w+)\.(\w+)|"
        rf"connect\(\s*(\w+)\.(\w+)(?:\[\d+\])?\s*,\s*{re.escape(comp)}\.{re.escape(port)}",
        src,
    )
    if peer:
        pc, pp = (peer.group(1), peer.group(2)) if peer.group(1) else (peer.group(3), peer.group(4))
        peer_type = _connector_type(src, index, pc, pp)
        if peer_type:
            mates = _observed_pairs(src, index).get(peer_type, set())
            viable = [p.name for p in entry.ports if p.type in mates]
            if len(viable) == 1:
                best = viable[0]

    if best is None:
        best = _closest(port, names, cutoff=0.6)
    if not best or best == port:
        return None
    return (
        src.replace(f"{comp}.{port}{sub}", f"{comp}.{best}{sub}"),
        f"corrected connector '{comp}.{port}' to '{comp}.{best}' (declared by {cls})",
        IREdit("port", port, best, block=comp, detail=f"declared by {cls}"),
    )


CATALOG_FIXERS: tuple[CatalogFixer, ...] = (
    fix_unknown_class,
    fix_wrong_modifier,
    fix_unknown_connector,
)


_GAP_BLOCK = re.compile(r"^\s*// GAP: block '([^']+)'", re.M)


def _unrepairable_reason(src: str, diag: Diagnostic) -> str | None:
    """Is this failure beyond any local edit? Return why, or None to carry on repairing.

    One case so far, and it is the common one on a packet where extraction is incomplete:
    an **under-determined** system whose missing equations are missing because components
    were never bound. The emitter already says so, in as many words:

        // GAP: block 'SRC_101' (Boundary source) has no binding; see report.

    A repair loop cannot conjure the boundary source that would supply those equations, and a
    model asked to try will either fail or invent a component -- the second being worse, since
    it compiles. Naming the unbound blocks is the useful answer and costs nothing.

    Deliberately narrow: only under-determined (too few equations), and only when there are
    gaps to point at. An over-determined system is often a real over-specification that
    `fix_unbalanced_system` can relax, and an under-determined one with no gaps is a genuine
    modelling bug worth a repair attempt.
    """
    if diag.kind != "unbalanced_system":
        return None
    m = re.search(r"has (\d+) equation\(s\) and (\d+) variable\(s\)", diag.message + diag.raw)
    if not m:
        return None
    eqs, vars_ = int(m.group(1)), int(m.group(2))
    if eqs >= vars_:
        return None
    gaps = _GAP_BLOCK.findall(src)
    if not gaps:
        return None
    shown = ", ".join(gaps[:6]) + (f" and {len(gaps) - 6} more" if len(gaps) > 6 else "")
    return (
        f"under-determined by {vars_ - eqs} equation(s) because {len(gaps)} block(s) "
        f"never bound to a component: {shown}. No edit to this file can supply them -- "
        f"the gap is in extraction, not in the Modelica."
    )


# ----------------------------------------------------------------------------- model repair

REPAIR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["diagnosis", "strategy", "replacements", "explanation"],
    "properties": {
        # C-AI-2. Diagnosis and strategy come BEFORE the edit, and are required. Naming the
        # cause and the plan first is what stops the common failure mode of patching the line
        # the compiler pointed at when the cause is three lines above it. They are also what
        # the next iteration reads back as memory.
        "diagnosis": {"type": "string", "description": "What is actually wrong. One sentence."},
        "strategy": {"type": "string", "description": "The edit that will fix it, and why."},
        "replacements": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["find", "replace"],
                "properties": {"find": {"type": "string"}, "replace": {"type": "string"}},
            },
        },
        # C-AI-2 tool use. The agent may ask for a verified class signature instead of
        # guessing one. Answered from the harvested catalog -- ground truth, not recall.
        "lookup": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Modelica class names whose verified signature you need before editing.",
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
{history}
Work in this order:
1. `diagnosis` -- what is actually wrong. The compiler points at the symptom; the cause is
   often a few lines above it.
2. `strategy` -- the edit you will make, and why it addresses the diagnosis.
3. `replacements` -- the edit itself.

Rules:
- Return replacements as exact substrings of the source window. Each `find` must appear
  verbatim, exactly once, inside the window shown above.
- Change as little as possible. Do not reformat, rename or restructure anything unrelated.
- Do not invent Modelica classes, parameters or connectors. If you need the real signature of
  a class, put its full name in `lookup` and return an empty `replacements`; you will be shown
  the verified signature and asked again. Guessing an API is always worse than asking.
- If a previous attempt is listed above, do not repeat it. It was measured and rejected.
- Answer JSON only.
"""

#: Injected when the agent has already tried and failed. Multi-pass refinement is only
#: refinement if the next pass can see the last one.
HISTORY_BLOCK = """
PREVIOUS ATTEMPTS ON THIS MODEL (all measured by the compiler, all rejected)
{attempts}
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
    #: Set on an accepted catalog-tier fix: the same correction stated against the IR, for
    #: the pipeline to fold back upstream before it re-emits. None for every other method.
    ir_edit: IREdit | None = None


@dataclass
class RepairOutcome:
    ok: bool
    source: str
    iterations: int
    steps: list[RepairStep] = field(default_factory=list)
    final: OmcResult | None = None

    @property
    def ir_edits(self) -> list[IREdit]:
        """The accepted catalog-tier fixes, restated as corrections to the IR.

        Only accepted ones. A patch the compiler rejected is not evidence of anything, and
        writing it upstream would push a guess we have already disproved into the IR -- and
        from there into the SysML we ship.
        """
        return [s.ir_edit for s in self.steps if s.accepted and s.ir_edit is not None]

    def summary(self) -> str:
        det = sum(1 for s in self.steps if s.method in ("deterministic", "catalog") and s.accepted)
        llm = sum(1 for s in self.steps if s.method == "model" and s.accepted)
        if self.ok:
            return (f"repaired after {self.iterations} iteration(s): "
                    f"{det} deterministic fix(es), {llm} model-authored fix(es)")
        # Three ways to not succeed, and they mean completely different things to whoever
        # reads the report. Saying "unrepaired" for all of them hid a quota outage behind
        # language that sounds like a modelling failure.
        last = self.steps[-1] if self.steps else None
        if last and last.method == "declared":
            return f"not repairable by editing: {last.description}"
        if last and "router failed" in (last.description or ""):
            return (f"repair unavailable ({last.description.split(':', 1)[-1].strip()[:80]}); "
                    f"{det} deterministic fix(es) applied first")
        return (f"unrepaired after {self.iterations} iteration(s): "
                f"{det} deterministic fix(es), {llm} model-authored fix(es)")


class RepairLoop:
    def __init__(
        self,
        runner: OmcRunner,
        router: Any | None = None,
        *,
        max_iterations: int = 6,
        window: int = 15,
        index: Any | None = None,
    ) -> None:
        self.runner = runner
        self.router = router
        self.max_iterations = max_iterations
        self.window = window
        #: CatalogIndex, for answering the agent's `lookup` requests. C-AI-2.
        self.index = index

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
        #: C-AI-2 memory. What was tried, and what the compiler said about it. Fed back to
        #: the agent so the next pass is a refinement rather than another first guess.
        history: list[str] = []
        #: (diagnostic, patch) pairs already rejected. A deterministic fixer is a pure
        #: function of the two, so re-deriving one is guaranteed to produce the same patch
        #: and the same rejection -- pure waste of the iteration budget, and for the model
        #: tier, of the minute's tokens.
        tried: set[str] = set()

        def gate(files: list[Any]) -> OmcResult:
            """The bar a candidate has to clear.

            C-AI-1: `checkModel` alone is not the bar. A model can check cleanly and still
            fail to build -- a partial-type binding does exactly that -- so when a stop time
            is given the gate runs the simulation too, and simulate-stage diagnostics become
            repairable like any other.
            """
            res = self.runner.check(model_name, files)
            if res.ok and stop_time:
                res = self.runner.simulate(model_name, files, stop_time=stop_time)
            return res

        for it in range(self.max_iterations + 1):
            target.write_text(source, encoding="utf-8")
            files = [target, *support_files]
            last = gate(files)
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

            patched, method, desc, edit = self._attempt(
                source, diag, target, catalog_note, history
            )
            if patched is None or patched == source:
                steps.append(RepairStep(it, diag.kind, method, desc or "no fix found",
                                        n_errors, n_errors, False, edit))
                break

            signature = f"{diag.kind}|{diag.message}|{desc or method}"
            if signature in tried:
                steps.append(RepairStep(
                    it, diag.kind, method,
                    f"{desc or method} -- already rejected once, not retried",
                    n_errors, n_errors, False, None,
                ))
                break

            # Evaluate the candidate against the same bar the loop exits on -- otherwise a
            # patch that fixes `check` while breaking the build would be accepted, and the
            # loop would congratulate itself on a model that does not run.
            target.write_text(patched, encoding="utf-8")
            probe = gate([target, *support_files])
            after = 0 if probe.ok else max(len(probe.diagnostics), 1)
            # Error COUNT is the wrong bar for a grounded fix. omc reports the first failure
            # and stops, so correcting a class that provably does not exist routinely
            # uncovers the next latent error and leaves the count unchanged -- at which point
            # keep-best discards a correct fix, the source never changes, and the next
            # iteration derives the identical patch from the identical diagnostic. That is
            # how a repairable model burned six iterations and reported "0 fixes".
            #
            # A deterministic or catalog fix is grounded in something checkable: the
            # language's own grammar, or a harvested signature. It cannot invent a class or a
            # parameter, so the honest bar for it is "does not make things worse". A
            # model-authored patch is a guess and keeps the stricter bar -- that asymmetry is
            # the whole reason for the tiering.
            grounded = method in ("deterministic", "catalog")
            accepted = probe.ok or after < n_errors or (grounded and after <= n_errors)
            steps.append(RepairStep(it, diag.kind, method, desc or "", n_errors, after,
                                    accepted, edit))
            if accepted:
                source = patched
                history.append(f"[accepted] {desc or method}: errors {n_errors} -> {after}")
            else:
                # Keep-best: never apply a patch that made things worse. But record WHY it
                # was rejected and let the agent try a different approach, rather than
                # stopping at the first bad guess -- that is the difference between a loop
                # that refines and a loop that gives up.
                target.write_text(source, encoding="utf-8")
                tried.add(signature)
                history.append(
                    f"[rejected] {desc or method}: errors {n_errors} -> {after}, discarded"
                )

        target.write_text(best_source, encoding="utf-8")
        return RepairOutcome(False, best_source, len(steps), steps, last)

    # ------------------------------------------------------------------ one repair attempt
    def _signature(self, class_names: list[str]) -> str:
        """Answer a `lookup` request from the harvested catalog. C-AI-2 tool use.

        The point is not convenience. The catalog is the same ground truth the emitter binds
        against (C-03), so an agent that asks instead of recalling cannot propose a parameter
        or connector that does not exist -- the class of error it is most prone to.
        """
        if self.index is None:
            return "(no catalog available; do not guess -- say so in `explanation`)"
        out: list[str] = []
        for name in class_names[:4]:
            entry = self.index.get(name)
            if entry is None:
                out.append(f"{name}: NOT IN CATALOG. It does not exist; do not use it.")
                continue
            params = ", ".join(f"{p.name}: {p.type}" for p in entry.params[:14])
            ports = ", ".join(f"{p.name}: {p.type}" for p in entry.ports)
            out.append(f"{name}\n  parameters: {params or '(none)'}\n  connectors: {ports or '(none)'}")
        return "VERIFIED SIGNATURES (from the harvested catalog)\n" + "\n".join(out)

    def _attempt(
        self,
        source: str,
        diag: Diagnostic,
        path: Path,
        catalog_note: str,
        history: list[str] | None = None,
    ) -> tuple[str | None, str, str, IREdit | None]:
        for fixer in DETERMINISTIC_FIXERS:
            try:
                result = fixer(source, diag)
            except Exception:
                continue
            if result is not None:
                # Deterministic fixes stay .mo-only, by design. `pre()` around a state read
                # or a missing semicolon corrects the emitter's output, not a decision the
                # IR ever made -- there is nothing upstream to write back to.
                return result[0], "deterministic", result[1], None

        # C5. Then the ones that need ground truth. Still no tokens spent: the compiler names
        # what it could not find and the catalog holds what exists, so the correction is a
        # lookup, not a recollection.
        for cfixer in CATALOG_FIXERS:
            try:
                result = cfixer(source, diag, self.index)
            except Exception:
                continue
            if result is not None:
                return result[0], "catalog", result[1], result[2]

        # Before spending a model call, ask whether ANY local edit could fix this. Some
        # failures are structural -- the model is under-determined because components were
        # never extracted -- and no minimal diff brings a missing tank into existence. Calling
        # a model there burns the minute's token budget to be told nothing, and the honest
        # output is a declared gap naming what is absent.
        reason = _unrepairable_reason(source, diag)
        if reason:
            return None, "declared", reason, None

        if self.router is None:
            return (None, "deterministic",
                    "no deterministic fixer matched and no router configured", None)

        lines = source.splitlines()
        centre = (diag.line or len(lines) // 2) - 1
        start = max(0, centre - self.window)
        end = min(len(lines), centre + self.window)
        window = "\n".join(f"{i + 1:5d}| {lines[i]}" for i in range(start, end))
        window_text = "\n".join(lines[start:end])
        hist = (
            HISTORY_BLOCK.format(attempts="\n".join(f"  - {h}" for h in history[-4:]))
            if history
            else ""
        )

        def build(note: str) -> str:
            return REPAIR_PROMPT.format(
                kind=diag.kind,
                location=diag.locate(),
                message=diag.message,
                raw=diag.raw[:1500],
                start=start + 1,
                end=end,
                path=path.name,
                window=window,
                catalog_note=note or "(no catalog context supplied)",
                history=hist,
            )

        def validate(data: Any) -> tuple[bool, str]:
            reps = data.get("replacements") or []
            for r in reps:
                if window_text.count(r["find"]) != 1:
                    return False, f"'find' text does not occur exactly once in the window: {r['find'][:60]!r}"
            return True, ""

        note = catalog_note
        data: dict[str, Any] = {}
        # Two rounds at most: one to ask for signatures, one to act on them. Bounded on
        # purpose -- an agent that can keep asking will keep asking.
        for round_no in range(2):
            try:
                resp = self.router.run(
                    "repair_modelica", build(note), schema=REPAIR_SCHEMA, validator=validate
                )
            except Exception as exc:
                return None, "model", f"router failed: {exc}", None
            data = resp.data or {}
            wanted = [w for w in (data.get("lookup") or []) if isinstance(w, str)]
            if wanted and not data.get("replacements") and round_no == 0:
                note = self._signature(wanted)
                continue
            break

        reps = data.get("replacements") or []
        rationale = (data.get("strategy") or data.get("explanation") or "").strip()
        if not reps:
            return None, "model", (rationale or "model declined to patch")[:200], None
        patched = source
        for r in reps:
            patched = patched.replace(r["find"], r["replace"], 1)
        return patched, "model", rationale[:200], None


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
