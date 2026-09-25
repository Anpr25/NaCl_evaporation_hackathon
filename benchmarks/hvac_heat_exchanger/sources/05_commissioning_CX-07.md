# Commissioning Test CX-07 — AHU-2 / ZN-1 Heating Warmup and Hold
Status: issued for test. Witness: Client Rep. Duration: 60 minutes from cold start.

## Purpose

Demonstrate that the PHC brings zone ZN-1 from the overnight cold condition up into the
control deadband, and then holds it there on two-position control.

## Preconditions

- AHU-2 running, outdoor air at or near winter design (2 degC).
- Zone unoccupied, no internal gains, no solar.
- The zone has been off overnight and is at the same temperature as outdoor air at the start
  of the test. (Note to witness: the overnight soak temperature is not logged by the BMS.
  Record it by hand on the day.)
- LPHW flow and return temperatures within normal range so the coil can make its rated duty.

## Acceptance criteria

| Ref | Criterion | Basis |
|---|---|---|
| CX-07-01 | TT-2101 rises through 20.5 degC | Warmup reaches the bottom of the deadband |
| CX-07-02 | TT-2101 rises through 21.5 degC | Warmup reaches the top of the deadband and the coil cuts out |
| CX-07-03 | TT-2101 reaches 20.5 degC before it reaches 21.5 degC | Monotonic warmup, no overshoot ordering fault |
| CX-07-04 | TT-2101 at end of test is at or below 21.5 degC | Two-position control is holding, not running away |
| CX-07-05 | TT-2101 at end of test is at or above 20.5 degC | Coil is re-enabling on the bottom of the deadband |
| CX-07-06 | TT-2101 at end of test is at or above 20.0 degC | Zone is maintained fit for occupation |
| CX-07-07 | TT-2101 at end of test is at or below 22.0 degC | No sustained overshoot above the deadband |

## Expected timings (informative, not pass/fail)

From a 2 degC start with the coil at full duty, first-order warmup of the zone mass against
the envelope loss gives a time constant of about ten minutes. The bottom of the deadband is
expected at roughly 15 minutes and the top at roughly 17 minutes. Timings are indicative
only; the criteria above are the pass/fail record.
