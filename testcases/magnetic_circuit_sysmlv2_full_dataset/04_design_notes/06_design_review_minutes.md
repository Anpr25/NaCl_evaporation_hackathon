# Magnetic Circuit Design Review - DR-MAG-03

**Date:** 2026-03-12  
**Status:** Final / approved

## Decisions

1. The released case is a **quasi-static, linear magnetic flux-tube model**.
2. The current input is an **RMS phasor magnitude**, not an instantaneous sinusoidal waveform and not a peak phasor magnitude.
3. The leakage branch is retained explicitly. Effective coefficient: `sigma = 0.08`.
4. Useful air-gap flux is `(1-sigma)*Phi_core`.
5. The nominal design/analytic air gap is `1.50 mm`; the `1.58 mm` measurement is a separate as-built prototype configuration.
6. Effective benchmark `mu_r = 1200`.
7. Measuring coil turns = 50. Exciting coil turns = 600.
8. Electric and magnetic grounds are both required.
9. No force interaction, saturation, hysteresis, or eddy-current loss is included in the baseline.
10. The model shall preserve the distinction between **model parameter**, **as-built measurement**, and **verification configuration**.

## Action items

- V&V to issue AV-11 with final analytic values.
- Modeling team to keep legacy v1.0 available but tag its sigma, mu_r and measuring-coil turns as superseded.
