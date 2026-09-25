# Provenance: chemical_jacketed_cstr

Everything was retrieved on 2026-09-25 with `curl`. Every file in `sources/` is third-party content. None of it was written for this packet. The listing below uses SHA-256 hashes of the files as they are stored in `sources/`.

## Licence summary

| File | Licence | Redistribution |
|---|---|---|
| 01 | CC BY-SA 4.0 (Wikipedia text) | OK with attribution + share-alike |
| 02, 03, 04 | Text: **CC BY-NC-ND 4.0** (LICENSE-TEXT.txt). The README says CC BY-NC-SA 4.0. Code cells: **MIT** (LICENSE-CODE.txt) | **Internal testing only. Do not redistribute.** |
| 05 | CC BY 4.0 (arXiv abstract page) | OK with attribution |

On the Kantor repo licence: the repo's `LICENSE-TEXT.txt` holds the full text of *Attribution-NonCommercial-NoDerivatives 4.0 International*, and the header cell of notebook 04.11 says the same (CC-BY-NC-ND-4.0). The `README.md` "License Requirements" paragraph says instead "Creative Commons Attribution Noncommericial ShareAlike License" (by-nc-sa/4.0). `LICENSE-CODE.txt` is the MIT License, "Copyright (c) 2019 by Jeffrey Kantor". The GitHub API reports the repo licence as `MIT`, but that reflects only the code licence file. I applied the stricter reading, NC-ND. Converting .ipynb to .md is a format change, not an adaptation, and we use it only for internal, non-commercial testing. The packet must **not** be published or redistributed with files 02–04 included.

---

## sources/01_wikipedia_continuous_stirred_tank_reactor.md

- **Original:** Wikipedia article "Continuous stirred-tank reactor", revision **1326444188** (2025-12-09T00:55:36Z).
  - Raw wikitext: `https://en.wikipedia.org/w/index.php?title=Continuous_stirred-tank_reactor&action=raw`
  - Permanent link: `https://en.wikipedia.org/w/index.php?title=Continuous_stirred-tank_reactor&oldid=1326444188`
- **Retrieved:** 2026-09-25
- **Licence:** CC BY-SA 4.0. Authors: Wikipedia contributors (see the article history).
- **Changes (mechanical wikitext → Markdown conversion by a regex script; no sentence, number or equation edited):**
  - Removed all `<ref>…</ref>` citations and the templates `{{Short description}}`, `{{reflist}}`, `{{Biotechnology}}`, `{{DEFAULTSORT}}` and `{{cite …}}`. Removed the category link. Dropped the empty "Notes" and "References" headings, which only held reflist templates.
  - Replaced `[[File:…|caption]]` image embeds with `[Figure: <caption>]`. The caption text is verbatim; the images are not included.
  - `[[target|text]]` became `text`. `'''bold'''` became `**bold**` and `''italic''` became `*italic*`. `== H ==` headings became Markdown `#` headings.
  - `<math>…</math>` became `$…$`, with the LaTeX left untouched. `<chem>X</chem>` became `$\ce{X}$`. The HTML tags `<sub>`, `<sup>`, `<u>`, `<s>` and `<br />` were kept verbatim.
  - The wikitable "Outlet Concentration for an Ideal CSTR" became a Markdown table, with its caption kept on a line prefixed `Table:`.
  - Added the article title as the first `#` heading.
- SHA-256: `85f8435aa512759038cd85cf0e59002a71fa3654645633c7e76aaf5cca6c9551`

## sources/02_exothermic_cstr_notebook.md

- **Original name:** `02.06-Exothermic-CSTR.ipynb`. The .ipynb format is not supported by the pipeline.
- **URL:** `https://raw.githubusercontent.com/jckantor/CBE30338/93418114a42775804cd419126e6e1d09f609ee3d/notebooks/02.06-Exothermic-CSTR.ipynb`
- **Repo / commit:** https://github.com/jckantor/CBE30338 at commit `93418114a42775804cd419126e6e1d09f609ee3d` (master HEAD, 2021-12-20T22:46:21Z). The original .ipynb has SHA-1 `18f6f5a673c9b927f23f86fab6cb0809b44f1c13`.
- **Author:** Jeffrey C. Kantor (CBE30338 Chemical Process Control, University of Notre Dame).
- **Retrieved:** 2026-09-25
- **Licence:** text CC BY-NC-ND 4.0, code MIT (see the licence summary above). **Internal testing only. Do not redistribute.**
- **Changes:** Concatenated all 22 cells in order, separated by blank lines. Markdown cells are verbatim. Code cells are verbatim inside ```` ```python ```` fences. The notebook file contains no outputs. No cells were dropped. Markdown image links such as `![Exothermic Reactor](https://upload.wikimedia.org/...)` stay as link text; the image itself is not included. Notebook JSON metadata was discarded. Misspellings in the original ("Arrehenius", "reactoris", "osciallations") are kept.
- SHA-256: `135d9e92a4511462579daaaf03b3f501eafcba8ccf22fee0ec876c2de8fb8062`

## sources/03_exothermic_cstr_pyomo_simulation_notebook.md

- **Original name:** `07.04-Simulation-of-an-Exothermic-CSTR.ipynb`
- **URL:** `https://raw.githubusercontent.com/jckantor/CBE30338/93418114a42775804cd419126e6e1d09f609ee3d/notebooks/07.04-Simulation-of-an-Exothermic-CSTR.ipynb` (same commit as above). The original .ipynb has SHA-1 `a5fbce1fee43cfc2342bca56c5932823726578bb`.
- **Retrieved:** 2026-09-25
- **Licence:** as for 02. **Internal testing only. Do not redistribute.**
- **Changes:** same conversion as file 02. There are 19 cells; the one dropped was the final empty code cell (index 18).
- SHA-256: `ba2b42fd01a2d34bded4fcb7b27aa7418aab88248fd48f43cbb9dc657c9d0baa`

## sources/04_pid_control_exothermic_cstr_notebook.md

- **Original name:** `04.11-Implementing-PID-Control-in-Nonlinear-Simulations.ipynb`
- **URL:** `https://raw.githubusercontent.com/jckantor/CBE30338/93418114a42775804cd419126e6e1d09f609ee3d/notebooks/04.11-Implementing-PID-Control-in-Nonlinear-Simulations.ipynb` (same commit). The original .ipynb has SHA-1 `0c82f8c10f1e0d3cbff899812e5c5f937a9e759a`.
- **Retrieved:** 2026-09-25
- **Licence:** as for 02. The notebook's own header cell states "text is released under the CC-BY-NC-ND-4.0 license, and code is released under the MIT license"; that cell is kept. **Internal testing only. Do not redistribute.**
- **Changes:** same conversion as file 02. There are 28 cells. Dropped: the two `<!--NAVIGATION-->` cells (indices 1 and 27, prev/next links and Colab/download badges) and one empty code cell (index 26). The `<!--NOTEBOOK_HEADER-->` cell with the licence statement was kept. Known errors in the original, all kept as-is: the table says feed temperature 350 K but the code says `Tf = 300.0`; the bifurcation sentence says "less than" twice; the bounded-control formula uses `max(...max(...))`.
- SHA-256: `05b54674dbf99ee58cdf3fbb77f20217ff3ec668fe43819a1507a143d2735891`

## sources/05_arxiv_2305.15602_cis_safe_rl_cstr.pdf

- **Original name:** `2305.15602.pdf`, i.e. the arXiv PDF of 2305.15602v1.
- **Paper:** Song Bo, Bernard T. Agyeman, Xunyuan Yin, Jinfeng Liu, "Control invariant set enhanced safe reinforcement learning: improved sampling efficiency, guaranteed stability and robustness". arXiv:2305.15602 [v1], submitted 24 May 2023.
- **URL:** https://arxiv.org/pdf/2305.15602 (abstract page: https://arxiv.org/abs/2305.15602)
- **Retrieved:** 2026-09-25
- **Licence:** CC BY 4.0, as linked from the abstract page (`creativecommons.org/licenses/by/4.0/`).
- **Changes:** none. This is the byte-for-byte PDF, 1,434,861 bytes. The relevant part is Section 5.1 (CSTR model, Table 1, constraints (22)–(24)). Sections 6 and 6.3–6.4 give the disturbance bounds, the 6 s sampling time and the optimal steady state.
- SHA-256: `b60c147de0b198f8fe0b4e9dbd2516413063c1605a2850b02f0efddb55041312`

---

## Considered and not used

- Kantor `docs/*.ipynb` copies of the same notebooks. These are near-duplicates of the `notebooks/` versions, so I used the `notebooks/` versions.
- arXiv 1712.03360 and 2007.15607. Both use the arXiv non-exclusive licence, and I preferred a CC BY paper.
- arXiv 2511.03603 and 2110.00618 (CC BY). They model different CSTR systems (other parameter sets and units), which would add a different plant rather than a contradiction about the same one.
- The arXiv API (export.arxiv.org) returned HTTP 429 (rate-limited). I found candidates with a web search instead and fetched the abstract pages and PDFs directly.
- Wikipedia "Arrhenius equation". Not needed; the notebooks state the Arrhenius form and constants.
