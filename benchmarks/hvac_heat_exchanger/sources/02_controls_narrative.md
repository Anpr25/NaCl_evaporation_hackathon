# AHU-2 Controls — Sequence of Operation
Issue: Rev A. Prepared by Controls. Applies to zone ZN-1 heating only.

## SOO-1  Occupied heating

The zone controller TC-2101 reads zone air temperature from TT-2101 and enables the preheat
coil on a simple two-position sequence with deadband. There is no optimum start, no night
setback and no morning boost in this revision.

**Step 1 — Warmup.** From system start the coil is enabled. The coil remains enabled while
the zone is below the upper deadband limit.

**Step 2 — Hold.** When TT-2101 reaches 21.5 degC the coil is disabled. The coil is
re-enabled when TT-2101 falls to 20.5 degC. The zone then cycles between these two limits.

The deadband limits above are the commissioned values. The heating setpoint quoted in the
design basis (21 degC) is the midpoint of the deadband and is not itself a switching point.

## SOO-2  Interlocks

The preheat coil shall not be enabled unless the zone temperature transmitter is reading a
plausible value. TT-2101 is regarded as plausible above -40 degC.

## SOO-3  Tag cross-reference

Different disciplines refer to the coil differently. For the avoidance of doubt:

| This document | Mechanical schedule | Commissioning sheets |
|---|---|---|
| preheat coil | HC-1 | PHC |

All three refer to the same physical coil in the AHU-2 supply duct.
