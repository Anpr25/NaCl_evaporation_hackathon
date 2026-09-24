# Test Rig DR-2 — Geared Drive Bench
Document status: Released Rev A. Later approved change records may override values here.

## 1. Purpose
A bench rig for characterising a geared rotational drive. A constant-torque source drives a
motor-side rotating mass through a reduction gear into a load-side rotating mass. A viscous
damper represents the parasitic load and is grounded to the frame.

## 2. Drive train
| Item | Tag | Description |
|---|---|---|
| Torque source | M1 | Constant-torque drive, applied to the motor shaft |
| Motor inertia | J1 | Rotor and coupling inertia on the motor shaft |
| Reduction gear | G1 | Single-stage ideal reduction gear |
| Load inertia | J2 | Load-side flywheel |
| Viscous damper | D1 | Parasitic damping, reacted against the frame |
| Frame | F1 | Fixed mechanical ground |

## 3. Arrangement
M1 drives J1. J1 drives G1. G1 drives J2. J2 is damped by D1, which is grounded to F1.

## 4. Notes
The gear is treated as ideal: no backlash, no efficiency loss, no elasticity. The damper is
linear in angular velocity.
