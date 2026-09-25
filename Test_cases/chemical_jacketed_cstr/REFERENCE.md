# REFERENCE (answer key): chemical_jacketed_cstr

This file is not ingested; it sits outside `sources/`. Citations use the file number and the section heading inside that file. For example, `[04 §Model]` means `sources/04_pid_control_exothermic_cstr_notebook.md`, heading "## Model". `[05 §5.1 T1]` means the PDF, Section 5.1, Table 1. Anything I inferred rather than found stated is marked **inferred**.

## 1. System summary

1. A well-mixed, constant-volume continuous stirred-tank reactor with an irreversible first-order exothermic reaction, A → Products, and Arrhenius kinetics [02 §Reaction Kinetics] [05 §5.1].
2. A liquid feed (flow q, concentration c_Ai/c_Af, temperature T_i/T_f) enters, and the outlet leaves at reactor conditions [02 §Model Equations…] [01 §Ideal CSTR].
3. Heat of reaction goes to a cooling jacket through UA(T_c − T) [02 §Model Equations…].
4. In the base model (02, 03, 05) the jacket/coolant temperature T_c is a prescribed input, "Primary Manipulated Variable". In 04 the jacket is a dynamic volume V_c fed with coolant flow q_c from T_cf [04 §Model].
5. File 04 closes the loop: a direct-acting, discrete-time (velocity-form) PI(D) controller measures reactor T and sets coolant flow q_c, clamped to [0, 300] L/min, with setpoint 390 K [04 §Simulation 3 …, code cell after §Bounded Control].

## 2. Modelling scope

**In scope**
- Reactor mole balance on A and energy balance, lumped (two states: c_A and T).
- The Arrhenius rate constant k(T) = k0·exp(−Ea/(R·T)).
- The heat path from reactor to jacket, UA·(T_c − T).
- Jacket energy balance: a third state T_c driven by coolant flow q_c [04 §Model]. This extends the base model; the base model (02/03/05) treats T_c as a boundary temperature.
- Feed as a fixed-state boundary: q, c_Ai, T_i.
- Reactor-temperature feedback control acting on q_c [04 §Simulation 3–4]. The open-loop case, with T_c as a manipulated input, is in 02, 03 and 05.

**Out of scope**
- Product species B, or "Products". No sources give it a balance; files 02/03/04 write "Products", not "B".
- Pressure and hydraulics, level dynamics (V is constant), agitator power, and mixing time.
- Non-ideal CSTR behaviour, RTD and dead volume, and cascades [01 §Non-ideal CSTR, §Cascades] (background only).
- The RL, CIS and MILP machinery of file 05. Only its plant model and constraints are relevant.
- The `PIDsim` class (manual/auto bumpless transfer) [04 §Simulation 5] is optional. The source calls it "try at your own risk".

## 3. Expected parts

| id | kind | citation |
|---|---|---|
| feed | boundary source: material stream at fixed q, c_Ai, T_i | [02 §Model Equations and Parameter Values] table rows "Feed flowrate / concentration / temperature"; [05 §5.1 T1] q, c_Af, T_f |
| reactor | CSTR vessel, constant volume V, well mixed, with an A→Products reaction | [02 §Description, §Model Equations…]; [01 §Ideal CSTR / Assumptions] "perfect or ideal mixing" |
| reaction_kinetics | Arrhenius first-order rate law k(T)·c_A (can be a sub-part or an equation of the reactor) | [02 §Reaction Kinetics] |
| product_outlet | material sink at reactor conditions (**inferred** as a part; the equations use outflow q at c_A, T) | [02 §Model Equations…] term q(c_Ai − c_A); [01 §Ideal CSTR] "the output composition is identical to composition of the material inside the reactor" |
| cooling_jacket | thermal capacity V_c at temperature T_c (dynamic in 04; a fixed-temperature boundary in 02/03/05) | [04 §Model] jacket energy balance and "Cooling jacket volume V_c 20 liters"; [02 table] "Coolant temperature T_c 300 K" |
| heat_transfer_wall | thermal conductance UA between reactor and jacket | [02 table] "Heat Transfer Coefficient UA 50,000 J/min/K"; [05 §5.1] "heat transfer coefficient between the reactor and the cooling jacket" |
| coolant_supply | boundary source: coolant at T_cf with commanded flow q_c | [04 §Model] table rows "Coolant feed temperature T_cf 300 K" and "Nominal coolant flowrate q_c 50 L/min, primary manipulated variable" |
| coolant_return | coolant sink (**inferred**; implied by the q_c(T_cf − T_c) term) | [04 §Model] |
| temperature_sensor | measures reactor T (**inferred** as a physical part; the source feeds T straight into the controller) | [04 code cell after §Bounded Control] `eI = Tsp - T` |
| temperature_controller | discrete velocity-form PID, direct acting, output clamped to [qc_min, qc_max] | [04 §Simulation 3, §Independent Parameters, §Setpoint Weighting, §Discrete Time Implementation, §Bounded Control] |
| setpoint | constant T_sp = 390 K | [04 code cell after §Bounded Control] `Tsp = 390` |

## 4. Ports / connectors and connections

| # | from | to | kind | citation |
|---|---|---|---|---|
| C1 | feed.outlet | reactor.inlet | material stream (volumetric flow q, c_A, T) | [02 §Model Equations…] q(c_Ai − c_A), q/V·(T_i − T) |
| C2 | reactor.outlet | product_outlet.inlet | material stream at (c_A, T) | [02 §Model Equations…]; [01 §Governing equations] eq. 4 "QC_Ao − QC_A" |
| C3 | reactor.heatPort | heat_transfer_wall.port_a | heat flow UA(T_c − T) into the reactor | [02 §Model Equations…] term UA(T_c − T) |
| C4 | heat_transfer_wall.port_b | cooling_jacket.heatPort | heat flow UA(T − T_c) into the jacket | [04 §Model] jacket balance term UA(T − T_c) |
| C5 | coolant_supply.outlet | cooling_jacket.inlet | coolant stream q_c at T_cf | [04 §Model] ρC_p q_c(T_cf − T_c) |
| C6 | cooling_jacket.outlet | coolant_return | coolant stream at T_c (**inferred**) | [04 §Model] |
| S1 | reactor T (sensor) | controller measurement | signal (K) | [04 code] `eI = Tsp - T` |
| S2 | setpoint | controller reference | signal (K) | [04 code] `Tsp = 390` |
| S3 | controller output | coolant_supply flow command q_c | signal (L/min), clamped 0…300 | [04 code] `qc = sat(qc)`, `qc_min = 0`, `qc_max = 300` |

For the open-loop variant (02/03/05), C5, C6 and S1–S3 are absent. The jacket side of C3 is then a prescribed temperature T_c, which is a manipulated input [02 table "Primary Manipulated Variable"]; [05 §5.1] "Tc is the manipulated variable", 285.0 ≤ Tc ≤ 315.0 (eq. 24).

## 5. Parameters

| name | value | unit | citation |
|---|---|---|---|
| Ea (activation energy) | 72,750 | J/gmol | [02 table], [03 table], [04 table] |
| E/R | 8750.0 | K | [05 §5.1 T1] (see contradiction X1) |
| k0 | 7.2 × 10^10 | 1/min | [02], [03], [04] tables; [05 T1] "min-1" |
| R | 8.314 | J/gmol/K | [02 table] |
| V (reactor volume) | 100 | liters | [02 table]; [05 T1] 100 L |
| ρ | 1000 | g/liter | [02 table]; [05 T1] 1000.0 g/L |
| C_p | 0.239 | J/g/K | [02 table]; [05 T1] "J/gK" |
| ΔH_r | −50,000 | J/gmol | [02 table]. Code comment says "[J/mol]" [02 §Transient Behavior code]; [05 T1] −ΔH = 5.0 × 10^4 J/mol |
| UA | 50,000 | J/min/K | [02 table]; [05 T1] "J/minK" |
| q (feed = outlet flow) | 100 | liters/min | [02 table]; [05 T1] |
| c_Ai / c_A,f (feed concentration) | 1.0 | gmol/liter | [02 table]; [05 T1] "1 mol/L" |
| T_i / T_f (feed temperature) | 350 | K | [02], [03] tables; [04] table; [05 T1]. **But** `Tf = 300.0` in [04 code cell under §Model] (see X2) |
| c_A,0 (initial concentration) | 0.5 | gmol/liter | [02], [04] tables |
| T_0 (initial temperature) | 350 | K | [02], [04] tables |
| T_c (coolant temperature, open loop) | 300 | K | [02 table] "Primary Manipulated Variable" |
| T_c bounds (open loop, file 05) | 285.0 … 315.0 | K | [05 eq. 24] |
| state constraints (file 05) | 0.0 ≤ c_A ≤ 1.0; 345.0 ≤ T ≤ 355.0 | mol/L; K | [05 eqs. 22–23] |
| T_cf (coolant feed temperature) | 300 | K | [04 table] |
| q_c nominal (coolant flow) | 50 | L/min | [04 table] |
| V_c (jacket volume) | 20 | liters | [04 table] |
| T_sp | 390 | K | [04 code, §Simulation 3] |
| kp, ki, kd | 40, 80, 0 | — (units not stated; see G5) | [04 code, §Simulation 3] |
| β, γ (setpoint weights) | 0, 0 | — | [04 code; §Setpoint Weighting] |
| dt (control sample time) | 0.05 | min (**inferred** from time in min) | [04 code] |
| q_c limits | 0 … 300 | L/min (**inferred** unit) | [04 code] `qc_min = 0`, `qc_max = 300` |
| q_c initial | 150 | L/min | [04 code] `qc = 150` |
| T_c initial (jacket) | = T_cf = 300 | K | [04 code] `IC = [C0,T0,Tcf]` |
| sampling time (file 05 RL) | 6 | seconds | [05 §6.3] |
| disturbance bound on c_Af, T_f | \|w\| ≤ [0.1, 2.0]^T | mol/L, K | [05 §6 intro] |
| simulation horizon | 10 (02/03), 8 (04) | min | [02 code] `t_final = 10.0`; [04 code] `tf = 8.0` |

## 6. Behaviour / control

- Base ODEs [02 §Model Equations…]:
  - dc_A/dt = (q/V)(c_Ai − c_A) − k(T)c_A
  - dT/dt = (q/V)(T_i − T) + (−ΔH_R/(ρC_p))k c_A + (UA/(VρC_p))(T_c − T)
- File 05 states the same pair [05 §5.1], with E/R in place of Ea/R.
- Jacket ODE [04 §Model]: dT_c/dt = (q_c/V_c)(T_cf − T_c) + (UA/(ρC_pV_c))(T − T_c)
- Qualitative open-loop behaviour. 02 says the interactive cooling-temperature study shows "a thermal runaway, sustained osciallations, and low and high conversion steady states" [02 §Interactive Simulation]. The exercise asks to find stable, oscillatory and thermal-runaway regimes for T_c from 290 to 310 K [02 §Suggested Exercises]. Steady states are nullcline intersections [02 §Nullclines]. Wikipedia: "CSTRs are known to be one of the systems which exhibit complex behavior such as steady-state multiplicity, limit cycles, and chaos" [01 §Modeling non-ideal flow].
- Without cooling, "the reactor will reach an operating temperature of 500K" [04 §Simulation 1]. A sweep of q_c shows "a clear bifurcation" near 153.7–153.8 L/min [04 text after the second sweep].
- Control objective: "stable operation of the reactor at a high conversion steady state but with an operating temperature below 400 K, an operating condition that does not appear to be possible without feedback control" [04]. "PID control is used to stabilize an otherwise unstable steady state" [04 §Simulation 4].
- Control law. It is direct acting: "a positive excursion of the reactor temperature T above the setpoint T_sp is compensated by an increase in coolant flow" [04 §Simulation 3].
  - Velocity form: Δq_c = −[k_P(e_P,k − e_P,k−1) + k_I·dt·e_I,k + k_D(e_D,k − 2e_D,k−1 + e_D,k−2)/dt], with e_P = βT_sp − T, e_I = T_sp − T and e_D = γT_sp − T [04 §Discrete Time Implementation].
  - Output saturation: `max(qc_min, min(qc_max, qc))` [04 code].
- File 05 control objective: keep 345 ≤ T ≤ 355 K and 0 ≤ c_A ≤ 1 using T_c ∈ [285, 315] K [05 §5.1]. File 05 also reports an economic optimum steady state x_s = [0.41, 354.98]^T, u_s = 298.68 [05 §6.4].

## 7. Natural gaps and contradictions

**Contradictions (all present in the sources as retrieved; none planted):**
- **X1. Activation energy:** Ea = 72,750 J/gmol with R = 8.314 [02/03/04], so Ea/R = 8750.30 K, against E/R = 8750.0 K [05 T1]. The difference is small but measurable: at T_c = 298.68 K the middle steady state is T = 355.09 K with Ea/R and 354.99 K with E/R = 8750.0. File 05's reported x_s = [0.41, 354.98] matches its own 8750.0 value.
- **X2. Feed temperature in file 04:** the parameter table says "Feed temperature T_f 350 K" but the code says `Tf = 300.0 # Inlet feed temperature [K]`. The notebook's own claims (no-cooling ≈ 500 K; bifurcation near 153.7 L/min; setpoint 390 K reachable) hold only with 300 K (see §8). Files 02/03/05 all say 350 K, but those describe the open-loop model without a dynamic jacket.
- **X3. Energy-balance flow symbol:** the balances in 02/03/04 write wC_p(T_i − T) with an undefined w (mass flow). The normalised forms and code use q/V (equivalent to w = ρq). The Pyomo code in [03 §Pyomo Model] writes `q*rho*Cp*(Ti - T)` explicitly.
- **X4. Sign/term confusion in the 04 text:** "At cooling flowrates less than 153.7 liters/minute, the reactor goes to a high conversion steady state … Coolant flowrates less than 153.8 liters/minute result in uneconomic operation at low conversion." Both sentences say "less than"; the second must mean "greater than".
- **X5. Bounded-control formula in 04:** the text formula is `max(q_c,min, max(q_c,max, q_c))`, which is wrong (it can never cap at the maximum). The code uses `max(qc_min, min(qc_max, qc))`.
- **X6. Sweep values:** 02 sweeps T_c ∈ {295, 300, 305} and says "plus or minus change of 5 K". 03 has the same sentence but sweeps {290, 300, 305}.
- **X7. Model assumptions:** Wikipedia's ideal-CSTR assumptions list "steady state", "closed boundaries" and "isothermal conditions" [01 §Assumptions], which contradicts the dynamic, non-isothermal jacketed model. Its symbols are Q, C_Ao and τ; the notebooks use q, c_Ai, c_A,f and T_i/T_f interchangeably, and 05 uses c_Af.
- **X8. Unit typos in 05:** the text says "Tf (L)" for feed temperature; the table gives K. The PDF's Table 1 extracts as scrambled columns (a PDF-table extraction stress test).
- **X9. Units of ΔH:** J/gmol (tables) against J/mol (code comments, 05). These are equivalent, but the spelling differs.
- **X10. Licence:** the repo README says BY-NC-SA, while LICENSE-TEXT.txt and the notebook header say BY-NC-ND. This affects the packet, not the model.

**Gaps (not stated by any source, but a model needs them):**
- **G1.** Jacket dynamics in the base model. 02/03/05 treat T_c as an instantly set temperature, with no jacket volume. Only 04 gives V_c = 20 L. Coolant ρ and C_p are not given separately; 04's jacket equation reuses the reactor ρ and C_p.
- **G2.** Initial conditions. 05 gives none; its RL episodes sample initial states. The jacket initial temperature in 04 is only in code (`IC = [C0,T0,Tcf]`). The controller's initial output (150) and its initial error history are in code only.
- **G3.** Product B. There is no product species balance, no molar mass and no stoichiometry beyond "A → Products".
- **G4.** Units are not SI throughout: L, min and gmol. The model needs conversion (e.g. V = 0.1 m³, q = 1.667e-3 m³/s, k0 = 1.2e9 1/s, UA = 833.3 W/K, C_p = 239 J/(kg·K)). These conversions are **inferred**, not stated.
- **G5.** Controller gain units are never stated (kp = 40 and ki = 80 are in L/min per K and L/min per K·min, **inferred**). 04 states no derivative filter, no anti-windup (beyond clamping) and no sensor dynamics or measurement noise.
- **G6.** Pressure, level and density changes: the only coverage is the constant-density assumption in [01]. The claimed "significant pressurization" at 500 K [04] is not modelled.
- **G7.** The coolant actuator (valve/pump) and its dynamics are absent. q_c is applied instantly.
- **G8.** Mixing time is not given, so the perfect-mixing validity check "residence time 5–10 times the mixing time" [01 §Non-ideal CSTR] cannot be evaluated.

## 8. Suggested acceptance checks

These are derived from cited numbers unless marked as stated by a source. I recomputed the numeric results (scipy `solve_ivp`, rtol 1e-10, or `odeint` as in the notebooks).

1. **Residence time** τ = V/q = 100 L / 100 L/min = **1.0 min** [01 §Governing equations τ = V/Q; 02 table].
2. **Rate constant at feed temperature:** k(350 K) = 7.2e10·exp(−72750/(8.314·350)) = **0.99907 1/min**. Other points: k(300) = 0.01549, k(400) = 22.74. That is 3.2 orders of magnitude between 300 and 400 K, consistent with "three orders of magnitude" [02 §Reaction Kinetics text].
3. **Isothermal first-order conversion at 350 K:** c_A = c_Ai/(1 + kτ) [01 §Outlet Concentration table, n=1] = 1/(1 + 0.99907) = **0.5002 gmol/L**, i.e. X ≈ 50.0 %. This matches (to 3 s.f.) the stated initial state c_A,0 = 0.5, T_0 = 350.
4. **Adiabatic temperature rise:** (−ΔH)c_Ai/(ρC_p) = 50,000·1.0/(1000·0.239) = **209.2 K**.
   - With T_f = 300 K and no cooling (q_c = 0 in 04), T → 300 + 209.2·X ≈ **509.0 K** (simulated). This is consistent with 04's stated "500K".
   - With T_f = 350 K it would be ≈ 559 K, which supports X2.
5. **Multiple steady states at T_c = 300 K, T_i = 350 K (open loop).** Setting both derivatives to zero with c_A = c_Ai/(1 + k(T)τ) gives three steady states:
   - (c_A, T) = (0.8775, 324.46 K): stable focus.
   - (0.4989, 350.08 K): saddle.
   - (0.2092, 369.67 K): unstable focus.

   The stated initial condition (0.5, 350) lies next to the saddle. In simulation it goes to the low-conversion state, T(10 min) ≈ 324.5 K.
6. **Coolant-temperature regimes (open loop, from (0.5, 350), 10 min):**

   | T_c | Result |
   |---|---|
   | 290 K | stable, T ≈ 312.65 K, c_A ≈ 0.952 |
   | 295 K | stable, T ≈ 317.7 K |
   | 305 K | single unstable focus (eigenvalues 0.298 ± 3.42i), so sustained oscillation of T between ≈ 362 and 406 K after the transient |
   | 310 K | stable high-conversion state, T ≈ 383.9 K, c_A ≈ 0.099 |

   The first peak at T_c = 305 is ≈ 441 K. This matches the behaviour classes stated in [02 §Interactive Simulation / §Suggested Exercises].
7. **File 05 steady state (stated):** x_s = [0.41, 354.98], u_s = T_c = 298.68 K [05 §6.4]. Recomputed with E/R = 8750.0: (0.413, 354.99 K), an unstable saddle. A model built with Ea/R = 8750.30 gives 355.09 K. Use a tolerance of ±0.2 K, or flag X1.
8. **Cooling-flow bifurcation (04, T_f = 300 K, jacket dynamic, IC (0.5, 350, 300), 8 min):**
   - q_c ≤ 153.5 L/min: high-conversion, hot state, T(8) ≈ 408 K, c ≈ 0.027.
   - q_c ≥ 153.75 L/min: low-conversion state, T ≈ 302 K, c ≈ 0.98.
   - The source states 153.7/153.8 L/min. With tight tolerances I get the threshold at ≈ 153.53 L/min. The threshold depends on the integrator because the initial condition is near a separatrix, so use a band of 153–154 L/min.
9. **Closed-loop PID (04 settings: T_sp = 390, kp = 40, ki = 80, kd = 0, β = γ = 0, dt = 0.05, q_c ∈ [0, 300], q_c(0) = 150, T_f = 300 K):**
   - T(8 min) = **390.0 K**; q_c → **259.47 L/min**; c_A → 0.0715 (X ≈ 92.8 %); T_c → 340.17 K.
   - Peak T ≈ 449 K, and q_c saturates at both limits during the transient.
   - Analytical steady state at T = 390: k = 12.978 1/min, c = 1/(1 + k) = 0.07154, T_c from dT/dt = 0 gives 340.17 K, and q_c = UA(T − T_c)/(ρC_p(T_c − T_cf)) = **259.47 L/min**.
   - **With the table's T_f = 350 K** the required q_c is 947.8 L/min, above q_c,max = 300. So the setpoint is unreachable; the simulation saturates at 300 L/min with T ≈ 414 K. This is the decisive test for X2.
10. **Stated requirement check:** closed-loop conversion > 80 % at T below 400 K is achievable [04 §Simulation 1 objective, §Simulation 4 Q1]; check 9 satisfies it (92.8 % at 390 K).
11. **Sign check:** the controller must be direct acting, so q_c rises when T > T_sp [04 §Simulation 3].

## 9. Candidate Modelica classes

The harvested catalog is `out/catalog.jsonl`: 1402 entries, libraries `Modelica` and `SpecAlive`.

**There is no reactor, CSTR, reaction-kinetics or Arrhenius class in the catalog.** A search of keys for "react", "kinet", "CSTR", "Chemical", "stirr" and "jacket" returned only `ReactivePowerSensor` (electrical, irrelevant). The reactor, with its mole and energy balances and k(T), must come from the template or synthesis tier, as a custom model with equations. The closest SpecAlive vessel, `SpecAlive.Vessels.CooledVessel` ("Vessel with a commanded cooling duty"), has no reaction and would need extension (**inferred** fit).

These classes are confirmed present in the catalog:

| role | class | notes |
|---|---|---|
| reactor thermal mass (if split into thermal + custom kinetics) | `Modelica.Thermal.HeatTransfer.Components.HeatCapacitor` | C = VρC_p = 23,900 J/K (**inferred**) |
| UA wall | `Modelica.Thermal.HeatTransfer.Components.ThermalConductor` | parameter `G` = UA; ports `port_a`, `port_b` |
| alternative UA wall | `Modelica.Thermal.HeatTransfer.Components.Convection` | |
| prescribed coolant temperature (open loop, 02/03/05) | `Modelica.Thermal.HeatTransfer.Sources.PrescribedTemperature` / `FixedTemperature` | |
| reaction heat injection | `Modelica.Thermal.HeatTransfer.Sources.PrescribedHeatFlow` | driven by (−ΔH)Vk c_A from the custom kinetics block |
| heat-port interface | `Modelica.Thermal.HeatTransfer.Interfaces.HeatPort_a` | |
| T measurement | `Modelica.Thermal.HeatTransfer.Sensors.TemperatureSensor` | |
| controller (continuous approximation) | `Modelica.Blocks.Continuous.LimPID` | params `k`, `Ti`, `Td`, `yMax`, `yMin`, `wp`, `wd`; ports `u_s`, `u_m`, `y`. Direct action needs a negative `k` or swapped inputs (**inferred**). wp = β = 0 and wd = γ = 0 map directly. |
| alternatives | `Modelica.Blocks.Continuous.PID`, `.PI`, `.Integrator`; `Modelica.Blocks.Nonlinear.Limiter`; `Modelica.Blocks.Math.Feedback`, `.Gain` | |
| discrete 0.05-min controller (faithful to 04) | `Modelica.Blocks.Discrete.Sampler`, `Modelica.Blocks.Discrete.ZeroOrderHold` | |
| setpoint / expressions | `Modelica.Blocks.Sources.Constant`, `.Step`, `.RealExpression` | |
| coolant stream (jacket as a fluid volume) | `Modelica.Thermal.FluidHeatFlow.Sources.VolumeFlow`, `.Sources.Ambient`, `.Components.Pipe` (with heat port), `.Components.OpenTank` | `Pipe` with a heat port could represent the V_c = 20 L jacket (**inferred**) |
| full-fluid alternative | `Modelica.Fluid.Vessels.ClosedVolume` (has `heatPort`, `V`), `Modelica.Fluid.Sources.MassFlowSource_T` | Needs a Medium. Species A as a trace substance `C` is possible but heavyweight (**inferred**) |
| SpecAlive boundaries | `SpecAlive.Sources.FixedSupply` (feed), `SpecAlive.Sources.Drain` (outlet), `SpecAlive.Interfaces.Inlet/Outlet` | |

`Modelica.Thermal.FluidHeatFlow.Components.HeatedPipe` was checked and is **not** in the catalog.
