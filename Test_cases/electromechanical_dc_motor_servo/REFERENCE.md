# REFERENCE (answer key): electromechanical_dc_motor_servo

This file is outside `sources/` and must never be fed to the pipeline.
Citation shorthand: `S01` ... `S06` = `sources/01_...` ... `sources/06_...`.
**inferred** = not read from a source; supplied by the packet author.

## 1. System summary
1. An armature-controlled permanent-magnet DC motor (constant field) drives a rigid rotor with viscous friction (S01 "Physical setup", "System equations").
2. The input is the armature voltage V and the output is the shaft speed theta-dot. Armature R and L are in series with the back EMF e = K theta-dot (S01, S02).
3. The speed loop is closed with unity feedback: r -> error e -> C(s) -> u -> P(s) -> theta-dot, fed back to the summing junction (S03, S04).
4. The controller is a PID, C(s) = Kp + Ki/s + Kd s. The final gains are Kp = 100, Ki = 200, Kd = 10 (S03 "Tuning the gains").
5. The requirements for a 1 rad/s step are: settling time < 2 s, overshoot < 5 %, steady-state error < 1 % (S01 "Design requirements", S03).

**Primary source:** the CTMS motor (S01 to S05). It is the only source that gives a complete parameter set, a controller and requirements. S06 (maxon A-max 22) is a real motor with very different constants, 12 winding variants and no controller. It is an alternative data set, not the scoped motor.

## 2. Modelling scope
In scope:
- The armature circuit (voltage source, R, L, back EMF).
- Electromechanical conversion with Kt = Ke = K.
- Rotor inertia J and viscous friction b.
- Speed measurement (unity feedback).
- Summing junction, PID controller, and a step reference of 1 rad/s.
- The CTMS parameter set.

Out of scope:
- Position control. The MotorPosition tutorial is not in the packet.
- Load inertia or load torque. No source gives any; J is "moment of inertia of the rotor" only.
- The thermal model, brushes, commutation and saturation.
- The gearheads and encoder listed in S06.
- Temperature dependence of R.
- The earlier tuning iterations (P-only, and PID 75/1/1 and 100/200/1). They appear only as the narrative that leads to the final gains.
- Using the S06 winding data as the plant.

## 3. Expected parts
| id | kind | citation |
|---|---|---|
| voltageSource | controlled voltage source (armature voltage V, driven by controller output u) | S01 "Physical setup" ("voltage source (V) applied to the motor's armature"); S02 source symbol `v`; S04 `u` enters P(s), whose input is V (S01 eq 7) |
| armatureResistor | resistor R | S01 parameter list; S02 `R` |
| armatureInductor | inductor L | S01 parameter list; S02 `L` |
| emf | electromechanical converter (torque T = Kt i, back EMF e = Ke theta-dot) | S01 eqs (1), (2); S02 `e` motor symbol |
| rotor | rotational inertia J | S01 parameter list; S02 `J` |
| viscousFriction | rotational damper b (to the fixed frame, **inferred**) | S01 "viscous friction model"; S02 `b theta-dot` torque arrow |
| electricalGround | ground reference | **inferred** (a closed loop is drawn in S02, but no ground is shown) |
| mechanicalFixed | housing/fixed frame for the damper reaction | **inferred** (S02 "Fixed field" is the stator field, not a mechanical ground) |
| speedSensor | ideal speed measurement, gain 1 | **inferred** from S04 (the theta-dot output is fed straight back); no sensor part is named in any source |
| feedbackJunction | summing junction (+r, -theta-dot) | S04 (`+`, `-` signs) |
| controller | PID C(s) | S03 eq (4); S04 `controller C(s)` |
| reference | step, 1 rad/s | S03 "For a 1-rad/sec step reference"; S01 "unit step command in motor speed" |

## 4. Ports / connections
| from | to | domain | citation |
|---|---|---|---|
| voltageSource.+ | armatureResistor | electrical | S02 (series loop v - R - L - motor) |
| armatureResistor | armatureInductor | electrical | S02 |
| armatureInductor | emf.+ | electrical | S02 (`+` on the motor terminal) |
| emf.- | voltageSource.- | electrical | S02 |
| voltageSource.- | electricalGround | electrical | **inferred** |
| emf.flange | rotor | rotational | S01 "rotor and shaft are assumed to be rigid"; S02 |
| rotor | viscousFriction -> mechanicalFixed | rotational | S01 viscous friction; S02 `b theta-dot`; the fixed side is **inferred** |
| rotor | speedSensor | rotational -> signal | **inferred** (S04 feeds back theta-dot) |
| reference (r) | feedbackJunction (+) | signal | S04 |
| speedSensor (theta-dot) | feedbackJunction (-) | signal | S04 |
| feedbackJunction (e) | controller input | signal | S04 |
| controller output (u) | voltageSource control input (V) | signal -> electrical | S04 `u -> P(s)`; S01 eq (7) P(s) = Theta-dot(s)/V(s) |

**Loop signal path:** r -> [sum: r - theta-dot] -> e -> C(s) -> u = V -> armature -> i -> T = K i -> J, b -> theta-dot -> (unity feedback) -> sum.

## 5. Parameters
Primary (CTMS):
| name | value | unit (as written) | citation |
|---|---|---|---|
| J | 0.01 | kg.m^2 | S01 parameter list; MATLAB `J = 0.01` (S01, S03) |
| b | 0.1 | N.m.s | S01 |
| Ke | 0.01 | V/rad/sec | S01 |
| Kt | 0.01 | N.m/Amp | S01 |
| K (= Kt = Ke) | 0.01 | (SI) | S01 "In SI units ... K_t = K_e"; `K = 0.01` |
| R | 1 | Ohm | S01 |
| L | 0.5 | H | S01 |
| Kp | 100 | - | S03 final gains |
| Ki | 200 | - | S03 |
| Kd | 10 | - | S03 |
| reference step | 1 | rad/sec | S03 |
| simulation span | 0:0.01:4 | s | S03 `step(sys_cl, 0:0.01:4)` |

Alternative (S06 maxon A-max 22, 5 W). Example column: order number 110117. All 12 columns are real data, and no source picks one.
| name | value (110117) | range across 12 windings | unit | citation |
|---|---|---|---|---|
| Nominal voltage | 6.0 | 6.0 to 48.0 | Volt | S06 line 2 |
| Terminal resistance | 1.71 | 1.71 to 145 | Ohm | S06 line 8 |
| Terminal inductance | 0.11 | 0.11 to 8.98 | mH | S06 line 18 |
| Torque constant | 5.90 | 5.90 to 54.3 | mNm/A | S06 line 14 |
| Speed constant | 1620 | 1620 to 176 | rpm/V | S06 line 15 |
| Rotor inertia | 3.88 | 3.70 to 4.16 | gcm2 | S06 line 17 |
| Mechanical time constant | 19 | 18 to 19 | ms | S06 line 16 |
| No load current | 30 | 30 to 3 | mA | S06 line 6 |
| No load speed | 9630 | 8370 to 10800 | rpm | S06 line 3 |
| Max. continuous current | 840 | 840 to 113 | mA | S06 line 10 |

## 6. Behaviour / control
- Plant: J theta-ddot + b theta-dot = K i, and L di/dt + R i = V - K theta-dot (S01 eqs 3, 4). P(s) = K / ((Js+b)(Ls+R) + K^2) [rad/sec / V] (S01 eq 7). MATLAB output: `0.01 / (0.005 s^2 + 0.06 s + 0.1001)` (S01).
- State space: x = [theta-dot, i], A = [-10 1; -0.02 -2], B = [0; 2], C = [1 0], D = 0 (S01).
- Control law: ideal parallel PID on the error, C(s) = Kp + Ki/s + Kd s = (Kd s^2 + Kp s + Ki)/s (S03 eq 4). Loop: `sys_cl = feedback(C*P_motor,1)`, i.e. unity negative feedback (S03, S04).
- Final gains: Kp = 100, Ki = 200, Kd = 10 (S03). These are "all of our design requirements will be satisfied".
- Reference: a 1 rad/s step (S03), zero initial state (**inferred**, MATLAB `step` default).
- Stated result (S05): peak amplitude 1.01, overshoot 1.03 %, time of peak 0.59 s, settling time 0.257 s, final value 1.

## 7. Natural gaps and contradictions
Gaps (a model needs these, but no source states them):
1. **Derivative filter.** An ideal Kd s term is improper. MSL `PID`/`LimPID` need `Nd` (or an equivalent roll-off), and no source gives one.
2. **Actuator / driver.** No amplifier, supply voltage or voltage limit is given. u goes straight in as V. The steady state alone needs 10.01 V (derived in §8), and a step reference makes Kd s produce an unbounded initial kick. S06 has nominal voltages of 6 to 48 V, but for a different motor.
3. **Speed sensor.** No sensor type, gain, dynamics or noise is given. The unity feedback implies an ideal sensor.
4. **Load.** There is no load inertia and no load or disturbance torque; J is the rotor alone.
5. **Initial conditions and ground references** are not stated.
6. **S06 friction.** S06 gives no viscous friction constant, only the no-load current (30 mA for 110117). It also gives no load and no controller.
7. **S06 winding choice.** Nothing picks which of the 12 winding columns applies.
8. **Settling-time band.** The band for "settling time" is not defined. MATLAB's default is 2 %, which is **inferred**.

Contradictions and inconsistencies (recorded as found, not reconciled):
1. **CTMS vs maxon constants.**
   - K: 0.01 N.m/A vs 5.90 to 54.3 mNm/A (0.0059 to 0.0543 N.m/A).
   - J: 0.01 kg.m^2 vs 3.70 to 4.16 gcm2 (3.70e-7 to 4.16e-7 kg.m^2, about 25,000 times smaller).
   - L: 0.5 H vs 0.11 to 8.98 mH.
   - R: 1 Ohm vs 1.71 to 145 Ohm.

   The time-constant ordering is reversed. In CTMS, L/R = 0.5 s is slower than J/b = 0.1 s. In the maxon data, L/R = 0.064 ms is far faster than the 19 ms mechanical time constant.
2. **Stated vs computed open-loop speed.** S01 says the uncompensated motor turns at "0.1 rad/sec" for 1 V. The computed value is 0.0999 rad/s. This is a rounding in the source.
3. **Unexplained Kp change.** S03 "Tuning the gains" says "change Ki to 200", but the code also changes Kp from 75 to 100 without comment.
4. **Units.**
   - b is written "N.m.s" (the per-radian is missing).
   - Ke is written "V/rad/sec".
   - Kt is written "N.m/Amp".
   - S01 asserts that Kt = Ke "in SI units". S06 gives separate torque (mNm/A) and speed (rpm/V) constants, which agree only after conversion (see §8).
5. **"Unit step" vs "1-rad/sec step".** S01 says "unit step command" and S03 says "1-rad/sec step". They are consistent, but the unit appears only in S03.

## 8. Acceptance checks
| # | check | expected | basis |
|---|---|---|---|
| A1 | Open-loop characteristic polynomial | 0.005 s^2 + 0.06 s + 0.1001 | stated S01 (MATLAB output). Derived: (0.01 s + 0.1)(0.5 s + 1) + 0.01^2 = 0.005 s^2 + 0.06 s + 0.1 + 0.0001 |
| A2 | Open-loop steady-state speed for V = 1 V | 0.0999 rad/s (source: "0.1 rad/sec") | derived: K/(bR + K^2) = 0.01/0.1001 = 0.09990; stated as 0.1 in S01 |
| A3 | Open-loop poles | -2.0025 and -9.9975 1/s | derived: roots of A1 = (-0.06 ± sqrt(0.0036 - 0.002002))/0.01 = (-0.06 ± 0.039975)/0.01 |
| A4 | Mechanical and electrical time constants (uncoupled) | J/b = 0.01/0.1 = 0.1 s; L/R = 0.5/1 = 0.5 s | derived from S01 values. The coupled poles in A3 are close to 1/0.1 and 1/0.5 because K^2 is small |
| A5 | P-only (Kp = 100) closed-loop final value | 0.909 (a steady-state error of 9.1 %) | derived: Kp K/(bR + K^2 + Kp K) = 1/(0.1001 + 1) = 0.90901. This matches the CTMS P-only plot, which is referenced in S03 but not included in the packet |
| A6 | PID closed-loop characteristic polynomial (100/200/10) | 0.005 s^3 + 0.16 s^2 + 1.1001 s + 2; roots -23.29, -5.69, -3.02 (all real, stable) | derived: s(0.005 s^2 + 0.06 s + 0.1001) + 0.01(10 s^2 + 100 s + 200) |
| A7 | Steady-state error to a step with integral action | 0 (final value 1) | derived: C has a pole at s = 0, so the loop is type 1. Stated in S05 ("Final value: 1") and in the S03 text |
| A8 | Step metrics with PID 100/200/10 | overshoot 1.03 % (< 5 %), settling time 0.257 s (< 2 s), peak 1.01 at 0.59 s | stated S05. Reproduced by the packet author's simulation of the linear model: OS 1.028 %, ts (2 %) 0.2570 s, peak 1.0103 at 0.592 s |
| A9 | Steady-state armature current and voltage at 1 rad/s | i = b ω/K = 10 A; V = R i + K ω = 10.01 V | derived from S01 eqs 3, 4 with derivatives set to 0 |
| A10 | PID 75/1/1 is slow | slowest closed-loop pole -0.0118 1/s (time constant about 85 s), far beyond 2 s | derived: roots of 0.005 s^3 + 0.07 s^2 + 0.8501 s + 0.01. S03 states the settling "is far larger than the required settling time of 2 seconds" |
| A11 | S06 internal consistency (110117) | kE = 60/(2π·1620) = 5.895e-3 V·s/rad ≈ 5.90 mNm/A; τm = R J/kM^2 = 1.71 · 3.88e-7/(5.90e-3)^2 = 19.06 ms ≈ 19 ms; n0 ≈ kn (U - I0 R) = 1620 (6 - 0.030 · 1.71) = 9637 rpm ≈ 9630 rpm | derived from S06 lines 3, 6, 8, 14, 15, 16, 17 |
| A12 | Requirements met | ts < 2 s, OS < 5 %, e_ss < 1 % | stated S01 and S03 |

## 9. Candidate Modelica Standard Library classes
All class names below were verified by grep against `out/catalog.jsonl`, using the `"key"` field.

| role | class | parameter mapping |
|---|---|---|
| armature voltage source | `Modelica.Electrical.Analog.Sources.SignalVoltage` | input `v` = controller output |
| resistor | `Modelica.Electrical.Analog.Basic.Resistor` | R = 1 |
| inductor | `Modelica.Electrical.Analog.Basic.Inductor` | L = 0.5 |
| EMF | `Modelica.Electrical.Analog.Basic.RotationalEMF` | k = 0.01 |
| ground | `Modelica.Electrical.Analog.Basic.Ground` | - |
| rotor | `Modelica.Mechanics.Rotational.Components.Inertia` | J = 0.01 |
| friction | `Modelica.Mechanics.Rotational.Components.Damper` + `Modelica.Mechanics.Rotational.Components.Fixed` | d = 0.1 |
| speed sensor | `Modelica.Mechanics.Rotational.Sensors.SpeedSensor` | - |
| summing junction | `Modelica.Blocks.Math.Feedback` | u1 = r, u2 = w |
| controller | `Modelica.Blocks.Continuous.PID` (or `Modelica.Blocks.Continuous.LimPID` with yMax/yMin, which the sources leave unknown) | **inferred** conversion from parallel to MSL form: k = Kp = 100, Ti = Kp/Ki = 0.5 s, Td = Kd/Kp = 0.1 s; Nd not given |
| reference | `Modelica.Blocks.Sources.Step` | height = 1 |
| optional voltage limit | `Modelica.Blocks.Nonlinear.Limiter` | limits not given |
| alternative plant | `Modelica.Electrical.Machines.BasicMachines.DCMachines.DC_PermanentMagnet` | **inferred** fit. It is parameterised by VaNominal, IaNominal, wNominal, Ra, La, Jr, and so on, and none of those are stated for the CTMS motor, so the discrete R + L + EMF assembly is the closer match |
| also present | `Modelica.Blocks.Continuous.PI`, `Modelica.Mechanics.Rotational.Sensors.AngleSensor` | for PI-only or position variants (out of scope) |
