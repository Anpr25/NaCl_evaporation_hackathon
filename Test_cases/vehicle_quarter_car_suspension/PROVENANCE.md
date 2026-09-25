# Provenance: vehicle_quarter_car_suspension

All files were retrieved on **2026-09-25** with `curl`. Nothing in `sources/` was written by the packet author. All four files are **byte-identical** to what was downloaded (checksums below). Nothing was converted, trimmed, renamed inside the file, or edited.

| # | File in `sources/` | Format | Size (bytes) |
|---|---|---|---|
| 01 | `01_karahan_active_suspension_LQR_arXiv2508.02906v6.pdf` | PDF, 15 pages | 1,371,020 |
| 02 | `02_hassan_twin_accumulator_PI_quarter_model_arXiv1706.02147v1.pdf` | PDF, 23 pages | 1,384,649 |
| 03 | `03_eme171_lab02_two_dof_quarter_car.rst` | reStructuredText | 13,910 |
| 04 | `04_eme171_lab02_fig01_schematic_and_bond_graph.png` | PNG, 1474x824 | 108,126 |

---

## 01: Karahan, "Modeling and Simulation of an Active Car Suspension with a Robust LQR Controller under Road Disturbance, Parameter Uncertainty and White Noise"

- **Author:** Mehmet Karahan (TOBB University of Economics and Technology).
- **Original URL:** https://arxiv.org/pdf/2508.02906 (resolved to the current version, **v6**, submitted Wed, 4 Feb 2026). Checked the download against https://arxiv.org/pdf/2508.02906v6: identical MD5. Abstract page: https://arxiv.org/abs/2508.02906
- **Retrieved:** 2026-09-25
- **License:** **CC BY 4.0** (the license link on the arXiv abstract page is `creativecommons.org/licenses/by/4.0/`).
  - **Flag:** page 1 of the PDF carries a journal footer, "Copyright © JES 2024 on-line : journal.esrgroups.org", and a running header "J. Electrical Systems 22-1 (2026): 01-15". The arXiv deposit is CC BY 4.0. The journal version may carry different terms. Treat the arXiv copy as CC BY 4.0, and do not redistribute the journal-formatted version on any other basis.
- **Changes:** none. The PDF is byte-identical.
  - MD5 `4733fff3f96f5b8f43f2758d87914181`
  - SHA-256 `2ee147c798e1d1d6589a4b260e09671f626d3baf6deff5617dfdf27e4a7045a1`
- **Note for testers:** the PDF's text layer loses most mathematical glyphs. Equations (1) to (15) come out of `pdftotext` as blank operators, and superscripts are flattened, so "3.2 x 10^5" reads as "3.2 x 105". Table 1 extracts correctly with `pdftotext -table`, but with `-layout` the symbols are misaligned. This is a natural property of the source, not a modification.

## 02: Hassan, Abd-El-Tawwab, Abd El-gwwad, Salem, "PI Controller for Active Twin-Accumulator Suspension with Optimized Parameters Based on a Quarter Model"

- **Authors:** Mohamed A. Hassan, Ali M. Abd-El-Tawwab, K. A. Abd El-gwwad, M. M. M. Salem (Minia University).
- **Original URL:** https://arxiv.org/pdf/1706.02147 (only version: **v1**, submitted Sun, 4 Jun 2017). Abstract page: https://arxiv.org/abs/1706.02147
- **Retrieved:** 2026-09-25
- **License:** **CC0 1.0, public domain dedication** (the arXiv abstract page links `creativecommons.org/publicdomain/zero/1.0/`).
- **Changes:** none. The PDF is byte-identical.
  - MD5 `ffc7d928c2a0cabdd22e976ba1ee2ccf`
  - SHA-256 `e701379ca9cbe206885514ccc1f3a9ff424c6d52a7ca16be4c01e21c82862599`
- **Note for testers:** the "Symbol" column of Table 3 and the parameter column of Tables 5 to 8 are empty in the text layer, because the symbols are equation objects. The signs in equations (1) to (8) are also lost. This is natural.

## 03: Jason K. Moore, EME 171 "Lab 2: Two DoF Quarter Car Model" (reStructuredText page source)

- **Original URL (pinned to commit):** https://raw.githubusercontent.com/moorepants/eme171/4b5f93f67bfb53d4fa652e75630b7ad5f09f5925/content/pages/lab-02.rst
  - Branch URL: https://raw.githubusercontent.com/moorepants/eme171/master/content/pages/lab-02.rst. Its content is identical to the pinned URL.
  - Last commit touching the file: `4b5f93f`, 2020-01-27, by Jason K. Moore ("Fixed math symbol tau.").
  - Rendered page: https://moorepants.github.io/eme171/lab-2-two-dof-quarter-car-model.html
- **Retrieved:** 2026-09-25
- **License:** **CC BY 4.0**. The repository `LICENSE` is the CC Attribution 4.0 International text; the GitHub API reports `CC-BY-4.0`, and the README says "This repository is licensed under the CC-BY 4.0 license."
  - Attribution: Jason K. Moore, EME 171, UC Davis.
- **Changes:** none. The file is byte-identical.
  - MD5 `c5e84c185a9f69d42b1a699448c69e31`
  - SHA-256 `d2a09cf643105fead3dba768955cbb9e5cef9d14ddfc6edafa0b9e5a8aa63d90`
- The file keeps its Pelican front-matter (`:title:`, `:status:`) and its external links, including the figure URL that file 04 was fetched from.

## 04: Figure 1 of EME 171 Lab 2 (schematic and bond graph of the two-DoF quarter car)

- **Original URL (as referenced in file 03):** https://objects-us-east-1.dream.io/eme171/2020w/lab-02-fig-01.png
  - **The original host was unreachable**: curl got no connection (HTTP 000).
  - **The file was retrieved from the Internet Archive** with a raw (`id_`) snapshot: https://web.archive.org/web/20210413151209id_/https://objects-us-east-1.dream.io/eme171/2020w/lab-02-fig-01.png (snapshot of 2021-04-13).
- **Retrieved:** 2026-09-25
- **License:** **CC BY 4.0 by association (flag).** The image is Figure 1 of the CC-BY-4.0 page in file 03. The repository README says the course's binary assets are served from Jason Moore's DreamObjects bucket rather than committed to the repo. The image itself carries no licence mark. **Internal testing only until the licence is confirmed with the author.**
- **Changes:** none. These are the raw archived bytes (the `id_` mode applies no Wayback rewriting).
  - MD5 `0fac686b7e188ba37dacd5f5a2fbcc68`
  - SHA-256 `6243a993db36dcc3c55431683ffceca8b1d47872420feb18ea90a98acedb068d`

---

## Sources considered and not used

- **U. Michigan CTMS "Suspension: System Modeling"** (https://ctms.engin.umich.edu/CTMS/index.php?example=Suspension&section=SystemModeling). This returned **HTTP 403 with a Cloudflare "Just a moment..." JavaScript challenge**, even with a full browser User-Agent and Accept headers. It is not reachable with curl, so it was not used. It was not reconstructed from memory.
- **arXiv 2507.19542** (BBO fuzzy quarter car): the arXiv licence is non-exclusive distribution only, so it was skipped in favour of CC-licensed papers.
- **arXiv 2306.08222**: CC BY-NC-ND. **arXiv 2401.06650** and **2407.17643**: non-exclusive distribution. **arXiv 2609.22205** (jumping quarter car, CC BY 4.0): it uses only nondimensional parameters, so it was not useful as a parameter source.
- **github.com/marclimGH/CarSuspensionControl** (Modelica): the repository has no licence, and it would hand the pipeline a finished model. Not used.
- **Wikipedia "Car suspension" / "Shock absorber"**: not needed. The three primary sources already give the vocabulary and context, and adding them would only have added unquantified noise.
