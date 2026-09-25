"""Catalog-tier repairs, expressed against the IR instead of the Modelica text.

Why this file exists
--------------------
The repair loop edits `GeneratedPlant.mo`, because that is where the compiler points. For a
*deterministic* fix that is the right and only place: `pre()` around a state read, a missing
semicolon, a unit annotation. None of those are decisions the IR ever made, so there is
nothing upstream to correct.

A **catalog-tier** fix is different in kind. `Class SpecAlive.Vessels.Resevoir not found`,
`Modified element surfaceArea not found`, `Variable B1.nonexistent_port not found` -- each of
those is a wrong *binding decision*, and binding decisions live in the IR (`modelica_class`,
`modelica_modifiers`, `Port.name`). Patching only the .mo left us in a bad place twice over:

  * the next emission re-derived the same wrong binding, so the fix survived exactly until
    something re-ran the emitter; and
  * the SysML we ship as a deliverable still described the wrong plant, because SysML is
    emitted from the IR and the IR was never told.

So a catalog fix is applied in both directions: to the .mo, so the current compile can
proceed, and to the IR, so the correction is durable and the architecture artefact agrees
with the code. The pipeline then re-emits SysML from the corrected IR and rebuilds the
Modelica from *that* -- IR -> SysML -> .mo, which is the contract C-08 is supposed to hold.

This is safe to do precisely because both bindings are idempotent on re-emission: `Binder`
skips a block that already carries a tier and a class, and connector resolution keeps a port
name the class already declares (see `emit/modelica.py`). A corrected value is therefore
read back, not overwritten.

Owner: C.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

EditKind = Literal["class", "modifier", "port"]


def _mid(raw: str) -> str:
    """The Modelica identifier an IR id becomes. Mirrors `emit.modelica._mid`.

    Duplicated rather than imported: `repair` must not depend on `emit`, and this is three
    lines of frozen convention. `tests/test_agentic.py` asserts the two stay in step.
    """
    out = re.sub(r"[^A-Za-z0-9_]", "_", raw.strip())
    return out if out and not out[0].isdigit() else f"m_{out}"


@dataclass
class IREdit:
    """One catalog-tier correction, stated in IR terms rather than as a text diff.

    `block` is the *Modelica* component name as the compiler reported it (`TK_101`), because
    that is all a diagnostic gives us; `apply` maps it back to the IR block id (`TK-101`).
    A `class` edit carries no block: it is applied to every block bound to the stale class,
    since one bad catalog key is usually shared.
    """

    kind: EditKind
    old: str
    new: str
    block: str | None = None
    detail: str = ""

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        where = f"{self.block}." if self.block else ""
        return f"{self.kind}: {where}{self.old} -> {self.new}"


def apply_ir_edits(model: Any, edits: list[IREdit]) -> list[str]:
    """Fold catalog-tier corrections back into the IR. Returns what actually landed.

    An edit that matches nothing is dropped silently rather than raised: the .mo has already
    been fixed either way, and a repair that cannot be traced back to a block is not a reason
    to fail a run. The caller reports the difference between `len(edits)` and the return.
    """
    applied: list[str] = []
    by_mid = {_mid(b.id): b for b in model.blocks}

    for edit in edits:
        if edit.kind == "class":
            hit = [b for b in model.blocks if b.modelica_class == edit.old]
            for b in hit:
                b.modelica_class = edit.new
                b.binding_rationale = (
                    f"{b.binding_rationale or ''} | repaired: {edit.old} is not in the "
                    f"catalog, rebound to {edit.new}".strip(" |")
                )
            if hit:
                applied.append(f"{len(hit)} block(s) rebound from {edit.old} to {edit.new}")
            continue

        block = by_mid.get(edit.block or "")
        if block is None:
            continue

        if edit.kind == "modifier":
            if edit.old not in block.modelica_modifiers:
                continue
            # Order is not meaningful in a modifier list, so a pop/insert is a rename.
            block.modelica_modifiers[edit.new] = block.modelica_modifiers.pop(edit.old)
            applied.append(f"{block.id}: modifier {edit.old} renamed to {edit.new}")

        elif edit.kind == "port":
            # Match on the bare name: the compiler reports `inlet` for a port the IR holds
            # as `inlet[1]`, and the subscript is the emitter's to re-derive.
            port = next(
                (p for p in block.ports if p.name.split("[")[0] == edit.old.split("[")[0]),
                None,
            )
            if port is None:
                continue
            port.name = edit.new
            applied.append(f"{block.id}: port {edit.old} renamed to {edit.new}")

    return applied
