# REFERENCE (answer key): power_electronics_buck_converter

This file is outside `sources/` on purpose. The pipeline must never read it.

Citation format: `[NN p.X §Y]`. NN is the source file number. The page is the printed page number in the PDF footer, which equals the PDF page index for 01, 02 and 03.
- 01 = SLVA477C app note
- 02 = TPS54331 datasheet SLVS839H
- 03 = TPS54331EVM-232 user's guide SLVU247A
- 04 = Wikipedia "Buck converter"
- 05 = Commons schematic `Buck_conventions.svg`

Items marked **inferred** were reasoned out by the packet author, not read from a source.

## 1. System summary

- A non-synchronous DC-DC step-down (buck) converter built on the TI TPS54331. The IC contains the high-side n-channel MOSFET (80 mΩ), and the circuit uses an external Schottky catch diode [02 p.1 §3, p.9 §7.1].
- The one worked design: VIN 7–28 V, VOUT 3.3 V, IOUT up to 3 A, fixed 570 kHz switching [02 p.14 Table 8-1; 03 p.2 Table 1-1/1-2].
- Power stage: L1 = 6.8 µH (Sumida CDRH103), 2 × 47 µF X5R ceramic output capacitors (C8, C9), 2 × 4.7 µF plus 0.01 µF input capacitors (C1, C2, C3), and D1 = B340A (40 V, 3 A) [02 p.14 Fig 8-1; 03 p.14 Table 4-1].
- Control: fixed-frequency peak-current-mode control with external Type II compensation (R3/C6/C7), a feedback divider R5/R6 to a 0.8 V reference, EN-pin UVLO (R1/R2) and slow-start (C5) [02 p.10–12 §7.3, p.18–20 §8.2.2.7].
- Sources 01, 04 and 05 give generic buck theory and design formulas in different notation: D, ΔIL, fS, η in 01; Vi, Vo, S, D, L, C, R in 04 and 05.

## 2. Modelling scope

**In scope:** the power stage of the TPS54331 typical-application / EVM-232 design:
- the input source VIN,
- the input capacitors,
- the high-side switch (the IC's internal MOSFET, treated as a controlled switch between VIN and PH),
- the catch diode D1,
- the inductor L1,
- the output capacitors C8 and C9,
- a load on VOUT.

**Optional:** the output feedback divider (R4/R5/R6) as a sensing path.

The switching can be modelled at either of two levels:
- (a) open-loop PWM at 570 kHz with a fixed duty cycle, or
- (b) a closed loop. The sources give enough numbers to parameterise a Type II compensator, but not the full current-mode modulator. **inferred:** closed-loop fidelity is limited; see §7.

**Out of scope, or only behavioural:**
- IC internals: slope compensation, Eco-mode pulse skipping, frequency foldback, OVTP, thermal shutdown, the bootstrap regulator [02 §7.3–7.4].
- The EN/UVLO divider (R1, R2) and slow-start (C5) as logic, unless start-up is modelled.
- The EVM connectors and test points (J1–J4, TP1–TP6).
- Thermal behaviour.
- The DCM and multiphase material in 04.

Source 01 has no numbers of its own, only formulas. Use it for cross-checks, not for the parameters.

## 3. Expected parts

| id | kind | value / part | citation |
|----|------|--------------|----------|
| VIN (J1) | DC voltage source (input supply) | 7–28 V, typ. 15 V (03) | 02 p.14 Fig 8-1 "Vin 7 V – 28 V"; 03 p.2 Table 1-2, p.4 Table 2-1 |
| C1, C2 | input decoupling capacitors | 4.7 µF each, 50 V X7R, ESR ≈ 2 mΩ | 02 p.15 §8.2.2.4; 03 p.14 Table 4-1 |
| C3 | input HF bypass capacitor | 0.01 µF, 50 V X7R | 02 p.15 §8.2.2.4; 03 p.14 Table 4-1 |
| U1 | buck regulator IC TPS54331D (integrated high-side MOSFET, controller) | SO-8 | 02 p.3 Table 5-1; 03 p.14 Table 4-1 |
| U1 high-side switch | controlled switch VIN→PH | RDS(on) 80 mΩ typ / 150 mΩ max (BOOT-PH = 6 V, VIN = 12 V) | 02 p.5 §6.5 |
| D1 | Schottky catch diode (PH→GND) | Diodes Inc. B340A, 40 V, 3 A, VF 0.5 V | 02 p.21 §8.2.2.9; 03 p.14 |
| L1 | output inductor | 6.8 µH, Sumida CDRH103-6R8 (03 BOM: CDRH103RNP-6R8), Isat 3.84 A, IRMS 3.6 A, 35 mΩ | 02 p.17 §8.2.2.5.1; 03 p.14 |
| C8, C9 | output capacitors | 47 µF each, TDK C3216X5R0J476MT, 6.3 V, ESR ≤ 2 mΩ | 02 p.18 §8.2.2.6; 03 p.14 |
| C10 | output bulk capacitor footprint | **not populated** (count 0, "Not Used") | 03 p.13 Fig 4-1, p.14 |
| C4 | bootstrap capacitor BOOT–PH | 0.1 µF | 02 p.20 §8.2.2.8; 03 p.14 |
| R4 | loop-break resistor | 0 Ω | 02 p.15 §8.2.2.3; 03 p.14 |
| R5, R6 | feedback divider (VOUT→VSENSE→GND) | 10.2 kΩ, 3.24 kΩ | 02 p.14 Fig 8-1, p.15; 03 p.14 |
| R3, C6, C7 | Type II compensation on COMP | 29.4 kΩ, 1000 pF, 47 pF | 02 p.20 §8.2.2.7; 03 p.14 |
| R1, R2 | EN / UVLO divider | 332 kΩ, 68.1 kΩ | 02 p.14 Fig 8-1; 03 p.14 |
| C5 | slow-start capacitor | 0.01 µF | 02 p.14 Fig 8-1; 03 p.14 |
| Load (J4) | load on VOUT | 0–3 A; its **type is not specified** (see §7) | 03 p.4 §2.1; 04/05 draw it as resistor R |

## 4. Ports and connections

Nets are read from the EVM schematic [03 p.13 Fig 4-1] and the datasheet schematic [02 p.14 Fig 8-1]. Both are drawn as images, so the connections are not in the PDF text layer. Pin functions are in [02 p.3 Table 5-1].

| net | connects | citation |
|-----|----------|----------|
| VIN | J1.VIN, TP1, C1+, C2+, C3+, U1.VIN (pin 2), R1 top | 03 Fig 4-1; 02 Fig 8-1 |
| GND | J1.GND, TP2, C1−, C2−, C3−, U1.GND (pin 7, plus PowerPAD on DDA), D1 anode, C8−, C9−, R6 bottom, R2 bottom, C5−, R3/C7 bottom, J4.GND, TP6 | 03 Fig 4-1; 02 p.3 Table 5-1 |
| PH (switch node) | U1.PH (pin 8), D1 cathode, L1 pin 1, C4, TP3 | 02 p.3 ("source of the internal high-side power MOSFET"), p.20 §8.2.2.9 ("catch diode between the PH and GND pins"); 03 p.4 Table 2-1 (TP3 = PH) |
| BOOT | U1.BOOT (pin 1) to C4 (to PH) | 02 p.3 Table 5-1, p.20 §8.2.2.8 |
| VOUT | L1 pin 2, C8+, C9+, (C10), R4, J4.VOUT, TP5 | 03 Fig 4-1, p.4 Table 2-1 |
| FB top | R4 to R5, TP4 | 03 Fig 4-1 (TP4 is between R4 and R5) |
| VSENSE | R5/R6 junction to U1.VSENSE (pin 5) | 02 Fig 8-1; 02 p.3 |
| COMP | U1.COMP (pin 6) to C6 in series with R3 to GND; C7 from COMP to GND | 02 Fig 8-1; 03 Fig 4-1; 02 p.12 §7.3.6 ("compensation components are connected between the COMP pin and ground") |
| EN | R1/R2 junction to U1.EN (pin 3), J2 | 02 Fig 8-1; 03 p.4 |
| SS | U1.SS (pin 4) to C5 to GND, J3 | 02 Fig 8-1, p.11 §7.3.5 |

The generic topology in [05] and [04 §Theory, Fig. 3] maps onto these parts as follows (**inferred**):

| 04/05 notation | this design |
|----------------|-------------|
| S | U1 internal MOSFET |
| D | D1 |
| L | L1 |
| C | C8 ∥ C9 |
| R | load |
| Vi | VIN |
| Vo | VOUT |

## 5. Parameters

| name | value | unit | citation |
|------|-------|------|----------|
| Input voltage range (design) | 7 to 28 | V | 02 p.14 Table 8-1; 03 p.2 Table 1-1 |
| Input voltage typ (EVM spec condition) | 15 | V | 03 p.2 Table 1-2 |
| Device operating input range | 3.5 to 28 | V | 02 p.4 §6.3 |
| Output voltage | 3.3 | V | 02 Table 8-1 |
| Output voltage with standard resistors | 3.31 | V | 02 p.15 §8.2.2.3 |
| Output current rating | 3 | A | 02 Table 8-1 |
| Switching frequency | 570 (min 456, max 684) | kHz | 02 Table 8-1; p.6 §6.6 |
| Input ripple voltage (spec) | 300 | mV | 02 Table 8-1 |
| Output ripple voltage (spec) | 30 | mV | 02 Table 8-1 |
| EVM input ripple (measured/spec) | 200 | mVpp | 03 p.2 Table 1-2 |
| EVM output ripple (measured/spec) | 10 | mVpp | 03 p.2 Table 1-2 |
| L1 | 6.8 | µH | 02 p.16; 03 p.14 |
| L1 DCR | 35 | mΩ | 03 p.14 Table 4-1 |
| L1 saturation / RMS current rating | 3.84 / 3.6 | A | 02 p.17 |
| C8, C9 (each) | 47 | µF | 02 p.18 |
| Output capacitance, DC-bias derated | 54 | µF | 02 p.20 |
| Output capacitor ESR (each, max) | 2 | mΩ | 02 p.18 |
| Combined output ESR | ≈ 0.001 | Ω | 02 p.20 |
| C1, C2 (each) | 4.7 | µF | 02 p.15 |
| C3 | 0.01 | µF | 02 p.15 |
| Input capacitor ESR | ≈ 2 | mΩ | 02 p.15 |
| D1 reverse voltage / forward current / VF | 40 / 3 / 0.5 | V / A / V | 02 p.21 |
| High-side RDS(on) typ/max @ BOOT-PH = 6 V, VIN = 12 V | 80 / 150 | mΩ | 02 p.5 §6.5 |
| High-side RDS(on) typ/max @ BOOT-PH = 3 V, VIN = 3.5 V | 115 / 200 | mΩ | 02 p.5 §6.5 |
| Current-limit threshold (min/typ) | 3.5 / 5.8 | A | 02 p.5 §6.5 |
| Voltage reference VREF | 0.772 / 0.8 / 0.828 | V | 02 p.5 §6.5 |
| Minimum controllable on-time (typ/max) | 105 / 130 | ns | 02 p.6 §6.6 |
| Maximum controllable duty ratio (min/typ) | 90 / 93 | % | 02 p.6 §6.6 |
| R5 / R6 | 10.2 / 3.24 | kΩ | 02 p.15; 03 p.14 |
| R3 / C6 / C7 | 29.4 kΩ / 1000 pF / 47 pF | – | 02 p.20 |
| Error amp gm | 92 | µA/V (µmhos) | 02 p.5, p.12 §7.3.6 |
| Error amp DC gain | 800 | V/V | 02 p.5 |
| Switch current to COMP transconductance (GMCOMP) | 12 | A/V | 02 p.5, p.20 |
| ROA / VGGM / RSENSE | 8 MΩ / 800 / 1 Ω/12 | – | 02 p.19–20 |
| Target crossover / phase margin | 25 kHz / 70° | – | 02 p.19–20 |
| EVM measured loop bandwidth / phase margin | 25.0 kHz / 58° (VIN = 25 V, IO = 1 A) | – | 03 p.2 Table 1-2 |
| C4 (bootstrap) | 0.1 | µF | 02 p.20 |
| C5 (slow start), ISS | 0.01 µF, 2 µA | – | 02 Fig 8-1, p.11 |
| R1 / R2 (EN divider) | 332 / 68.1 | kΩ | 02 Fig 8-1 |
| Enable threshold | 1.25 | V | 02 p.5, p.11 |
| Eco-mode entry (peak inductor current) | 160 | mA | 02 p.13 §7.4.1 |
| KIND used | 0.3 | – | 02 p.16 |
| EVM output rise time | 3.5 | ms | 03 p.2 |
| Efficiency estimate for duty-cycle calculation (generic) | 90 % in Eq. 1, 85 % in Eq. 15 | – | 01 p.2 §2, p.7 App. A |

## 6. Behaviour and control

- **Switching:** fixed-frequency PWM at 570 kHz. The high-side MOSFET conducts VIN→PH during on-time. During off-time, D1 carries the inductor current [02 p.10 §7.3.1; 04 §Continuous mode].
- **Ideal CCM duty cycle:** D = Vo/Vi [04 §Continuous mode]. With efficiency included, D = VOUT/(VIN(max)·η) [01 p.2 Eq 1].
- **Control law:** peak-current mode. "When the peak inductor current intersects the COMP pin voltage, the high-side switch is turned off" [02 p.12 §7.3.9]. The outer loop is a gm error amplifier comparing VSENSE with VREF (0.8 V, or the SS voltage when that is lower), with Type II compensation from COMP to GND [02 p.11 §7.3.5, p.12 §7.3.6, p.18 §8.2.2.7]. Slope compensation is added for D > 50 % [02 p.12 §7.3.7].
- **Modes:**
  - Eco-mode pulse skipping when peak IL < 160 mA [02 p.13].
  - Frequency foldback ÷2/÷4/÷8 as VSENSE falls below 0.6, 0.4 and 0.2 V [02 p.12 Table 7-2].
  - OVTP turns the switch off when VSENSE rises above 109 % × VREF and releases it below 107 % [02 p.12].
  - Thermal shutdown at 165 °C [02 p.12].
- **Start-up:** EN above 1.25 V, then SS ramps the effective reference to 0.8 V and VOUT ramps to 3.3 V [03 p.9 §2.9; 02 p.11 Eq 3].
- **DCM** is described generically in [04 §Discontinuous mode]. The datasheet's power-dissipation formulas are valid only in CCM [02 p.21 §8.2.2.11].

## 7. Natural gaps and contradictions

No gaps or contradictions were planted. All of the following were found in the sources as downloaded.

### Gaps: things a model needs that no source states

1. **Load model.** No source says whether the load is resistive, constant-current or an electronic load. 03 says only that "the load must be connected to J4" with a maximum of 3 A. 04 and 05 assume a resistor R. **inferred:** a 3 A resistive load would be 1.1 Ω (02 p.17 does use RO = VO/IO).
2. **Initial conditions** (iL(0), vC(0)). None are stated. Start-up is shown only as scope captures [03 p.9–10].
3. **Parasitics that are missing or ranged.**
   - Diode: only VF 0.5 V is given. No diode resistance, junction capacitance or reverse recovery.
   - MOSFET: no switching times. 02 gives Psw = 0.5·10⁻⁹·VIN²·IOUT·fSW as an empirical loss term [02 p.21].
   - Capacitors: no ESL.
   - Input source: impedance not given; 02 p.16 says the input ripple "is greatly affected by … the output impedance of the voltage source".
   - Board: trace resistance not given.
4. **Operating point for a single simulation.** VIN is a range. The EVM specifies performance at VIN = 15 V [03 p.2]. Loop measurements were made at 25 V / 1 A in Table 1-2 but at 15 V / 1.5 A in the §2.6 text [03 p.2 vs p.8].
5. **Current-mode modulator internals** needed for a faithful closed loop: ramp amplitude, the exact sense gain beyond "RSENSE is 1 Ω/12", and the COMP clamp level. These are not given.
6. **Output capacitance under DC bias** is given as a single figure ("can be as low as 54 µF") without a C(V) curve [02 p.20].

### Contradictions and inconsistencies in the sources

1. **Efficiency factor.** 01 Eq 1 says "e.g., estimated 90%" (p.2). The same formula in Appendix A Eq 15 says "e.g., estimated 85%" (p.7).
2. **Feedback resistor naming.**
   - 02 p.15 says the divider is "R5 and R6", then says "In this design, R4 = 10.2 kΩ and R = 3.24 kΩ", then calls R4 "the 0-Ω resistor".
   - 03 p.3 says to change "R6" but gives Equation 1 and Table 1-3 in terms of "R2". On the EVM, R2 is the 68.1 kΩ EN resistor.
   - **Reference voltage:** 03 Eq 1 uses 1.221 V, which gives R2 = 10 k × 1.221/(3.3 − 1.221) ≈ 5.87 kΩ. That contradicts Table 1-3 (3.24 kΩ for 3.3 V) and the 0.8 V VREF [02 p.5]. With 0.8 V: 10.2 k × 0.8/2.5 = 3.264 kΩ, which is consistent.
3. **Input voltage range.** 03 p.2 says "The TPS54331EVM-232 is designed and tested for VIN = 10 V to 35 V". The same page's Table 1-1/1-2 give 7–28 V, the absolute maximum is 30 V [03 p.2; 02 p.4], and the device range is 3.5–28 V.
4. **Maximum duty cycle.**
   - 02 p.10 §7.3.3 says the device "is designed to operate at 100% duty cycle as long as the BOOT-to-PH pin voltage is greater than 2.1 V".
   - 02 p.6 §6.6 gives the maximum controllable duty ratio as 90 % min / 93 % typ, and Eq 32 uses 0.91 [02 p.21].
   - 03 p.3 says "less than 93%".
5. **Compensation arithmetic.**
   - 02 p.20 states FZ1 = 5883 Hz and FP1 = 106200 Hz, but Eq 30 and Eq 31 substitute 6010 Hz and 103900 Hz.
   - The printed results (928 pF, 51 pF) match 5883 Hz and 106200 Hz: 1/(2π·5883·29200) = 926 pF and 1/(2π·106200·29200) = 51.3 pF. They do not match the substituted values: 907 pF and 52.5 pF.
   - Gain: Eq 20 as printed, −20·log(2π·(1/12)·25000·54e-6), evaluates to **+3.01 dB**, but the text says "Gain = −2.26 dB".
6. **Phase margin.** 02 p.19 says the design "has greater than 60 degrees of phase margin", but the EVM table gives 58° [03 p.2]. The design target was 70° [02 p.20].
7. **Output ripple Eq 13** [02 p.17] uses a (D − 0.5) term. For this design D ≈ 0.12–0.47, so that term is negative, and at 28 V the equation gives a negative VOPP (≈ −0.7 mV with 94 µF). The quoted results are also not reproducible:
   - "maximum total ESR required is 43 mΩ": Eq 14 gives ≈ 34–35 mΩ.
   - "total RMS ripple current is 161 mA (80.6 mA each)": Eq 15 gives 108 mA with NC = 2, or 217 mA with NC = 1.
   These are reported, not corrected.
8. **Input ripple.** 02 p.16 gives "143 mV" as calculated. Eq 6 with CBULK = 9.4 µF and ESR = 2 mΩ gives ≈ 146 mV. The same page also says the measured value "is listed in Table 8-1", but Table 8-1 contains only the 300 mV specification.
9. **Designator slips.**
   - 02 p.16 says the output filter is "L1 and C2", but C2 is an input capacitor and the output capacitors are C8/C9.
   - 02 Table 7-1 (p.12) uses C1/C2/R3 for compensation parts and RO1/RO2 for the divider, but those designators mean other parts in Fig 8-1.
   - 03 p.11 says the divider ties to VOUT "past the output capacitor C3", but C3 is the 0.01 µF input capacitor.
   - 03 p.4 describes TP4 as "between voltage divider network and R3", but the schematic places it between R4 and R5.
10. **Ripple-current formulas differ between sources.**
    - 02 Eq 9 has a hidden ×0.8 in the denominator. **inferred:** 0.8 = 456/570 kHz, the minimum switching frequency.
    - 01 Eq 2 uses D with η and fS min.
    - 04 uses the ideal case.
    For VIN = 28 V these give 0.94 A, 1.04 A (fS min, η = 90 %) and 0.75 A (570 kHz ideal) respectively.
11. **Revision dates.**
    - 01's footer reads "REVISED SEPTEMBER 2026", but its revision history says "Revision C (October, 2026)"; the file was fetched from a `slva477b` URL.
    - 02's footer says "REVISED OCTOBER 2023", but its revision history says "Revision H (September 2023)".

## 8. Suggested acceptance checks

| # | check | expected | basis |
|---|-------|----------|-------|
| A1 | Average VOUT in steady state (CCM, nominal) | 3.3 V (3.31 V with standard resistors) | Stated in 02 Table 8-1 and p.15. Derived: VREF·(1 + R5/R6) = 0.8·(1 + 10.2/3.24) = **3.319 V** |
| A2 | Ideal duty cycle across the VIN range | D = 3.3/28 = 0.118 → 3.3/7 = 0.471; 0.22 at 15 V | Derived from 04 (D = Vo/Vi) and 02 Table 8-1. With 01 Eq 1 (η = 0.9) at 28 V: 0.131 |
| A3 | Minimum on-time margin at VIN = 28 V | ton = D/fsw = 0.118/570 kHz = 207 ns > 130 ns (max tON,min) | Derived from 02 §6.6. 03 p.3 requires > 150 ns |
| A4 | Inductor ripple current at VIN = 28 V | 0.751 A p-p at 570 kHz. Using 02 Eq 9 (×0.8, equivalently 456 kHz): **0.939 A** | Derived: ΔI = Vo(Vi−Vo)/(Vi·L·f) = 3.3·24.7/(28·6.8 µH·570 kHz) |
| A5 | Inductor RMS and peak current at 3 A | 3.01 A RMS, 3.47 A peak | Stated in 02 p.17. Reproduced: √(3² + 0.939²/12) = 3.012; 3 + 0.939/2 = 3.469 |
| A6 | Minimum inductance (KIND = 0.3) | 5.7 µH ≤ 6.8 µH used | Stated in 02 p.16. Reproduced: 3.3·24.7/(28·0.3·3·570e3) = 5.67 µH |
| A7 | Peak switch current below the minimum current limit | 3.47 A < 3.5 A (current-limit min). 01 Eq 3: IMAXOUT = 3.5 − 0.939/2 = 3.03 A ≥ 3 A | Derived from 02 p.5 and 01 p.3 Eq 3. The margin is thin. |
| A8 | Output voltage ripple ≤ 30 mV spec (EVM: 10 mVpp) | Capacitive term ΔI/(8·f·C) = 0.939/(8·570 kHz·94 µF) = 2.2 mV (3.8 mV at 54 µF), plus ESR term 0.939 × 1 mΩ ≈ 0.9 mV | Derived from 04 §Output voltage ripple (ΔV = ΔI·T/8C) and 01 Eq 12–13. Spec from 02 Table 8-1; measurement from 03 Table 1-2 |
| A9 | Input RMS ripple current | 1.5 A | Stated in 02 p.16 Eq 7 (IOUT/2) |
| A10 | Input ripple voltage ≤ 300 mV | ≈ 0.146 V calc (02 says 143 mV) | Derived from 02 Eq 6 with 9.4 µF, 2 mΩ. EVM: 200 mVpp [03] |
| A11 | Output LC corner frequency | 1/(2π√(6.8 µH·94 µF)) ≈ **6.3 kHz** (8.3 kHz with 54 µF), below 25 kHz crossover | Derived from cited L and C values |
| A12 | Minimum Cout for 25 kHz crossover | 1/(2π·1.1 Ω·25 kHz) = 5.8 µF | Stated in 02 p.17; reproduced |
| A13 | Catch-diode stress | VR ≥ VIN(max) + 0.5 = 28.5 V < 40 V. Average IF = 3·(1 − 0.131) = 2.61 A ≤ 3 A. PD = 2.61·0.5 = 1.30 W | 02 p.20 (VIN(MAX) + 0.5 V rule); 01 Eq 7–8 derived with D from 01 Eq 1 |
| A14 | Maximum achievable VOUT at VIN = 7 V, 3 A | 0.91·(7 − 3·0.15 + 0.5) − 3·0.035 − 0.5 = **5.81 V** > 3.3 V | Derived from 02 Eq 32 with RDS(on) max 150 mΩ, RL = 35 mΩ [03], VD = 0.5 V |
| A15 | Slow-start time | TSS = 10 nF·0.8 V/2 µA = **4 ms** (EVM rise time 3.5 ms) | Derived from 02 Eq 3; 03 Table 1-2 |
| A16 | UVLO thresholds from R1/R2 | VSTOP ≈ 6.02 V, VSTART ≈ 7.01 V, consistent with the 7 V minimum VIN | Derived by inverting 02 Eq 1–2: VSTOP = 1.25 + (1.25/68.1k − 4 µA)·332k; VSTART = VSTOP + 3 µA·332k |
| A17 | Compensation RZ | 29.2 kΩ (29.4 kΩ standard) | Stated in 02 Eq 29; reproduced 29.16 kΩ |
| A18 | Energy balance / efficiency sanity | Efficiency < 100 %. EVM curve peaks near 0.6–1 A; maximum 91.6 % at VIN = 10 V, VO = 5 V (a different VO) | 03 p.2, p.4 §2.2. **inferred:** only a loose bound for 3.3 V |

## 9. Candidate Modelica Standard Library classes

All names below were verified to exist as `"key"` entries in `out/catalog.jsonl`.

| role | class | notes |
|------|-------|-------|
| Switch + diode leg (packaged) | `Modelica.Electrical.PowerConverters.DCDC.ChopperStepDown` | Ports dc_p1/dc_n1 (input), dc_p2/dc_n2 (output), fire_p (Boolean). Params RonTransistor, GoffTransistor, VkneeTransistor, RonDiode, GoffDiode, VkneeDiode. Good fit for the U1 switch plus D1. The L and C must be added externally. |
| PWM generator | `Modelica.Electrical.PowerConverters.DCDC.Control.SignalPWM` | Params f (Hz), constantDutyCycle / dutyCycle input; outputs fire/notFire |
| Voltage → duty | `Modelica.Electrical.PowerConverters.DCDC.Control.Voltage2DutyCycle` | Optional, for a closed loop |
| Discrete alternative | `Modelica.Electrical.Analog.Ideal.IdealClosingSwitch` (control: BooleanInput) + `Modelica.Electrical.Analog.Ideal.IdealDiode` (Ron, Goff, Vknee) | Vknee can carry VF = 0.5 V and Ron can carry RDS(on) |
| Alternative diode | `Modelica.Electrical.Analog.Semiconductors.Diode` | Exponential diode. No source gives its Ids/N, so it would need assumed values |
| Inductor | `Modelica.Electrical.Analog.Basic.Inductor` (L) | Add a series `Basic.Resistor` for the 35 mΩ DCR |
| Capacitors | `Modelica.Electrical.Analog.Basic.Capacitor` (C) | Add a series `Basic.Resistor` for ESR |
| Resistors, load, divider | `Modelica.Electrical.Analog.Basic.Resistor` | |
| Input source | `Modelica.Electrical.Analog.Sources.ConstantVoltage` (V) | `Sources.StepVoltage` for line steps |
| Load alternatives | `Modelica.Electrical.Analog.Sources.ConstantCurrent`, `Sources.StepCurrent` | For the 0.75 ↔ 2.25 A transient in 03 Table 1-2 |
| Ground | `Modelica.Electrical.Analog.Basic.Ground` | |
| Sensing | `Modelica.Electrical.Analog.Sensors.VoltageSensor`, `Sensors.CurrentSensor` | |
| Clock alternative | `Modelica.Blocks.Sources.BooleanPulse` (width, period) | |
| Compensator (approx.) | `Modelica.Blocks.Continuous.PI` | **inferred** stand-in only |

MSL has no peak-current-mode controller and no TPS54331-specific model. A faithful closed-loop model of the IC is not available off the shelf, which is why the model scope in §2 is open-loop PWM or an approximate loop.
