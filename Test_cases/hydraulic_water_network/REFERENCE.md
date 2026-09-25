# REFERENCE — hydraulic_water_network (answer key; NOT a pipeline input)

Citation keys:
- **S01** = `sources/01_Net1.inp.txt` (cited by `[SECTION]`)
- **S02** = `sources/02_EPANET_Users_Manual_v1.1_1994_Ch7_Example1.md` (cited by §/Figure)
- **S03** = `sources/03_Net1_EPANET_2.00.12_report.rpt.txt` (cited by block heading)
- **S04** = `sources/04_Net1_network_plot_epanetReader.png`
- **S05** = `sources/05_EPANET_2.2_User_Manual_EPA-600-R-20-133.pdf`, cited as "PDF p.N (printed p.M)". Printed page = PDF page − 14.

Anything marked **inferred** was worked out by the packet author, not read from a source.

## 1. System summary

1. EPANET Example Network 1 ("Net1"), a small municipal water distribution network (S01 `[TITLE]`, S02 §7.2).
2. "Pump 9 takes water from a reservoir at Node 9 and feeds it into a system containing a storage tank at Node 2" (S02 §7.2).
3. The network has 9 demand junctions and 12 Hazen-Williams pipes forming a looped grid, plus one elevated cylindrical tank (S01 `[JUNCTIONS]`, `[PIPES]`, `[TANKS]`; S04).
4. "The operation of the pump is controlled by the level in Tank 2" (S02 §7.2): the pump opens below 110 ft and closes above 140 ft (S01 `[CONTROLS]`).
5. The simulation is a 24 h extended-period run with a 2 h demand pattern (S01 `[TIMES]`, `[PATTERNS]`). The published results are in S03 (EPANET 2.00.12) and part of them in S02 Fig. 7.3 (EPANET 1.1).

## 2. Modelling scope

**In scope (model this):**
- Hydraulics of the 11 nodes and 13 links in S01.
- Time-varying junction demands (demand-driven).
- Tank level dynamics.
- The single-point pump curve.
- The two simple level controls, which together act as on/off hysteresis control.
- 24 h horizon.

**Out of scope:**
- Water quality: chlorine, `[QUALITY]`, `[REACTIONS]`, `[MIXING]`, `[SOURCES]`, Quality Timestep, Diffusivity, Tolerance. Net1's stated *purpose* is chlorine decay (S01 `[TITLE]`, S02 §7.2), but the brief is hydraulics plus discrete control.
- Energy cost (Global Price 0.0, Demand Charge 0.0, S01 `[ENERGY]`). Pump efficiency may be used for an optional power check only.
- EPANET solver settings (Trials, Accuracy, CHECKFREQ, MAXCHECK, DAMPLIMIT, Unbalanced; S01 `[OPTIONS]`).
- Map data (`[COORDINATES]`, `[LABELS]`, `[BACKDROP]`).
- **Distractor:** the EPANET 2.2 Quick Start tutorial network in S05 Ch.2 (PDF p.19–24, printed p.5–10) is a *different* network. It has pump "Link 9" (150 ft @ 600 gpm), tank "Node 8" (60 ft diameter) and junctions 2–7. Do not merge its parameters into Net1: the ID "9" collides.
- The Net2/Net3 names listed in S02 §7.1 are out of scope.

## 3. Expected parts

| id | kind | citation |
|---|---|---|
| 9 (node) | reservoir, fixed head | S01 `[RESERVOIRS]`; S02 §7.2 ("reservoir at Node 9"); S03 node tables ("Reservoir") |
| 2 | storage tank, cylindrical | S01 `[TANKS]`; S02 §7.2; S03 ("Tank") |
| 10, 11, 12, 13, 21, 22, 23, 31, 32 | junctions (demand nodes; 10 has zero demand) | S01 `[JUNCTIONS]`; S02 Fig. 7.2 |
| 9 (link) | pump, curve 1 | S01 `[PUMPS]`, `[CURVES]`; S02 Fig. 7.2 `[PUMPS]` |
| 10, 11, 12, 21, 22, 31, 110, 111, 112, 113, 121, 122 | pipes (12) | S01 `[PIPES]`; S02 Fig. 7.2 |
| pattern 1 | demand multiplier schedule (12 periods × 2 h) | S01 `[PATTERNS]`, `[OPTIONS] Pattern 1`, `[TIMES] Pattern Timestep 2:00` |
| pump level controller | 2 simple controls on link 9 driven by tank 2 level | S01 `[CONTROLS]`; S05 PDF p.39–40 (printed 25–26) |

The element counts are confirmed by S02 Fig. 7.3 ("Number of Pipes 12, Number of Nodes 11, Number of Pumps 1, Number of Valves 0"). There are no valves (S01 `[VALVES]` is empty). S04 legend lists "Valves", but no valve symbol appears in the plot.

## 4. Ports / connectors and connections

Each link joins Node1 to Node2. That is the positive flow direction, and it is where the pump suction and discharge sides are (S05 PDF p.165, printed 151).

| link | kind | from (Node1) | to (Node2) | citation |
|---|---|---|---|---|
| 9 | pump | 9 (reservoir) | 10 | S01 `[PUMPS]` |
| 10 | pipe | 10 | 11 | S01 `[PIPES]` |
| 11 | pipe | 11 | 12 | S01 `[PIPES]` |
| 12 | pipe | 12 | 13 | S01 `[PIPES]` |
| 21 | pipe | 21 | 22 | S01 `[PIPES]` |
| 22 | pipe | 22 | 23 | S01 `[PIPES]` |
| 31 | pipe | 31 | 32 | S01 `[PIPES]` |
| 110 | pipe | 2 (tank) | 12 | S01 `[PIPES]` |
| 111 | pipe | 11 | 21 | S01 `[PIPES]` |
| 112 | pipe | 12 | 22 | S01 `[PIPES]` |
| 113 | pipe | 13 | 23 | S01 `[PIPES]` |
| 121 | pipe | 21 | 31 | S01 `[PIPES]` |
| 122 | pipe | 22 | 32 | S01 `[PIPES]` |

Signal connection: the level of tank 2 drives the status of pump 9 (S01 `[CONTROLS]`).

Node degree check (**inferred**): 10:2, 11:3, 12:4, 13:2, 21:3, 22:4, 23:2, 31:2, 32:2, tank 2:1, reservoir 9:1. S04 shows the same layout: a reservoir-pump line, a tank on a stub, and a 3-row grid.

## 5. Parameters

Units are US customary because flow units are GPM (S01 `[OPTIONS] Units GPM`; S05 PDF p.144, printed 130, Table A.1, and PDF p.160, printed 146). S01 has **no per-column unit labels**. S02 Fig. 7.2 does label them: ft, gpm, in.

| name | value | unit | citation |
|---|---|---|---|
| elevation J10, J11, J12, J13 | 710, 710, 700, 695 | ft | S01 `[JUNCTIONS]`; S02 Fig. 7.2 |
| elevation J21, J22, J23 | 700, 695, 690 | ft | same |
| elevation J31, J32 | 700, 710 | ft | same |
| base demand J10, J11, J12, J13 | 0, 150, 150, 100 | gpm | same |
| base demand J21, J22, J23 | 150, 200, 150 | gpm | same |
| base demand J31, J32 | 100, 100 | gpm | same |
| reservoir 9 head | 800 | ft | S01 `[RESERVOIRS]` (S02 lists it as elevation 800 under `[TANKS]`) |
| tank 2 bottom elevation | 850 | ft | S01 `[TANKS]`; S02 |
| tank 2 initial level | 120 | ft | same |
| tank 2 min level | 100 | ft | same |
| tank 2 max level | 150 | ft | same |
| tank 2 diameter | 50.5 | ft | same |
| tank 2 min volume | 0 | ft³ | S01 `[TANKS]` |
| pipe 10 length, diameter | 10530, 18 | ft, in | S01 `[PIPES]` |
| pipe 11 length, diameter | 5280, 14 | ft, in | same |
| pipe 12 length, diameter | 5280, 10 | ft, in | same |
| pipe 21 length, diameter | 5280, 10 | ft, in | same |
| pipe 22 length, diameter | 5280, 12 | ft, in | same |
| pipe 31 length, diameter | 5280, 6 | ft, in | same |
| pipe 110 length, diameter | 200, 18 | ft, in | same |
| pipe 111 length, diameter | 5280, 10 | ft, in | same |
| pipe 112 length, diameter | 5280, 12 | ft, in | same |
| pipe 113 length, diameter | 5280, 8 | ft, in | same |
| pipe 121 length, diameter | 5280, 8 | ft, in | same |
| pipe 122 length, diameter | 5280, 6 | ft, in | same |
| Hazen-Williams C (all pipes) | 100 | – | S01 `[PIPES]`, `[OPTIONS] Headloss H-W` |
| minor loss (all pipes) | 0 | – | S01 `[PIPES]` |
| pipe status (all) | Open | – | S01 `[PIPES]` |
| pump 9 curve 1 (single point) | 1500 gpm @ 250 ft | gpm, ft | S01 `[CURVES]`; S02 Fig. 7.2 `[PUMPS]` "250 1500" (ft, gpm) |
| pump global efficiency | 75 | % | S01 `[ENERGY]`; S03 Energy Usage "75.00" |
| demand pattern 1 | 1.0 1.2 1.4 1.6 1.4 1.2 1.0 0.8 0.6 0.4 0.6 0.8 | – | S01 `[PATTERNS]`; S02 |
| pattern timestep | 2:00 | h | S01 `[TIMES]`; S02 "PATTERN TIMESTEP 2" |
| duration | 24:00 | h | S01 `[TIMES]`; S02 |
| hydraulic timestep | 1:00 | h | S01 `[TIMES]` |
| report timestep | 1:00 | h | S01 `[TIMES]` |
| pattern start, start clock time | 0:00, 12 am | – | S01 `[TIMES]` |
| demand multiplier | 1.0 | – | S01 `[OPTIONS]` |
| specific gravity | 1.0 | – | S01 `[OPTIONS]` |
| viscosity (relative to water at 20 °C = 1.0 cSt) | 1.0 | – | S01 `[OPTIONS]`; definition S05 PDF p.161 (printed 147) |
| control: pump open threshold | tank 2 level < 110 | ft | S01 `[CONTROLS]` |
| control: pump close threshold | tank 2 level > 140 | ft | S01 `[CONTROLS]` |

## 6. Behaviour / control

- **Pump on/off control.** `LINK 9 OPEN IF NODE 2 BELOW 110` and `LINK 9 CLOSED IF NODE 2 ABOVE 140` (S01 `[CONTROLS]`; S02 Fig. 7.2).
  - The level is "height of water above the tank bottom, not the elevation" (S05 PDF p.40, printed 26).
  - Each rule fires only when its threshold is crossed. Between 110 and 140 ft the pump keeps its last status. This two-rule pair is equivalent to a **hysteresis relay** (**inferred**).
  - Two discrete states: PUMP_ON (link 9 OPEN) and PUMP_OFF (link 9 CLOSED).
- **Initial pump state.** OPEN. `[STATUS]` is empty, and "Links not listed in this section have a default status of OPEN (for pipes and pumps)" (S05 PDF p.176, printed 162). S03 confirms: "0:00:00: Tank 2 is filling at 120.00 ft".
- **Observed switching** (S03 Hydraulic Status):
  - "12:32:34: Pump 9 changed from open to closed" at "140.00 ft".
  - "22:41:30: Pump 9 changed from closed to open" at "110.00 ft".
- **Pump curve.** Single-point rule: "shutoff head at zero flow equal to 133% of the design head and a maximum flow at zero head equal to twice the design flow", fitted as h = A − B·q^C (S05 PDF p.35, printed 21). With the 4/3 shutoff reading, **inferred**: A = 333.33 ft, C = 2.000, B = 3.7037e-5 ft/gpm², giving h = 333.33 − 3.7037e-5·q². See §7 about 133% versus 4/3.
- **Pump flow limits.** Flow through a pump is unidirectional. If the system needs more head than the pump can produce, EPANET shuts the pump off (S05 PDF p.33, printed 19).
- **Pipe headloss (Hazen-Williams).** h_L = 4.727·C^−1.852·d^−4.871·L·q^1.852, with h_L in ft, d and L in ft, q in cfs (S05 PDF p.32, printed 18, Table 3.1). Flow goes from the higher-head end to the lower-head end, and pipes are always full (S05 PDF p.31, printed 17).
- **Tank.**
  - Water surface elevation = bottom elevation + level (S05 PDF p.178, printed 164).
  - EPANET "stops outflow if a tank is at its minimum level and stops inflow if it is at its maximum level" (S05 PDF p.30, printed 16).
  - Mass balance, **inferred**: A_tank·dh/dt = Q_in, where A_tank = π·50.5²/4 = 2002.96 ft². This area matches `tank area` 2002.9617 in OWA `tests/data/net1.out`.
- **Reservoir.** "infinite external source"; its head "cannot be affected by what happens within the network" (S05 PDF p.30, printed 16).
- **Demands.**
  - Junction demand = base demand × multiplier of the current 2 h period. The pattern wraps around after its last period (S05 PDF p.39, printed 25; PDF p.163, printed 149).
  - Junctions with no pattern ID follow the default pattern "1" (S05 PDF p.157, printed 143; S01 `[OPTIONS] Pattern 1`).
  - Demand-driven analysis is the default (S05 PDF p.162, printed 148).
- **Hydraulic stepping.** EPANET inserts shorter steps when a pattern period changes, a tank empties or fills, or a control fires (S05 PDF p.41, printed 27). A continuous-time Modelica model with state events matches this.

## 7. Natural gaps and contradictions (found, not planted)

**Gaps: what a Modelica model needs that the sources do not state**
1. **Units are implicit in the primary file.** S01 gives only `Units GPM`. Feet, inches and psi must be inferred from S05 Table A.1 and the `[OPTIONS]` UNITS definition. S02 labels its columns, but S01 and S03 (partly) do not.
2. **Pump curve shape.** Only one operating point is given (1500 gpm, 250 ft). The full curve comes from an EPANET convention (§6). There is no speed, no NPSH, no efficiency curve (a global 75 % only), no motor or start-up dynamics, and switching is instantaneous.
3. **Water properties.** Temperature and density are not stated. SG = 1.0, and viscosity is only a relative 1.0. A Modelica medium needs a temperature. Hazen-Williams results do not depend on viscosity.
4. **Elevations of the pump and the tank inlet.** Pumps are links and have no elevation. Pipe 110 is assumed to enter at the tank bottom (850 ft), **inferred**. The reservoir head of 800 ft is taken as the free-surface elevation (S05 PDF p.30: "equal to the water surface elevation if the reservoir is not under pressure").
5. **Initial discrete state.** The pump starting OPEN follows only from the `[STATUS]` default rule in S05, not from S01. In Modelica, the hysteresis `pre_y_start` must be chosen to match.
6. **Tank overflow or limits.** No overflow is described; EPANET simply blocks inflow at 150 ft. The level never leaves 110–140 ft in the published run.
7. **Node coordinates are unitless** (`[BACKDROP] UNITS None`). S04 has no ID labels, so topology must be matched by shape only.

**Contradictions between sources**
8. **Classification of node 9.** S02 (1994) lists node 9 under `[TANKS]` with only "800", and its report says "Number of Tanks 2" while labelling 9 "Reservoir". S01 has node 9 under `[RESERVOIRS]` as `Head 800`.
9. **Order of pump data.** S02 `[PUMPS]` gives "250 1500" (head ft, then flow gpm). S01 `[CURVES]` gives "1500 250" (X = flow, then Y = head). A naive reader could swap them.
10. **133 % versus 4/3 shutoff head, and version drift in results.** S05 says "133%". At the S03 t = 0 flow of 1866.18 gpm:
    - with A = 1.33·250 = 332.5 ft, the curve gives 204.50 ft, exactly the S02 (EPANET 1.1) value "-204.50";
    - with A = 4/3·250 = 333.33 ft, it gives 204.35 ft, exactly the S03 (EPANET 2.00.12) value "-204.35".

    So the two report versions differ a little: at 0 h the pump gives 1865.06 gpm in S02 versus 1866.18 gpm in S03, and the tank inflow is 765.06 versus 766.18 gpm (**inferred** explanation). The OWA EPANET 2.2-era regression output `tests/data/net1.out`, decoded by the author, matches S03 to 0.01 for every hourly tank head and pump flow.
11. **Viscosity.** S02 reports "Kinematic Viscosity 1.10e-005 sq ft/sec". S05 defines relative viscosity 1.0 as 1.0 centistoke, which is about 1.076e-5 ft²/s (**inferred** conversion). This has no effect under Hazen-Williams.
12. **S03 was not generated from exactly S01.** The companion `Net1.inp` in the epanetReader repo has the same network data but adds `[REPORT] Links All / Nodes All / Energy Yes`. S01 does not have these lines (**inferred** from diff). This only affects report content, not hydraulics.
13. **Initial quality syntax differs** (S02 `2 32 0.5` range form versus S01 per-node lists). Water quality is out of scope.

## 8. Suggested acceptance checks

| # | check | basis |
|---|---|---|
| A1 | Model has 9 junctions, 1 reservoir, 1 tank, 12 pipes, 1 pump, 0 valves, connected as in §4 | S01; S02 Fig. 7.3 counts |
| A2 | At t = 0: pump flow = total demand + tank inflow. 1100 + 766.18 = 1866.18 gpm. Total base demand = 0+150+150+100+150+200+150+100+100 = 1100 gpm | derived; S03 "Node Results at 0:00:00" (9: −1866.18; 2: 766.18) |
| A3 | Pump head gain at 1866.18 gpm ≈ 204.35 ft. 333.33 − 3.7037e-5·1866.18² = 204.35. Tolerance ±0.5 ft covers the 1.33 reading (204.50) | derived from S05 p.35 rule; S03 link 9 "−204.35" |
| A4 | Tank pressure at t = 0 ≈ 52.0 psi. 120 ft × 0.4333 psi/ft (SG 1) = 52.00 | derived; S03 node 2 "52.00" |
| A5 | Pipe 10 headloss at t = 0 ≈ 1.82 ft/1000 ft. H-W with q = 1866.18/448.83 = 4.158 cfs, d = 1.5 ft, C = 100 gives 1.815 | derived from S05 Table 3.1; S03 link 10 "1.82" |
| A6 | Pump turns OFF when tank level reaches 140 ft at ≈ 12:32:34, and ON at 110 ft at ≈ 22:41:30. Suggested tolerance ±10 min | S03 Hydraulic Status |
| A7 | Drain-phase volume balance (independent of pipe hydraulics). Tank volume drop = 30 ft × 2002.96 ft² = 60,089 ft³ = 449,496 gal. Demand from 12:32:34 to 22:41:30 = 1100 gpm × 60 × Σ(mult·Δt) = 1100 × 60 × 6.8106 h = 449,497 gal. These agree within 0.01 % | derived from S01 pattern, tank data and S03 times |
| A8 | While the pump is off, tank outflow = 1100 × multiplier: 13 h −1100, 14–15 h −880, 16–17 h −660, 18–19 h −440, 20–21 h −660, 22 h −880 gpm | derived; S03 node 2 "Demand" column |
| A9 | Pump utilization = (12.5428 h + 1.3083 h)/24 h = 57.71 % | derived; S03 Energy Usage "57.71" |
| A10 | Tank level (head − 850 ft) at hours 0–24, tolerance ±0.3 ft: 120.00, 123.07, 126.07, 128.14, 130.16, 131.28, 132.38, 132.59, 132.80, 133.86, 134.89, 136.75, 138.57, 137.99, 133.58, 130.06, 126.53, 123.89, 121.25, 119.49, 117.72, 115.08, 112.44, 111.28, 115.40 | S03 node 2 "Head" per hour |
| A11 | Tank level stays inside [100, 150] ft for the whole run; the min/max guards never activate | S03 |
| A12 | Pump flow ≥ 0 always; reservoir outflow = 0 while the pump is closed | S05 p.33; S03 (13–22 h: 9 "0.00") |
| A13 | Junction pressure range over the 24 h run: min 106.81 psi (J32 at 22 h), max 133.89 psi (J10 at 12 h) | S03 hourly node tables |
| A14 | Daily average demand = 1100 gpm, because the pattern mean = 12.0/12 = 1.0 | derived from S01 |

## 9. Candidate Modelica Standard Library classes

All names below were verified by grepping `out/catalog.jsonl` (JSON key field `"key"`) unless marked otherwise.

| role | candidate class (in catalog) | notes |
|---|---|---|
| global settings | `Modelica.Fluid.System` | sets g and p_ambient |
| reservoir 9 | `Modelica.Fluid.Sources.FixedBoundary` or `Modelica.Fluid.Sources.Boundary_pT` | EPANET "head" must be split into a height and a pressure; MSL boundaries have no elevation parameter. Put elevation differences into pipe `height_ab` (**inferred**) |
| tank 2 | `Modelica.Fluid.Vessels.OpenTank` | params include `height`, `crossArea`, `level_start`. It does **not** implement EPANET's stop-outflow-at-min-level rule. Alternative: `Modelica.Thermal.FluidHeatFlow.Components.OpenTank`, which has a `level` output usable as the control signal |
| pipes | `Modelica.Fluid.Pipes.StaticPipe` | **Poor fit.** **Inferred:** MSL has no Hazen-Williams correlation among its wall-friction models. `WallFriction` packages are not in the catalog, so this could not be checked there. Options: Darcy-Weisbach with an equivalent roughness, or `Modelica.Fluid.Fittings.GenericResistances.VolumeFlowRate` (dp = a·V̇² + b·V̇, quadratic rather than exponent 1.852), or a custom H-W resistance |
| junction mixing | direct multi-connection at a port, `Modelica.Fluid.Fittings.MultiPort`, `Modelica.Fluid.Fittings.TeeJunctionIdeal` | |
| junction demand | `Modelica.Fluid.Sources.MassFlowSource_T` (`use_m_flow_in`, negative flow) | |
| demand pattern | `Modelica.Blocks.Sources.CombiTimeTable` (piecewise-constant table) plus `Modelica.Blocks.Math.Gain` | |
| pump 9 | `Modelica.Fluid.Machines.PrescribedPump` | params include `use_N_in`, `N_nominal`, `checkValve`. Its replaceable `flowCharacteristic` (e.g. `...PumpCharacteristics.quadraticFlow`) is **not in the catalog, unverified**. Alternatives: `Modelica.Fluid.Machines.ControlledPump`, `Modelica.Fluid.Machines.Pump`, `Modelica.Thermal.FluidHeatFlow.Sources.IdealPump` |
| on/off switching | `Modelica.Fluid.Valves.ValveDiscrete` in series, or pump speed set through `Modelica.Blocks.Math.BooleanToReal` | |
| level control | `Modelica.Blocks.Logical.Hysteresis` (`uLow` = 110, `uHigh` = 140) plus `Modelica.Blocks.Logical.Not` | Pump runs when the level is low, so the output is inverted. `pre_y_start` must give pump ON at 120 ft. Alternative: `Modelica.Blocks.Logical.OnOffController` (reference 125, bandwidth 30, **inferred**). `Modelica.StateGraph.Step`/`Transition` are available for an explicit two-state machine |
| level signal | `Modelica.Blocks.Sources.RealExpression` reading the tank level | there is no `Modelica.Fluid.Sensors.Level` in the catalog |
| medium | `Modelica.Media.Water.ConstantPropertyLiquidWater` | **not in the catalog, unverified.** The catalog lists only `Modelica.Media.Water.WaterIF97_base.BaseProperties` from `Modelica.Media.Water` |
| project-local option | `SpecAlive.Vessels.Reservoir`, `SpecAlive.Transport.Pump`, `SpecAlive.Transport.Path`, `SpecAlive.Transport.Junction`, `SpecAlive.Sources.FixedSupply` | all present in the catalog; parameterised by mass flow and dp nominal, not by curves |

Overall fit: MSL covers the tank, reservoir, pump, table and hysteresis well. The main gap is Hazen-Williams pipe friction, which has no MSL class. EPANET's tank level-limit semantics also have to be added by hand.
