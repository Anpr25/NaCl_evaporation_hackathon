"""Retrieval regression probe — the eight queries from STATUS.md §2.3, plus the two that
motivated C7.

Phrased the way a brochure or a datasheet would phrase it, not the way MSL names things:
that is the gap the catalog has to bridge. Run after any change to harvest filters, aliases
or ranking.

    python scripts/retrieval_probe.py
"""

from __future__ import annotations

import sys

from specalive.catalog.retrieve import CatalogIndex

PROBES: list[tuple[str, str]] = [
    ("flywheel rotating mass with moment of inertia", "Modelica.Mechanics.Rotational.Components.Inertia"),
    ("gearbox with fixed transmission ratio", "Modelica.Mechanics.Rotational.Components.Gearbox"),
    ("permanent magnet DC machine", "Modelica.Electrical.Machines.BasicMachines.DCMachines.DC_PermanentMagnet"),
    ("open storage tank with fluid ports", "Modelica.Fluid.Vessels.OpenTank"),
    ("PID controller block", "Modelica.Blocks.Continuous.PID"),
    ("ideal linear electrical resistor", "Modelica.Electrical.Analog.Basic.Resistor"),
    ("linear translational damper", "Modelica.Mechanics.Translational.Components.Damper"),
    ("thermal conduction between two ports", "Modelica.Thermal.HeatTransfer.Components.ThermalConductor"),
    # The two C7 was aimed at, from the PLAN.md C2 note.
    ("electrical resistance element", "Modelica.Electrical.Analog.Basic.Resistor"),
    ("heat conduction through a wall", "Modelica.Thermal.HeatTransfer.Components.ThermalConductor"),
]


def main() -> int:
    ix = CatalogIndex.from_file()
    print(f"catalog: {len(ix.entries)} classes\n")

    top1 = 0
    for query, want in PROBES:
        hits = ix.search(query, k=5)
        got = hits[0].entry.key if hits else "(nothing)"
        ok = got == want
        top1 += ok
        rank = next((i + 1 for i, h in enumerate(hits) if h.entry.key == want), None)
        mark = "ok  " if ok else "MISS"
        print(f"{mark} {query!r}")
        print(f"       got  {got}")
        if not ok:
            print(f"       want {want}   (rank {rank if rank else '>5'})")
            for i, h in enumerate(hits[:5], 1):
                print(f"         {i}. {h.entry.key}")
    print(f"\ntop-1: {top1}/{len(PROBES)}")
    # Any partial class in the results at all is a C7 regression.
    leaked = [e.key for e in ix.entries if ".BaseClasses." in e.key or e.key.endswith("Element1D")]
    if leaked:
        print(f"WARNING: {len(leaked)} partial-looking class(es) in the catalog: {leaked[:5]}")
    return 0 if top1 == len(PROBES) else 1


if __name__ == "__main__":
    sys.exit(main())
