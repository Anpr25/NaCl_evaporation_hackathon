# Test_cases — cross-domain packets from public sources

Six extra packets for testing whether SpecAlive generalises beyond the four supplied cases
(L1–L4). Each one is real third-party material collected on 2026-09-25, not written for
SpecAlive, so the inconsistencies in them are genuine, not planted.

## Layout

```
<packet>/
  sources/        the input: point the pipeline here, and only here
  PROVENANCE.md   per file: URL (commit SHA where from git), licence, checksum, what was changed
  REFERENCE.md    answer key: scope, parts, connections, parameters, gaps, acceptance checks,
                  candidate MSL classes (checked against out/catalog.jsonl)
```

`REFERENCE.md` sits outside `sources/` on purpose. Running the pipeline on the packet root
would feed it the answers.

```bash
specalive run Test_cases/<packet>/sources --provider none --out out/tc_<packet>
```

Files in `sources/` are byte-identical downloads, or web pages converted to Markdown with
the text left verbatim. Formats the ingester has no adapter for (`.inp`, `.dat`, `.F90`,
`.IN`, `.ipynb`, `.rpt`) were given a `.txt` or `.md` extension; `PROVENANCE.md` records the
original name.

## The packets

| Packet | Domain | Pattern it tests | Formats | MSL coverage |
|:--|:--|:--|:--|:--|
| [hydraulic_water_network](hydraulic_water_network/) | hydraulic network | pump + tank + 12 pipes, level rules switch the pump, 24 h demand pattern | txt, md, png, pdf | thin: no Hazen-Williams pipe |
| [power_electronics_buck_converter](power_electronics_buck_converter/) | power electronics | one worked 3.3 V / 3 A design described by 3 documents with different part labels | pdf, md, png | power stage yes; no peak-current-mode controller |
| [vehicle_quarter_car_suspension](vehicle_quarter_car_suspension/) | translational mechanics | 2-DOF passive model under road disturbance; active controllers present but out of scope | pdf, rst, png | good |
| [electromechanical_dc_motor_servo](electromechanical_dc_motor_servo/) | electrical + rotational + control | **closed loop**: PID with stated gains and requirements (the L2 pattern) | md, png, pdf | good |
| [wind_turbine_drivetrain_nrel5mw](wind_turbine_drivetrain_nrel5mw/) | rotational + generator + control | 97:1 drivetrain, piecewise sampled torque law across 5 regions, aero torque as input | txt, yaml, pdf | good for mechanics; controller is custom |
| [chemical_jacketed_cstr](chemical_jacketed_cstr/) | chemical kinetics + thermal + control | Arrhenius reaction, jacket heat path, PID on coolant flow, multiple steady states | md, pdf | none: no reactor class, so this tests L1/L2 templates and synthesis |

## What each packet will catch

The PRD §6.2 input properties each packet exercises. Full lists are in each `REFERENCE.md` §7.

- **Water network.** *Contradictory:* the 1994 manual makes node 9 a tank and writes the
  pump point as head-then-flow; the current file makes it a reservoir, flow-then-head.
  *Incomplete:* the `.inp` has no column units; only `Units GPM` implies ft/in/psi. The
  EPA PDF also contains a different tutorial network with its own "Pump 9" as a distractor.
- **Buck converter.** *Contradictory:* the datasheet swaps the R4/R5/R6 labels, and the board
  guide's feedback equation uses 1.221 V instead of 0.8 V. The datasheet's own compensation
  numbers don't recompute. *Incomplete:* no load model, no parasitics, no initial conditions.
- **Quarter-car.** *Contradictory:* three sources give three different vehicles (sprung mass
  234 / 300 / 250 kg). *Custom:* one source states parameters only as ratios, natural
  frequency and damping ratio. *Incomplete:* one road profile exists only as a figure.
- **DC motor servo.** *Contradictory:* the textbook motor and the real maxon datasheet differ
  by orders of magnitude (J 0.01 vs ~3.9e-7 kg·m²). *Implicit:* no speed sensor or load is ever
  named. *Incomplete:* PID has no derivative filter and no voltage limit.
- **Wind turbine.** *Contradictory:* rated speed and power are defined on different sides of
  the gearbox in the baseline and ROSCO controllers; the region-2 gain disagrees in value and
  unit (the ServoDyn deck gives N·m/rpm² for a rad/s gain). *Incomplete:* `9999.9` placeholders
  must not be extracted as values.
- **CSTR.** *Contradictory:* one notebook's table says feed 350 K and its code uses 300 K; only
  300 K reproduces its results, and at 350 K the setpoint is unreachable. The activation energy
  differs slightly between the notebooks and the paper. *Custom:* L, min and gmol throughout.

## Ingest problems these packets have already exposed

Found while collecting, not yet fixed in the code:

- The YAML adapter drops comments. `wind_turbine.../05_ROSCO_NREL5MW_tuning.yaml` gives the
  rotor-inertia unit only in a comment, so that unit is lost when the file is read.
- PDF text extraction loses equations, superscripts and Greek letters (quarter-car and ROSCO
  papers), and the CSTR paper's parameter table comes out with scrambled columns.
- Several key values exist only inside images: TI schematics, the CTMS block diagram and the
  road-profile figure. Without the vision tier they will be missing.

## Licences

| Packet | Status |
|:--|:--|
| water network | public domain (US EPA) + MIT |
| quarter-car | CC BY 4.0 / CC0; one PNG marked internal-only |
| wind turbine | Apache-2.0 + CC BY 4.0 |
| DC motor servo | CTMS pages CC BY-SA 4.0; **maxon datasheet: internal testing only** |
| buck converter | **TI documents: internal testing only**; Wikipedia / Commons CC BY-SA |
| CSTR | **Kantor notebooks CC BY-NC-ND: internal testing only**; Wikipedia CC BY-SA; arXiv CC BY 4.0 |

PRD §5.3 allows only "material you are free to share". If any of these packets goes into a
submission or demo, use the four with open licences, or drop the files marked internal-only.
