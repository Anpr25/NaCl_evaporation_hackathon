# REFERENCE (answer key): vehicle_quarter_car_suspension

**Do not place this file in `sources/`.** Citation keys:

- **S01** = `01_karahan_active_suspension_LQR_arXiv2508.02906v6.pdf`. Page numbers are PDF pages, which match the printed page numbers.
- **S02** = `02_hassan_twin_accumulator_PI_quarter_model_arXiv1706.02147v1.pdf`. Page numbers are PDF pages.
- **S03** = `03_eme171_lab02_two_dof_quarter_car.rst`. Cited by section heading.
- **S04** = `04_eme171_lab02_fig01_schematic_and_bond_graph.png`. This is Figure 1 of S03.

Anything marked **inferred** was derived or interpreted by the packet author and is not stated in a source.

## 1. System summary

1. A two-degree-of-freedom quarter-car vertical suspension. The sprung mass is the body (a quarter of the car). The unsprung mass is the wheel, tyre and axle.
2. The two masses are coupled by a suspension spring and a viscous damper in parallel. The unsprung mass rests on the road through a tyre spring. The tyre has zero or no damping in all three sources.
3. The road displacement, or road vertical velocity in S03, is an external kinematic disturbance: a step, a bump, a pothole or a random ISO profile.
4. The domain is 1-D translational mechanics. Gravity acts explicitly on both masses in S03. S01 and S02 write equations about the static equilibrium.
5. There are three independent sources, with three different vehicles and three different vocabularies: `Zs/Zus/Zr` (S01), `xs/xu/xo` (S02), and bond-graph states `p2, q6, p8, q11, vi` (S03). The sources describe active variants too (PID, LQR, twin-accumulator plus PI), and those are out of scope.

## 2. Modelling scope

- **In scope: the passive 2-DoF quarter car.** It has a sprung mass, an unsprung mass, a suspension spring, a suspension damper and a tyre spring. It is driven by a prescribed road displacement or velocity input.
  - Tyre damping is included only as a zero-valued element, because S01 states it as 0.
  - Gravity is optional. It is needed to reproduce S03's equilibrium initial conditions.
- **Parameter sets:** the three sources give three different vehicles (Section 7). A correct pipeline should **not** merge them.
  - Acceptable: pick one set and cite it, or expose all three as alternative parameter records.
  - Mixing values across sources is a failure. For example, S01 masses with S02 stiffnesses.
- **Out of scope** (described by the sources, but not the baseline):
  - S01's active actuator with two PID loops, and its LQR controller. The LQR gain matrix K is never stated, and Q is garbled in the text layer.
  - S02's twin-accumulator hydro-pneumatic branch (k2, c2, x3), its evolution-strategy optimisation, and its PI-controlled active force Fa.
  - S01's ±20 % mass uncertainty case and its band-limited-white-noise case.
  - S02's ISO class-D random road. A model may optionally include it, but it needs a noise and filter source.
  - S01 Fig. 2 (front and rear unsprung masses, half-vehicle context).
  - Tyre lift-off.

## 3. Expected parts

| id | kind | citation |
|---|---|---|
| sprungMass | translational mass (car body, quarter) | S01 p3 ("Zs is sprung mass displacement"), p4 Table 1 `ms`; S02 p6 §3.2 ("Car body is denoted as sprung mass"), p11 Table 3; S03 "Model Description" (`M`); S04 |
| unsprungMass | translational mass (wheel, tyre, axle) | S01 p3 (Zus; list of unsprung components), p4 Table 1 `mus`; S02 p6 §3.2, p11 Table 3; S03 "Model Description" (`M_u`); S04 |
| suspensionSpring | linear translational spring, body to wheel | S01 p4 Table 1 `ks`; S02 p6 §3.2, p11 Table 3 ("Frist spring stiffness"), eq. (1)-(2) p7 (`k1`); S03 "Model Description" ("linear spring and damper in parallel"); S04 (`K`) |
| suspensionDamper | linear viscous damper, body to wheel, parallel to the spring | S01 p4 Table 1 `bs`; S02 p11 Table 3 ("Frist Damping coefficient"), eq. (1)-(2) (`c1`); S03 "Model Description"; S04 (`B`) |
| tyreSpring | linear translational spring, wheel to road | S01 p4 Table 1 `kus` "Tyre stiffness"; S02 p6 ("The tire is assumed to have only the spring feature"), Table 3; S03 "Model Description"; S04 (`Kt`) |
| tyreDamper (value 0, optional) | viscous damper, wheel to road | S01 p3 ("The wheel damping ratio has been chosen as 0") and Table 1 `bus` = 0 Ns/m. Absent in S02 and S03. |
| road | prescribed-motion source (displacement or velocity) | S01 p3 (Zr), p8; S02 p6 ("The road terrain serves as an external disturbance input"), p9; S03 "Inputs" (`v_i`); S04 (`SF: Vi(t)`) |
| gravity on both masses (optional) | constant force | S03 state equations (`+Mg`, `+M_u g`); S04 (`SE:MG`, `G=9.81 M/S^2`) |
| *(out of scope)* actuator | force source between the masses | S01 Fig. 1 p3, p1 abstract; S02 eq. (6), (8) p7 (`Fa`) |
| *(out of scope)* controllers | PID ×2 and LQR (S01); PI (S02) | S01 p5 Table 2, eqs. (7)-(15); S02 p13-14 eq. (11), Table 8 |

## 4. Ports / connectors and connections

Every connector is a 1-D translational flange (position s, force f).

| # | from | to | meaning | citation |
|---|---|---|---|---|
| C1 | road (moving ground) | tyreSpring end a | tyre contacts the road | S02 p6; S03 "Model Description" ("spring between the unsprung mass and the ground"); S04 |
| C2 | tyreSpring end b | unsprungMass | tyre deflection = unsprung minus road displacement | S02 eq. (1) `kt(xo − xu)` p7; S03 state `q11` ("displacement between the unsprung mass and the ground") |
| C3 | unsprungMass | suspensionSpring end a **and** suspensionDamper end a | the spring and damper in parallel | S02 p6 ("connected ... through a spring and damper"); S03 "Model Description"; S04 |
| C4 | suspensionSpring end b **and** suspensionDamper end b | sprungMass | suspension travel = relative displacement (Zs − Zus or xu − xs) | S01 p4 (state 1 "suspension travel"); S02 eq. (1)-(2), §3.2 SWS p11; S03 `q6` |
| C5 (optional) | road | tyreDamper (d = 0) to unsprungMass | parallel to C1/C2 | S01 Table 1 p4 |
| C6 (optional) | gravity force sources | sprungMass, unsprungMass | the weight of each mass | S03 state equations; S04 |

Sign conventions:

- **S03:** downward velocity is positive ("Power flowing from the system to the ground is considered positive"; S04 arrows V, Vu, Vi point down). A positive `q6` is compression ("Outputs").
- **S01 and S02:** the sign convention is not readable from the text layer, and the figures show it only graphically. Take the directions as **inferred** from standard practice (upward positive). They are not stated in the text.

## 5. Parameters

### Set A: S01 (Karahan), Table 1, p4

| name | value | unit | citation |
|---|---|---|---|
| ms (sprung mass) | 234 | kg | S01 p4 Table 1 |
| mus (unsprung mass) | 43 | kg | S01 p4 Table 1 |
| ks (suspension stiffness) | 26000 | N/m | S01 p4 Table 1 |
| kus (tyre stiffness) | 100000 | N/m | S01 p4 Table 1 |
| bs (suspension damping) | 1544 | Ns/m | S01 p4 Table 1 |
| bus (tyre damping) | 0 | Ns/m | S01 p4 Table 1; p3 "wheel damping ratio has been chosen as 0" |
| vehicle speed | 72 | km/h | S01 p8 |
| road disturbance amplitude | 0.08 | m | S01 p8 |
| disturbance time | 1st second of simulation | s | S01 p8 |
| ms under +20 % uncertainty (out of scope) | 281 | kg | S01 p10 |
| white-noise power / sampling time (out of scope) | 1×10⁻⁵ / 0.1 | (units not stated) | S01 p12 |
| PID gains, sprung mass motion (out of scope) | Kp 3.2 x 10^5, Ki 5.24 x 10^3, Kd 3.8 x 10^6 | not stated | S01 p5 Table 2. The exponents are **inferred**: the text layer shows "105/103/106" with the superscripts flattened. |
| PID gains, suspension travel (out of scope) | Kp 160, Ki 1.27 x 10^4, Kd 0 | not stated | S01 p5 Table 2 (same caveat) |
| LQR R (out of scope) | 1 | - | S01 p6 eq. (15) |

### Set B: S02 (Hassan et al.), Table 3, p11

| name | value | unit | citation |
|---|---|---|---|
| ms (sprung mass) | 300 | kg | S02 p11 Table 3 |
| mu (unsprung mass) | 40 | kg | S02 p11 Table 3 |
| c1 ("Frist Damping coefficient") | 1000 | N.s/m | S02 p11 Table 3 |
| k1 ("Frist spring stiffness") | 15000 | N/m | S02 p11 Table 3 |
| kt (tire stiffness) | 20000 | N/m | S02 p11 Table 3 |
| c2, k2 ("Second ...", twin-accumulator only, out of scope) | 1000, 15000 | N.s/m, N/m | S02 p11 Table 3 |
| step height / time | 0.02 m at t = 2 s | m, s | S02 p9 |
| random road (optional) | V = 20 m/s, Gq(n0) = 1024e-6 m³, n0 = 0.1 m⁻¹, f0 = 0, Class D | as stated | S02 p8 |
| PI gains (out of scope) | initial 0 / 1; tuned: random 0 / 1904, step 0 / 800 | - | S02 p14 Table 8. Which row is Kp and which is Ki is **inferred** from eq. (11) order; the symbol column is empty in the text layer. |

### Set C: S03 (EME 171 Lab 2), "Constant Parameters". Stated indirectly.

| name | value | unit | citation / derivation |
|---|---|---|---|
| M (sprung mass) | 250 | kg | S03 |
| M/M_u | 5 | - | S03, so **M_u = 50 kg (derived)** |
| g | 9.81 | m s⁻² | S03; S04 |
| f_n (sprung-mass natural frequency) | 1 | Hz | S03 |
| ζ (sprung-mass damping ratio) | 0.3 | - | S03 |
| K_t/K | 10 | - | S03 |
| **K (derived)** | M(2π f_n)² = 250 × 39.478 = **9869.6** | N/m | from S03 ω_n = √(K/M) ("Time Duration and Resolution") |
| **B (derived)** | 2ζMω_n = 2 × 0.3 × 250 × 6.2832 = **942.48** | N s/m | from S03 ζ = B/(2Mω_n) |
| **K_t (derived)** | 10K = **98696** | N/m | S03 ratio |
| V_c (forward speed) | 10 | m s⁻¹ | S03 |
| L (pothole width) | 1.2 | m | S03 |
| A (pothole depth) | 0.08 | m | S03 |

## 6. Behaviour / control

**Road disturbance**

- **S01:** a disturbance of amplitude 0.08 m, applied in the 1st second, at a vehicle speed of 72 km/h (p8). The shape is shown only in Fig. 9, which is an image. The text does not say whether it is a step, a bump or a pulse.
- **S02:** a step of 0.02 m at t = 2 s (p9, Fig. 5 "Road bump displacement"). There is also a white-noise-filtered ISO Class-D random profile, eq. (9)-(10), p8.
- **S03:** a symmetric triangular (V-shaped) pothole ("Inputs"; S04).
  - The input is the road vertical velocity v_i.
  - The tyre crosses the pothole in T = L/v_c.
  - Its velocity is constant downward from T1 to T2 = T1 + T/2, then constant upward at the same speed until T3 = T1 + T, then zero.
  - v_i = v_c·dy/dx.
  - **Derived:** T = 1.2/10 = 0.12 s. |v_i| = V_c·A/(L/2) = 10 × 0.08/0.6 = **1.333 m/s**. T1 is not stated.
- **Controllers** (out of scope, recorded for completeness):
  - S01 uses two PID loops, one on sprung mass motion and one on suspension travel (p5).
  - S01 also uses an LQR controller with u = −Kx and states x1 = suspension travel, x2 = sprung mass velocity, x3 = wheel deflection, x4 = wheel vertical velocity (p4-6).
  - S02 uses PI control on the active twin-accumulator force, with unity feedback of body acceleration and a set point of zero (p13).
- **In scope:** passive only, with no controller.

## 7. Natural gaps and contradictions

### Gaps (what a model needs that the sources do not state)

1. **Initial conditions.** S01 and S02 do not state them. S03 states zero momenta and equilibrium spring deflections, to be solved by the reader ("Initial Conditions"). Nobody gives numeric values; see Section 8 for the derived values.
2. **S01 disturbance shape and duration.** Only the amplitude (0.08 m) and the onset (1st second) are in the text. The shape is in the image Fig. 9 only. S01's result tables (Tables 3-11) cannot be reproduced without it.
3. **S03 pothole entry time T1** is not given. Simulation duration and step size are left to the reader, by design ("Time Duration and Resolution").
4. **S01 equations of motion and state-space matrices** (eqs. 1-4, 7-15) are unreadable in the PDF text layer. The glyphs are lost, so a text-only pipeline must rely on S02 and S03 for the structure. The S01 LQR gain K is never stated numerically.
5. **Sign conventions** in S01 and S02 are given only in figures (images).
6. **S02 Table 3 symbol column** is empty in the text layer. The mapping of "Frist/Second" coefficients to c1/k1 and c2/k2 is **inferred** from eq. (1)-(5).
7. **Whether gravity is modelled** differs by source. S03 includes Mg explicitly. S01 and S02 do not show it in any readable way.

### Contradictions / inconsistencies between sources (recorded, NOT reconciled)

| topic | S01 | S02 | S03 |
|---|---|---|---|
| sprung mass | 234 kg | 300 kg | 250 kg |
| unsprung mass | 43 kg | 40 kg | 50 kg (derived) |
| suspension stiffness | 26000 N/m | 15000 N/m | 9869.6 N/m (derived) |
| suspension damping | 1544 Ns/m | 1000 N.s/m | 942.48 N s/m (derived) |
| tyre stiffness | 100000 N/m | 20000 N/m | 98696 N/m (derived) |
| tyre/suspension stiffness ratio | 3.85 | 1.33 | 10 (stated) |
| road input | 0.08 m, shape in figure only | 0.02 m step at 2 s | 0.08 m deep × 1.2 m pothole at 10 m/s |
| input variable | displacement Zr | displacement xo | velocity v_i |

Two things in this table are worth noting:

- S01's 0.08 m amplitude equals S03's 0.08 m pothole depth, but the inputs are different in kind.
- S02's tyre stiffness of 20000 N/m gives a static tyre deflection of about 0.167 m (Section 8). That is physically large. **Do not "fix" it.**

### Internal inconsistencies within single sources (natural, not planted)

- **S01**
  - p3: "Gur is the center of gravity of the rear sprung mass". Given the context of "front unsprung mass", "unsprung" is presumably intended.
  - p3/p4: the text says "wheel damping ratio ... 0", while Table 1 lists `bus` "Tyre damping" as a coefficient, 0 Ns/m.
  - p13: the caption of Table 9 says "parameter uncertainty", but the section is about white noise.
  - p14: the text introduces Table 11 as "sprung mass acceleration", but the caption says "sprung mass motion".
  - p14: the text says "Passive suspension has ... the shortest settling time". Table 11 shows passive as the longest (2.901 s).
  - p10: 234 × 1.2 = 280.8 kg, which the source rounds to 281 kg.
  - The PDF footer says "Copyright © JES 2024", while the header says "22-1 (2026)".
- **S02**
  - §3.2 p6 calls the passive baseline a "conventional hydro-pneumatic suspension system", but models it as a linear spring and damper.
  - The section numbering is inconsistent: "section 34"; §3.1-3.3 sit inside §6.
  - Table 6 in the text layer shows the optimal k2 "18801" in a shifted row.
- **S03**
  - "State Equations": the first equation contains `\frac{B}{M}_up_8`, which should presumably be `\frac{B}{M_u}p_8`, as in the third equation. The same pattern appears in the second equation, `\frac{1}{M}_u p_8`.
  - "Time Duration": it says "For an over damped system", yet ζ = 0.3 is underdamped.

## 8. Suggested acceptance checks

All the numbers below are derived analytically from the cited values with g = 9.81 m/s². g is from S03. S01 and S02 do not state g, so using 9.81 for them is **inferred**.

| # | check | Set A (S01) | Set B (S02) | Set C (S03) |
|---|---|---|---|---|
| A1 | static suspension deflection m_s g / k_s | 234·9.81/26000 = **0.08829 m** | 300·9.81/15000 = **0.1962 m** | 250·9.81/9869.6 = **0.2485 m** (= S03 q6(0)) |
| A2 | static tyre deflection (m_s+m_u) g / k_t | 277·9.81/100000 = **0.02717 m** | 340·9.81/20000 = **0.1668 m** | 300·9.81/98696 = **0.02982 m** (= S03 q11(0)) |
| A3 | uncoupled body frequency √(k_s/m_s)/2π | 10.54 rad/s = **1.678 Hz** | 7.071 rad/s = **1.125 Hz** | 6.283 rad/s = **1.000 Hz** (stated by S03) |
| A4 | ride rate k_s k_t/(k_s+k_t); body frequency on the ride rate | 20635 N/m; **1.495 Hz** | 8571 N/m; **0.851 Hz** | 8972 N/m; **0.953 Hz** |
| A5 | wheel-hop frequency √((k_s+k_t)/m_u)/2π | 54.13 rad/s = **8.615 Hz** | 29.58 rad/s = **4.708 Hz** | 46.60 rad/s = **7.416 Hz** |
| A6 | coupled undamped eigenfrequencies (2-DoF) | **1.489 Hz, 8.650 Hz** | **0.840 Hz, 4.767 Hz** | **0.953 Hz, 7.422 Hz** |
| A7 | body damping ratio b_s / (2√(k_s m_s)) | 1544/4933.1 = **0.313** | 1000/4242.6 = **0.236** | **0.300** (stated by S03) |
| A8 | step or pothole steady state: after the input ends, the suspension deflection returns to its static value, and the body displacement equals the final road offset | final offset = the S01 disturbance level (shape unknown) | body and wheel both rise 0.02 m | final offset 0 (pothole returns to grade); q6 → q6(0) |
| A9 | at equilibrium with gravity: the tyre force equals (m_s+m_u)g and the suspension force equals m_s g | 2717.4 N / 2295.5 N | 3335.4 N / 2943 N | 2943 N / 2452.5 N |

How the table was derived:

- **A6:** from det([[k_s/m_s − ω², −k_s/m_s], [−k_s/m_u, (k_s+k_t)/m_u − ω²]]) = 0.
- **A9:** Set A tyre force 277 × 9.81 = 2717.4 N, suspension force 234 × 9.81 = 2295.5 N; Set B 340 × 9.81 = 3335.4 N, 300 × 9.81 = 2943 N; Set C 300 × 9.81 = 2943 N, 250 × 9.81 = 2452.5 N.

**Source-stated behavioural checks** (S01, passive column). These apply only if the S01 disturbance of Fig. 9 is reproduced, so they are conditional on Gap 2:

- suspension travel: rise 1.29 s, overshoot 0.0387 m, settling 1.451 s (p9 Table 3);
- sprung mass acceleration: overshoot −55.1 m/s², settling 1.378 s (p9 Table 4);
- sprung mass motion: rise 1.138 s, overshoot 0.0567 m, settling 1.428 s (p10 Table 5).

S01 p7 also states that all passive poles lie in the left half-plane. That is consistent with A7, since the damping ratio is greater than 0.

## 9. Candidate Modelica Standard Library classes

Every class name below was verified to exist in `out/catalog.jsonl` (`"key"` field). The parameter and port names are from the catalog entries.

| role | class | key params / ports (from catalog) |
|---|---|---|
| sprung / unsprung mass | `Modelica.Mechanics.Translational.Components.Mass` | m, L; flange_a, flange_b |
| suspension spring and damper (combined) | `Modelica.Mechanics.Translational.Components.SpringDamper` | c, d, s_rel0; flange_a, flange_b |
| separate spring / damper | `Modelica.Mechanics.Translational.Components.Spring` (c, s_rel0), `...Components.Damper` (d) | flange_a, flange_b |
| tyre (with optional lift-off, out of scope) | `Modelica.Mechanics.Translational.Components.ElastoGap` | c, d, s_rel0 |
| road displacement input | `Modelica.Mechanics.Translational.Sources.Position` | s_ref (input), flange, support; exact, f_crit |
| road velocity input (S03 style) | `Modelica.Mechanics.Translational.Sources.Speed` | exists in the catalog |
| ground reference | `Modelica.Mechanics.Translational.Components.Fixed` | s0; flange |
| gravity on the masses | `Modelica.Mechanics.Translational.Sources.ConstantForce` | f_constant; flange. **inferred** usage: MSL Translational Mass has no gravity parameter in the catalog. |
| step road (S02) | `Modelica.Blocks.Sources.Step` | height, offset, startTime; y |
| pothole / arbitrary profile (S03, S01) | `Modelica.Blocks.Sources.TimeTable`, `Modelica.Blocks.Sources.CombiTimeTable`, `Modelica.Blocks.Sources.Trapezoid` | table / startTime; y |
| random road (optional) | `Modelica.Blocks.Noise.BandLimitedWhiteNoise`, `Modelica.Blocks.Noise.NormalNoise` | exist in the catalog |
| outputs | `Modelica.Mechanics.Translational.Sensors.RelPositionSensor` (s_rel = suspension travel), `...Sensors.PositionSensor`, `...Sensors.AccSensor` | flange_a, flange_b, s_rel |
| connectors | `Modelica.Mechanics.Translational.Interfaces.Flange_a`, `...Flange_b` | exist in the catalog |
| *(out of scope)* actuator / controllers | `Modelica.Mechanics.Translational.Sources.Force`, `Modelica.Blocks.Continuous.PI`, `...PID`, `...LimPID`, `Modelica.Blocks.Math.MatrixGain` | f (input); exist in the catalog |
