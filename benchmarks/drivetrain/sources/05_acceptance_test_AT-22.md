# Acceptance Test AT-22 — Geared Drive Bench
Rev B

## 1. Initial conditions
| Item | Value |
|---|---|
| Simulation time | 0 s |
| All shaft speeds | 0 rad/s |
| Applied torque | constant from t = 0 |

## 2. Acceptance criteria
| Check | Criterion |
|---|---|
| Load spins up | Load-side speed exceeds 12.0 rad/s |
| Steady state | Load-side speed settles at 12.5 rad/s within 2% |
| No overshoot | Load-side speed never exceeds 13.0 rad/s |
| Gear ratio holds | Motor-side speed is 5x the load-side speed at steady state |
| Direction | Load-side speed is never negative |

## 3. Run
Stop time 20 s. Log at 0.02 s or faster.
