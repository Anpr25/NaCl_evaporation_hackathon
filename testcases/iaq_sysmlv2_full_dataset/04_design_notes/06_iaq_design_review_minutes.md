# DR-IAQ-05 - Indoor Air Quality Control Design Review

**Date:** 2026-02-14  
**System:** RM-201 room CO2 controlled ventilation  
**Status:** Final / approved

## Attendees
M. Ortega (owner engineering), N. Shah (controls), L. Chen (simulation), E. Ruiz (BMS), T. Willis (commissioning)

## Decisions
1. The owner limit is **1000 ppm absolute room CO2**. The phrase "1000 ppm above outdoor" from the 10-Feb email is not applicable to this benchmark.
2. Outdoor CO2 for the reference model remains **300 ppm**, represented as `0.3 * 1.519E-3 kg/kg`.
3. Internal controller feedback remains trace-substance mass fraction in **kg/kg**. A normalization gain converts `1.519E-3 kg/kg` to `1.0`.
4. Controller output is an **ACH command**. The airflow conversion uses `m = ACH * V * rho / 3600`.
5. In the Modelica source component, inflow is represented with a **negative mass-flow command**. SysML requirements should distinguish this software sign convention from physical airflow direction.
6. The occupant source implementation may keep `C_source=100 kg/kg` and scale its carrier flow by 1/100. The resulting CO2 injection must remain `8.18E-6 kg/s/person`.
7. `C_source=100 kg/kg` is a numerical implementation parameter and shall not be shown as a realistic room or outdoor gas composition.
8. If the CO2 sensor is invalid continuously for more than 60 s, fallback ventilation is 4 ACH and a fault indication is raised. This fault mode is outside the baseline trend run.

## Actions
- Controls: issue revised tuning after updated occupancy schedule. **Closed by CR-IAQ-007.**
- Facilities: issue final people schedule. **Closed by OCC-SCH-04 Rev C.**
- Commissioning: verify absolute 1000 ppm criterion in 24-h synthetic trend. **Closed by CP-23 Rev C.**
