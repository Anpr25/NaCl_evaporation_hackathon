# Provenance — wind_turbine_drivetrain_nrel5mw

Retrieval date for every file: **2026-09-25** (fetched with `curl`).
Every file in `sources/` is a byte-for-byte copy of the upstream file. Nothing was
edited, trimmed, re-encoded or re-line-ended. The only change is the **file name**
(numeric prefix added, and `.txt` appended where the original extension is not
ingestible). SHA-256 of each stored file is listed so the copy can be re-verified.

The original NREL report (NREL/TP-500-38060) could not be used: nrel.gov and osti.gov
are unreachable from this machine, and no copy on an openly accessible host that was
clearly legitimate was found, so it was not used. No value in the packet comes from it.

| # | File in `sources/` | Original name | Source URL (pinned) | License | Changes |
|---|---|---|---|---|---|
| 01 | `01_NRELOffshrBsline5MW_Onshore_ElastoDyn.dat.txt` | `NRELOffshrBsline5MW_Onshore_ElastoDyn.dat` | https://raw.githubusercontent.com/OpenFAST/r-test/dd5feaaaa500ba7283140107806300d551cff0a7/glue-codes/openfast/5MW_Land_DLL_WTurb/NRELOffshrBsline5MW_Onshore_ElastoDyn.dat | Apache-2.0 (OpenFAST/r-test repo license) | Renamed only (`.dat` → `.dat.txt`, prefix `01_`). CRLF line endings kept. |
| 02 | `02_NRELOffshrBsline5MW_Onshore_ServoDyn.dat.txt` | `NRELOffshrBsline5MW_Onshore_ServoDyn.dat` | https://raw.githubusercontent.com/OpenFAST/r-test/dd5feaaaa500ba7283140107806300d551cff0a7/glue-codes/openfast/5MW_Land_DLL_WTurb/NRELOffshrBsline5MW_Onshore_ServoDyn.dat | Apache-2.0 (OpenFAST/r-test repo license) | Renamed only (`.dat` → `.dat.txt`, prefix `02_`). CRLF line endings kept. |
| 03 | `03_NREL5MW_baseline_DISCON.F90.txt` | `DISCON.F90` (Fortran source of the NREL 5MW baseline Bladed-style controller, J. Jonkman) | https://raw.githubusercontent.com/OpenFAST/r-test/dd5feaaaa500ba7283140107806300d551cff0a7/glue-codes/openfast/5MW_Baseline/ServoData/DISCON/DISCON.F90 | Apache-2.0 (header of the file itself, lines 1–17; © 2015-2016 NREL, © 2016-2017 Envision Energy USA) | Renamed only (`.F90` → `.F90.txt`, prefix `03_`). CRLF line endings kept. |
| 04 | `04_ROSCO_NREL-5MW_DISCON.IN.txt` | `DISCON.IN` (ROSCO controller parameter file for the NREL-5MW) | https://raw.githubusercontent.com/NatLabRockies/ROSCO/974290ec39f7322a9ae83ffa989444bfbea8728b/Examples/Test_Cases/NREL-5MW/DISCON.IN | Apache-2.0 (ROSCO repo license) | Renamed only (`.IN` → `.IN.txt`, prefix `04_`). |
| 05 | `05_ROSCO_NREL5MW_tuning.yaml` | `NREL5MW.yaml` (ROSCO toolbox tuning input) | https://raw.githubusercontent.com/NatLabRockies/ROSCO/974290ec39f7322a9ae83ffa989444bfbea8728b/Examples/Tune_Cases/NREL5MW.yaml | Apache-2.0 (ROSCO repo license) | Renamed only (prefix `05_`). |
| 06 | `06_Abbas_et_al_2022_WES_ROSCO_reference_controller.pdf` | `wes-7-53-2022.pdf` — N. J. Abbas, D. S. Zalkind, L. Pao, A. Wright, "A reference open-source controller for fixed and floating offshore wind turbines", Wind Energ. Sci., 7, 53–73, 2022, doi:10.5194/wes-7-53-2022 | https://wes.copernicus.org/articles/7/53/2022/wes-7-53-2022.pdf | CC BY 4.0 (stated on page 1 of the PDF) | Renamed only. PDF stored as PDF (4,275,801 bytes). |

## Notes

- **Git SHAs.** `OpenFAST/r-test` tree SHA `dd5feaaaa500ba7283140107806300d551cff0a7`
  (branch `main` at retrieval). ROSCO: `https://github.com/NREL/ROSCO` now redirects to
  `NatLabRockies/ROSCO`; commit/tree SHA `974290ec39f7322a9ae83ffa989444bfbea8728b`
  (branch `main` at retrieval). The same file is also served via the old
  `raw.githubusercontent.com/NREL/ROSCO/<sha>/...` path (HTTP 200).
- **Why this DISCON.F90.** r-test holds two copies of the baseline controller:
  `glue-codes/openfast/5MW_Baseline/ServoData/DISCON/DISCON.F90` (used here) and
  `glue-codes/fast-farm/5MW_Baseline/ServoData/DISCON/DISCON.F90`. Apart from line
  endings, they differ only on lines 485 and 487 (the pitch-rate limiter uses `PitCom(K)`
  in the openfast copy and `BlPitch(K)` in the fast-farm copy). Both copies carry the
  in-source comment `!JASON:THIS CHANGED FOR ITI BARGE: 0.0001` on `PC_DT` / `VS_DT`
  (lines 70, 89); this is upstream content, not an edit.
- **Why these ElastoDyn/ServoDyn decks.** Case `5MW_Land_DLL_WTurb` is the land-based 5MW
  run with the baseline controller DLL (`VSContrl = 5`, `PCMode = 5`). In this deck (and
  in every other r-test 5MW ServoDyn deck inspected: `5MW_Land_Linear_Aero`,
  `5MW_Land_BD_Linear`, `5MW_Land_ModeShapes`) the simple-VS fields `VS_RtGnSp`,
  `VS_RtTq`, `VS_Rgn2K`, `VS_SlPc` are placeholders (`9999.9`, or `0.0099999`). They were
  left as-is on purpose: they are a real trap for an extractor.
- ROSCO's own copies of the ElastoDyn/ServoDyn decks (`Examples/Test_Cases/NREL-5MW/`)
  were fetched and compared but not included. Their drivetrain values are the same as
  file 01, written in a different format (`8.67637E+08` vs `867637000`,
  `6.215E+06` vs `6215000`).
- **Considered, not included:** the OpenFAST docs `docs/source/user/servodyn/input.rst`
  and `docs/source/user/elastodyn/input.rst` (commit
  `2895884d2be01862173c88d70f86b358d2f1a50a`). They repeat the parameter one-liners that
  are already in files 01/02. The one extra fact is the documented unit of `VS_Rgn2K`,
  which is `N-m/rpm^2` (see REFERENCE §7). Also not included: the Wikipedia article
  "Variable speed wind turbine", which is generic and not specific to the 5MW.
- The WES paper is copyrighted by its authors and distributed under CC BY 4.0.
  Attribution: Abbas et al. (2022), doi:10.5194/wes-7-53-2022.

## SHA-256

```
8be12ffb8351ccff91f77472d16b33f65d72c54907c1c3c0d20f943cb51c74a1  01_NRELOffshrBsline5MW_Onshore_ElastoDyn.dat.txt
7a7e2b5f062afd81bd43f6d853b6ec075f8cc2a66a54184769212d25f6fb3abd  02_NRELOffshrBsline5MW_Onshore_ServoDyn.dat.txt
43e44536f2e7fca87c650b35553d6385474bf847ae6493268b9a6fdd8013b3e4  03_NREL5MW_baseline_DISCON.F90.txt
455a2b0248301016fce55b908198c0992479de2490be73f69fde3ad83c37a26e  04_ROSCO_NREL-5MW_DISCON.IN.txt
cb4f1542215ea32e519b5114d0ee896755b11e544ab6bad0678fea4039ab693e  05_ROSCO_NREL5MW_tuning.yaml
cbf8b94cb11279589ba1f2b854fd89caa10d8015daed01dc68a516d8cbb1c089  06_Abbas_et_al_2022_WES_ROSCO_reference_controller.pdf
```
