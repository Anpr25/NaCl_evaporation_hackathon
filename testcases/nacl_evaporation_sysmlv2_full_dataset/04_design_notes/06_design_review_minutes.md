# Design Review DR-07 - NaCl Evaporation Bench

**Date:** 2026-02-21  
**Status:** Final / approved

## Decisions
1. Controller remains a sequential StateGraph with a parallel split after evaporation and a join before cycle reset.
2. B5 heater permissive: `LIS-501 >= 0.05 m` and `FIS-801 >= 0.10 kg/s`.
3. P1 and P2 require dry-run inhibit from source-tank level.
4. Automated process valves are discrete and fail closed.
5. K1 remains a physical condenser even if the legacy Modelica component combines evaporator and condenser equations.
6. Junction volumes are mandatory where closed valve combinations could otherwise leave pressure/composition states undefined.
7. StandardWater is a topology/control integration baseline only; intended physical variant remains WaterNaCl.

## Open Actions
- A-17: resolve return-header stream identity.
- A-18: finalize B7 cooling completion temperature.
- A-19: isolate WaterNaCl pump-start convergence issue.
