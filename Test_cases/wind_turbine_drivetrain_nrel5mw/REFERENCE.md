# REFERENCE (answer key) — wind_turbine_drivetrain_nrel5mw

This file is the answer key. It is **not** ingested. Citations use the form `NN:Lx`,
meaning file `sources/NN_*` at line x. The PDF (06) is cited as `06:p.<journal page>`
(journal page 53 = PDF page 1). Anything marked **inferred** is not stated by any
source. Numbers under "derived" are computed from values the sources state; the
arithmetic is shown.

## 1. System summary

1. The system is the NREL 5 MW land-based reference wind turbine, as modelled in OpenFAST (ElastoDyn + ServoDyn) and driven by a Bladed-style controller DLL (02:L2, 02:L7, 02:L28, 02:L86).
2. The drivetrain has a rotor (hub + 3 blades) on a torsionally flexible shaft with a spring and a damper, a 97:1 gearbox at 100 % efficiency, and a generator inertia on the high-speed shaft (HSS) (01:L13–14, 01:L84, 01:L86, 01:L123–126).
3. The generator is a torque actuator commanded by the controller. Generator efficiency is 94.4 % (02:L30, 04:L81).
4. Two controllers are documented. (a) The baseline NREL 5MW DISCON (03) uses variable-speed torque control over regions 1 / 1½ / 2 / 2½ / 3 plus a gain-scheduled PI collective pitch loop. (b) ROSCO (04, 05, 06) uses TSR-tracking PI torque control with a setpoint smoother and gain-scheduled PI pitch control.
5. Rated power is 5 MW (05:L22, 04:L88). Rated rotor speed is 1.26711 rad/s (05:L16). The generator speed reference is 122.9096 rad/s (03:L77, 04:L67).

## 2. Modelling scope

- **In scope:** the rotational drivetrain (rotor inertia, LSS torsional spring-damper, gearbox, generator inertia), the generator torque and electrical power (via efficiency), and the **generator-torque controller** in the baseline DISCON form (03:L384–407). That form includes the speed low-pass filter (03:L355–360), the torque saturation and the torque-rate limit.
- **Aerodynamic rotor torque is a declared input / boundary condition.** It is not modelled. The sources define it through Cp(λ, β) (06:p.57 Eq. 3), but the Cp table `Cp_Ct_Cq.NREL5MW.txt` (04:L127, 05:L11) is not in the packet.
- **Blade pitch control: OUT of the required scope.** The aero torque is prescribed, so a pitch command has no physical path back to the drivetrain. However, the baseline torque law switches to region 3 when the pitch command reaches `VS_Rgn3MP` (03:L94, 03:L384). A faithful torque controller therefore needs a **blade-pitch signal input**, declared as a boundary input. The PI pitch-loop parameters (03:L71–77, 03:L450–489) are listed in §5 for an optional extension.
- Out of scope: tower, blades' flexibility, yaw, HSS brake (`HSSBrMode = 0`, 02:L56), wind-speed estimator, IPC, shutdown, startup.

## 3. Expected parts

| id | kind | citation |
|---|---|---|
| rotor | rotational inertia (hub + blades, about the rotor axis) | 05:L15 (`rotor_inertia`); 01:L84 (HubIner, hub only); 04:L125 (WE_Jtot) |
| aeroTorque | torque source, external input (boundary) | 06:p.57 Eq. 2–3; 01:L163 (`RotTorq` output) |
| lss | torsional spring + damper (drivetrain flexibility) | 01:L13 (DrTrDOF), 01:L125–126 |
| gearbox | ideal gear, ratio 97, efficiency 100 % | 01:L123–124; 04:L124 |
| generatorInertia | rotational inertia about the HSS | 01:L14 (GenDOF), 01:L86 |
| generator | torque actuator + efficiency (electrical power output) | 02:L28–30; 02:L116–117 (GenPwr, GenTq); 04:L81 |
| genSpeedSensor | HSS speed measurement (the controller's input signal) | 03:L138 (`GenSpeed = avrSWAP(20)`); 01:L151 |
| speedFilter | first-order (single-pole) low-pass filter, 1.570796 rad/s | 03:L58, 03:L355–360; 04:L11, 04:L38 |
| torqueController | piecewise torque law, regions 1 / 1½ / 2 / 2½ / 3 | 03:L384–394 |
| torqueSaturation | max-torque clamp + torque-rate limiter | 03:L399–407 |
| pitchInput | blade-pitch signal input (used by the region-3 switch) | 03:L135, 03:L384 |
| pitchController (optional, out of scope) | gain-scheduled PI + angle and rate limits | 03:L450–489; 04:L57–69 |

## 4. Ports / connectors and connections

| from | to | kind | citation |
|---|---|---|---|
| aeroTorque.flange | rotor.flange_a | rotational flange (aero torque τ_a on the LSS side) | 06:p.57 Eq. 2 (τ_a acts on the rotor); **inferred** placement |
| rotor.flange_b | lss.flange_a | rotational flange | 01:L125 ("Drivetrain torsional spring"); **inferred** that the spring sits between rotor and gearbox (side not stated, see §7) |
| lss.flange_b | gearbox.flange_a (LSS side) | rotational flange | 01:L124; 01:L150 ("Low-speed shaft and high-speed shaft speeds") |
| gearbox.flange_b (HSS side) | generatorInertia.flange_a | rotational flange | 01:L86 ("about HSS") |
| generatorInertia.flange_b | generator (electrical torque, reaction to ground) | rotational flange | 03:L425 ("Demanded generator torque") |
| HSS speed | genSpeedSensor → speedFilter.u | real signal, rad/s | 03:L59, 03:L138, 03:L360 |
| speedFilter.y (GenSpeedF) | torqueController.u | real signal | 03:L384–393 |
| pitchInput (PitCom(1)) | torqueController (region-3 switch) | real signal, rad | 03:L304, 03:L384 |
| torqueController.y | torqueSaturation.u | real signal, N·m | 03:L399–407 |
| torqueSaturation.y (LastGenTrq) | generator torque command (avrSWAP(47)) | real signal, N·m (HSS side) | 03:L413, 03:L425 |
| generator | P_el = GenEff · τ_g · ω_g | electrical power output | 04:L81 ("mechanical power -> electrical power"); formula **inferred** |
| (optional) speedFilter.y | pitchController → avrSWAP(45) | real signal | 03:L456–473, 03:L520 |
| ServoDyn ↔ DLL | swap-array interface (`DISCON.IN`, `DISCON`) | Bladed interface | 02:L86–89 |

## 5. Parameters

Drivetrain and generator (01, 02):

| name | value | unit | citation |
|---|---|---|---|
| GBoxEff | 100 | % | 01:L123 |
| GBRatio | 97 | - | 01:L124 (also 04:L124 `97.0`) |
| DTTorSpr | 867637000 | N-m/rad | 01:L125 |
| DTTorDmp | 6215000 | N-m/(rad/s) | 01:L126 |
| GenIner | 534.116 | kg m^2 (about HSS) | 01:L86 |
| HubIner | 115926 | kg m^2 | 01:L84 |
| HubMass | 56780 | kg | 01:L83 |
| rotor_inertia | 38677040.613 | kg m^2 | 05:L15 |
| WE_Jtot | 43702538.05700 | kg m^2 (incl. blades, hub, generator cast to LSS) | 04:L125 |
| TipRad / HubRad | 63 / 1.5 | m | 01:L46–47 |
| RotSpeed (initial) | 12.1 | rpm | 01:L34 |
| BlPitch(1..3) (initial) | 0 | deg | 01:L29–31 |
| GenEff | 94.4 | % | 02:L30; 04:L81 (`94.40000`) |
| VSContrl / PCMode | 5 / 5 (Bladed-style DLL) | - | 02:L28, 02:L7 |
| rated_rotor_speed | 1.26711 | rad/s | 05:L16 |
| rated_power | 5000000. | W | 05:L22 |
| v_min / v_rated / v_max | 3.0 / 11.4 / 25.0 | m/s | 05:L17–19 |

Baseline torque controller (03):

| name | value | unit | citation |
|---|---|---|---|
| CornerFreq | 1.570796 | rad/s | 03:L58 |
| VS_CtInSp | 70.16224 | rad/s | 03:L88 |
| VS_Rgn2Sp | 91.21091 | rad/s | 03:L93 |
| VS_Rgn2K | 2.332287 | N-m/(rad/s)^2 | 03:L92 |
| VS_RtGnSp | 121.6805 | rad/s | 03:L95 |
| VS_RtPwr | 5296610.0 | W | 03:L96 |
| VS_SlPc | 10.0 | % | 03:L99 |
| VS_MaxTq | 47402.91 | N-m | 03:L91 |
| VS_RtTq (in comment) | 43.09355 | kNm | 03:L91 |
| VS_MaxRat | 15000.0 | N-m/s | 03:L90 |
| VS_Rgn3MP | 0.01745329 | rad | 03:L94 |
| VS_DT | 0.000125 | s | 03:L89 |

Baseline pitch controller (optional) (03):

| name | value | unit | citation |
|---|---|---|---|
| PC_RefSpd | 122.9096 | rad/s | 03:L77 |
| PC_KP | 0.01882681 | s | 03:L73 |
| PC_KI | 0.008068634 | - | 03:L71 |
| PC_KK | 0.1099965 | rad | 03:L72 |
| PC_MinPit / PC_MaxPit | 0.0 / 1.570796 | rad | 03:L76, 03:L74 |
| PC_MaxRat | 0.1396263 | rad/s | 03:L75 |
| PC_DT | 0.000125 | s | 03:L70 |

ROSCO values (04, 05), for the contradiction checks:

| name | value | unit | citation |
|---|---|---|---|
| VS_ControlMode | 2 (WSE TSR tracking) | - | 04:L13 |
| VS_ConstPower | 1 | - | 04:L14 |
| VS_Rgn2K | 2.31055e+00 | (unit not stated) | 04:L87 |
| VS_RtPwr | 5.00000e+06 | W | 04:L88 |
| VS_RtTq | 4.30935e+04 | Nm | 04:L89 |
| VS_RefSpd | 122.90967 | rad/s | 04:L90 |
| VS_MaxTq | 4.74029e+04 | Nm | 04:L84 |
| VS_MaxRat | 4.00000e+04 | Nm/s | 04:L83 (05:L21 `40000.`) |
| VS_MinOMSpd | 34.64286 | rad/s | 04:L86 |
| VS_KP / VS_KI | -6.97771e+02 / -1.04507e+02 | - / s | 04:L92–93 |
| VS_TSRopt | 7.50000 | - | 04:L94 |
| PC_RefSpd | 122.9096700000 | rad/s | 04:L67 |
| PC_MaxRat | 0.174500000000 | rad/s | 04:L65 (05:L20 `0.1745`) |
| PC_MaxPit | 1.570000000000 | rad | 04:L63 |
| PC_Switch | 0.017450000000 | rad | 04:L69 |
| PC_GS_KP / PC_GS_KI | 30-entry tables, negative | s / - | 04:L57–60 |
| F_LPFCornerFreq | 1.57080 | rad/s | 04:L38 |
| WE_BladeRadius | 63.000 | m | 04:L120 |
| WE_RhoAir | 1.225 | kg m^-3 | 04:L126 |
| bld_edgewise_freq | 6.2831853 | rad/s | 05:L23 |

## 6. Behaviour / control — baseline torque law (03)

Signals and parameters are on the HSS side, in rad/s and N·m. The speed ω is the filtered speed `GenSpeedF`:
- Filter: `Alpha = EXP((LastTime - Time)*CornerFreq)`, `GenSpeedF = (1-Alpha)*GenSpeed + Alpha*GenSpeedF` (03:L355, 03:L360).
- **Region 3**, if `GenSpeedF >= VS_RtGnSp` **or** `PitCom(1) >= VS_Rgn3MP`: `GenTrq = VS_RtPwr/GenSpeedF`, i.e. constant power (03:L384–385).
- **Region 1**, else if `GenSpeedF <= VS_CtInSp`: `GenTrq = 0` (03:L386–387).
- **Region 1½**, else if `GenSpeedF < VS_Rgn2Sp`: `GenTrq = VS_Slope15*(GenSpeedF - VS_CtInSp)` (03:L388–389).
- **Region 2**, else if `GenSpeedF < VS_TrGnSp`: `GenTrq = VS_Rgn2K*GenSpeedF^2` (03:L390–391).
- **Region 2½**, else: `GenTrq = VS_Slope25*(GenSpeedF - VS_SySp)`, the induction-generator line (03:L392–393).
- The code computes these internal constants itself (03:L174–181): `VS_SySp = VS_RtGnSp/(1+0.01*VS_SlPc)`, `VS_Slope15 = VS_Rgn2K*VS_Rgn2Sp^2/(VS_Rgn2Sp-VS_CtInSp)`, `VS_Slope25 = (VS_RtPwr/VS_RtGnSp)/(VS_RtGnSp-VS_SySp)`, and `VS_TrGnSp = (VS_Slope25 - SQRT(VS_Slope25*(VS_Slope25-4*VS_Rgn2K*VS_SySp)))/(2*VS_Rgn2K)`.
- Then `GenTrq = MIN(GenTrq, VS_MaxTq)`, and the rate is limited to ±`VS_MaxRat` (03:L399–407). The controller runs only when at least `VS_DT` has elapsed (03:L379). It is a **sampled / discrete** controller.
- The pitch PI loop is optional: `GK = 1/(1+PitCom(1)/PC_KK)`, `SpdErr = GenSpeedF - PC_RefSpd`, and the integral is saturated by the pitch limits. The command is `GK*PC_KP*SpdErr + GK*PC_KI*IntSpdErr`, clamped to [PC_MinPit, PC_MaxPit], with the rate limited to ±PC_MaxRat (03:L450–489).
- Region definitions in prose, and how the two controllers differ: region 1 is below cut-in; in region 1.5 "the traditional NREL 5 MW reference controller" uses "a linear transition from no generator torque to the minimum optimal generator torque" (06:p.55). In region 2 the pitch is fixed and a square law or TSR tracking is used. In region 2.5 the NREL 5 MW controller uses "a linear transition and switching logic". In region 3 the pitch regulates speed and the torque is constant or gives constant power (06:p.56–57). The K·ω² law is Eq. 17 and the above-rated torque is Eq. 21 (06:p.60–61).
- ROSCO switches to above-rated torque "when the blades are pitched beyond an offset, denoted by PC_Switch" (06:p.61). The file uses `VS_ControlMode = 2` (TSR tracking), so `VS_Rgn2K` is unused there (04:L13, 04:L87).

## 7. Natural gaps and contradictions

**Gaps: things a model needs that the sources do not state.**
- G1. **Rotor inertia is not in the ElastoDyn deck.** It follows from the blade files, which are not in the packet. The only value is `rotor_inertia: 38677040.613` in 05:L15, and its unit `[kg m^2]` sits only in a YAML comment. (The YAML adapter drops comments, so the unit may be lost at ingest.)
- G2. **Which shaft `DTTorSpr` / `DTTorDmp` refer to (LSS or HSS) is not stated** (01:L125–126). HSS compliance, gearbox inertia and the separate LSS/HSS inertias are not given.
- G3. **The aerodynamic torque / Cp surface is absent.** Cp,max is not stated, so K in Eq. 17 (06:p.60) cannot be checked independently, even though λ_opt = 7.5 (04:L94), ρ = 1.225 (04:L126) and R = 63 (04:L120) are given.
- G4. **There is no generator electrical model.** The Thevenin / induction fields are `9999.9` placeholders and apply only when `VSContrl = 0` (02:L29, 02:L42–54). The generator must be an ideal torque source with an efficiency. Torque-actuator dynamics are not given.
- G5. **Placeholder trap.** The simple-VS fields `VS_RtGnSp`, `VS_RtTq`, `VS_Rgn2K`, `VS_SlPc` = `9999.9` (02:L37–40) are unused because `VSContrl = 5`. They must not be taken as parameters.
- G6. **Timing is not fixed.** `DT`/`DLL_DT` = "default" (02:L5, 02:L89), and the ElastoDyn DT = "DEFAULT" (01:L6). The controller interval 0.000125 s carries the comment `JASON:THIS CHANGED FOR ITI BARGE: 0.0001` in this land deck (03:L70, 03:L89).
- G7. The region-3 switch uses the **commanded** pitch `PitCom(1)` (03:L384). Without the pitch loop, the source gives no value for that input.
- G8. The initial state is given only as `RotSpeed` 12.1 rpm (01:L34) and pitch 0 (01:L29–31). This is an initial condition, not a stated rated value.

**Contradictions: recorded, not reconciled.**
- C1. **Region-2 gain.** `VS_Rgn2K` = 2.332287 N-m/(rad/s)^2 (03:L92), vs 2.31055e+00 with no unit (04:L87, ≈0.93 % lower). The ServoDyn deck gives the unit of `VS_Rgn2K` as N-m/**rpm**^2 (02:L39).
- C2. **"Rated generator speed".** `VS_RtGnSp` = 121.6805 rad/s, "chosen to be 99% of PC_RefSpd" (03:L95), vs `VS_RefSpd` = 122.90967 "Rated generator speed" (04:L90).
- C3. **Rated power.** `VS_RtPwr` = 5296610.0 W, "generator power ... 5MW divided by ... 94.4%" (03:L96), vs `VS_RtPwr` = 5.00000e+06, "Wind turbine rated power" (04:L88).
- C4. **Max torque rate.** 15000.0 N-m/s (03:L90) vs 4.00000e+04 (04:L83) and `40000.` (05:L21).
- C5. **Max pitch rate.** 0.1396263 rad/s (03:L75) vs 0.1745 (04:L65, 05:L20).
- C6. **Pitch gains.** The gains are positive single values with a GK schedule (03:L71–73), vs negative 30-point tables (04:L59–60). The WES paper says kp and ki "are negative" (06:p.60).
- C7. **Minimum / cut-in generator speed.** `VS_CtInSp` = 70.16224 rad/s (03:L88) vs `VS_MinOMSpd` = 34.64286 (04:L86).
- C8. **Torque control law.** The baseline uses the piecewise K·ω² law (03). ROSCO uses TSR-tracking PI (04:L13), and region 1.5 uses a PI controller in ROSCO but a linear ramp in the baseline (06:p.55).
- C9. **Inertia in the plant equation.** Eq. 2 calls J "the rotor inertia" (06:p.57), while ROSCO uses `WE_Jtot`, which includes the generator cast to the LSS (04:L125).
- C10. **Gearbox efficiency.** Eq. 2 and Eq. 17 include η_gb (06:p.57, p.60). ElastoDyn sets `GBoxEff` = 100 (01:L123), and 04/05 give no η_gb.
- C11. **Blade radius.** `WE_BladeRadius` = 63.000, "Blade length (distance from hub center to blade tip)" (04:L120), vs `TipRad` = 63 "rotor apex to the blade tip" with `HubRad` = 1.5 (01:L46–47).
- C12. **Minor rounding differences.** `PC_MaxPit` is 1.570796 (03:L74) vs 1.57 (04:L63). `VS_Rgn3MP` is 0.01745329 (03:L94) vs `PC_Switch` 0.01745 (04:L69).

## 8. Suggested acceptance checks

- A1. **Rated generator speed = rated rotor speed × gear ratio** (derived): 1.26711 × 97 = 122.90967 rad/s. This equals `PC_RefSpd` 122.9096 (03:L77) and 122.90967 (04:L67, 04:L90). The same value in rpm: 12.1 rpm (01:L34) × 97 = 1173.7 rpm = 122.9096 rad/s.
- A2. **Stated:** `VS_RtGnSp` = 99 % of `PC_RefSpd` (03:L95). 121.6805 / 122.9096 = 0.99000.
- A3. **Stated:** `VS_RtPwr` = 5 MW / 94.4 % (03:L96). 5e6 / 0.944 = 5,296,610.2 W.
- A4. **Rated torque** (derived): VS_RtPwr / PC_RefSpd = 5296610 / 122.9096 = 43,093.5 N·m. This matches 43.09355 kNm (03:L91) and 4.30935e+04 (04:L89). Note that VS_RtPwr / VS_RtGnSp = 43,528.8 N·m is the region-3 torque at the switch, not VS_RtTq.
- A5. **Rated electrical power** (derived) = torque × speed × efficiency = 43,093.55 × 122.9096 × 0.944 = 5.000 MW, matching 05:L22.
- A6. **Stated:** `VS_MaxTq` is 10 % above VS_RtTq (03:L91). 1.1 × 43,093.55 = 47,402.9 N·m.
- A7. **Region-2 torque** (derived, 03 law). At ω = 91.21091 rad/s (`VS_Rgn2Sp`): 2.332287 × 91.21091² = 19,403.3 N·m. At ω = 100 rad/s: 23,322.9 N·m (ROSCO K would give 23,105.5).
- A8. **Internal constants** (derived from 03:L174–181): VS_SySp = 110.6186 rad/s; VS_Slope15 = 921.830 N·m/(rad/s); VS_Slope25 = 3935.04 N·m/(rad/s); VS_TrGnSp = 119.0138 rad/s. The torque is continuous at VS_Rgn2Sp (19,403.3 from both the 1½ and 2 branches) and at VS_TrGnSp (33,035.2 from both branches). At VS_RtGnSp the 2½ line gives 43,528.8 = VS_RtPwr/VS_RtGnSp.
- A9. **Validity checks stated in the source** must pass: VS_Rgn2K·VS_RtGnSp² = 34,532.2 ≤ VS_RtPwr/VS_RtGnSp = 43,528.8 (03:L231); VS_MaxTq 47,402.91 ≥ 43,528.8 (03:L236); VS_TrGnSp 119.01 ≥ VS_Rgn2Sp 91.21 (03:L206); VS_Rgn2Sp > VS_CtInSp (03:L201).
- A10. **Inertia bookkeeping** (derived): rotor_inertia + GenIner·N² = 38,677,040.613 + 534.116 × 9409 = 43,702,538.057 kg m². This equals `WE_Jtot` (04:L125).
- A11. **Drivetrain torsional natural frequency** (derived, **inferred assumptions**: rigid rotor lumped at 38,677,040.613 kg m², spring and damper referenced to the LSS, generator reflected to the LSS as 5,025,497.4 kg m²):
  - ω_n = √(k(1/J_r + 1/J_gL)) = √(867,637,000 × 2.2484e-7) = 13.967 rad/s = **2.223 Hz**.
  - ζ = c / (2√(k·J_eq)) with J_eq = J_r·J_gL/(J_r+J_gL), giving ζ = **0.050**.
- A12. **Stated:** the speed-filter corner is 1/4 of the blade edgewise frequency (03:L58; 06:p.57). 6.2831853/4 = 1.5708 rad/s (05:L23), i.e. 0.25 Hz.
- A13. **Region boundaries converted to rotor rpm** (derived, ÷97 × 60/2π): cut-in 70.16224 rad/s → 670.0 rpm generator / 6.907 rpm rotor. VS_Rgn2Sp → 871.0 / 8.979 rpm. VS_RtGnSp → 1161.96 / 11.979 rpm.
- A14. **Steady-state balance** (derived from 06:p.57 Eq. 2 with ω̇_g = 0): τ_a = N_g·τ_g/η_gb. With GBoxEff = 100 % (01:L123), the rated aero torque on the LSS is 97 × 43,093.55 = 4.180 MN·m.
- A15. **Simulation behaviour.** A ramp in the aero-torque input should make the generator torque pass through 0 → ramp → k·ω² → slip line → constant power. The command must never exceed 47,402.91 N·m and must never change faster than 15,000 N·m/s (03:L399–407).

## 9. Candidate Modelica Standard Library classes

Every name below was verified as a `"key"` in `out/catalog.jsonl`.

| role | class |
|---|---|
| rotor inertia, generator inertia | `Modelica.Mechanics.Rotational.Components.Inertia` |
| LSS torsional spring + damper | `Modelica.Mechanics.Rotational.Components.SpringDamper` |
| gearbox (97:1, η = 100 %) | `Modelica.Mechanics.Rotational.Components.IdealGear` (or `...Components.LossyGear` if η_gb ≠ 1) |
| aero torque input, generator torque actuator | `Modelica.Mechanics.Rotational.Sources.Torque` |
| HSS speed measurement | `Modelica.Mechanics.Rotational.Sensors.SpeedSensor` |
| shaft power / torque monitoring | `Modelica.Mechanics.Rotational.Sensors.PowerSensor`, `...Sensors.TorqueSensor` |
| ground / reaction | `Modelica.Mechanics.Rotational.Components.Fixed` |
| flanges | `Modelica.Mechanics.Rotational.Interfaces.Flange_a`, `...Flange_b` |
| speed low-pass filter | `Modelica.Blocks.Continuous.FirstOrder` |
| piecewise torque law | **inferred**: a custom block, or `Modelica.Blocks.Tables.CombiTable1Ds` plus `Modelica.Blocks.Logical.Switch` / `Modelica.Blocks.Math.Product` / `Modelica.Blocks.Math.Division` |
| max-torque clamp | `Modelica.Blocks.Nonlinear.Limiter` |
| torque-rate limit | `Modelica.Blocks.Nonlinear.SlewRateLimiter` |
| sampled controller (VS_DT) | `Modelica.Blocks.Discrete.ZeroOrderHold` |
| efficiency / power | `Modelica.Blocks.Math.Gain`, `Modelica.Blocks.Math.Product` |
| signal I/O (pitch input, torque command) | `Modelica.Blocks.Interfaces.RealInput`, `Modelica.Blocks.Interfaces.RealOutput` |
| (optional) pitch PI | `Modelica.Blocks.Continuous.LimPID` or `Modelica.Blocks.Continuous.PI` + `Modelica.Blocks.Math.Feedback` + `Modelica.Blocks.Nonlinear.VariableLimiter` |
| aero-torque test profile | `Modelica.Blocks.Sources.CombiTimeTable` |
