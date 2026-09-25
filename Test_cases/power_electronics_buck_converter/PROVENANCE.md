# Provenance: power_electronics_buck_converter

All files in `sources/` were retrieved with `curl` on **2026-09-25**. Nothing in `sources/` was written by the packet author.
SHA-256 values are for the files as stored in `sources/`.

**Important:** files 01, 02 and 03 are copyrighted Texas Instruments documents. TI makes them free to download, but the TI "Important Notice" at the end of each PDF says: "Other reproduction and display of these resources is prohibited." They are included **for internal testing only. Do not redistribute them.** Do not publish this packet as a public dataset without removing 01–03.

| # | File | Original URL | License / copyright | Changes |
|---|------|--------------|---------------------|---------|
| 01 | `01_ti_slva477_buck_power_stage_calculation.pdf` (612,292 B, sha256 `7997d9374f72a961c337c455b06b3c227d6333732bb13f078783097057f6a969`) | https://www.ti.com/lit/an/slva477b/slva477b.pdf | © Texas Instruments (the PDF footer says "Copyright © 2026"). Free public download with no login. **Internal testing only, do not redistribute.** | **Byte-identical** to the download. Note: the URL names revision B, but TI's server returned **revision C**. The footer reads "SLVA477C – DECEMBER 2011 – REVISED SEPTEMBER 2026" and the revision history names "Revision C (October, 2026)". The file keeps a revision-neutral name for that reason. 9 pages. |
| 02 | `02_ti_tps54331_datasheet.pdf` (2,098,305 B, sha256 `cf72dfd0ac69eec645b7b493de628dc1c3aa66f5f925a2ea9be6bb5c38260730`) | https://www.ti.com/lit/ds/symlink/tps54331.pdf | © 2023 Texas Instruments. Free public download with no login. **Internal testing only, do not redistribute.** | **Byte-identical**. Document SLVS839H ("JULY 2008 – REVISED OCTOBER 2023"), 41 pages. |
| 03 | `03_ti_tps54331evm_232_users_guide.pdf` (782,137 B, sha256 `6dbf482d5dd856d09b31718441369d3e8ac7cf995a8affb3aaf4531e31b763ef`) | https://www.ti.com/lit/ug/slvu247a/slvu247a.pdf (found through a web search; the tool page is https://www.ti.com/tool/TPS54331EVM-232) | © 2022 Texas Instruments. Free public download with no login. **Internal testing only, do not redistribute.** | **Byte-identical**. Document SLVU247A ("JULY 2008 – REVISED OCTOBER 2021"), 15 pages. |
| 04 | `04_wikipedia_buck_converter.md` (44,134 B, sha256 `e8244f6a1c857da898c98d8c9040a46d878da5912166add32cfbab6dd98fbca5`) | https://en.wikipedia.org/wiki/Buck_converter. Fetched as Parsoid HTML from https://en.wikipedia.org/api/rest_v1/page/html/Buck_converter, revision **1367033299** (2026-07-31T15:07:21Z). | **CC BY-SA 4.0** (Wikipedia text). Attribution: "Buck converter", Wikipedia contributors; see the page history at https://en.wikipedia.org/w/index.php?title=Buck_converter&action=history | The HTML was converted to Markdown by a stdlib/bs4 script. Headings, paragraphs, lists and the References and Bibliography sections were kept. The "See also" and "External links" sections, navboxes, edit links, hatnotes, the infobox and images were removed. Figure captions were kept as `*Figure: …*` lines. Math was taken from each MathML element's `alttext` (LaTeX) and written as `$…$`, with the outer `{\displaystyle …}` wrapper removed. Reference markers such as `[1]` were kept. Prose, numbers and units are otherwise verbatim. The only line the script added is the H1 `# Buck converter`, which is the article's own title. No attribution text was added inside the file; the attribution is in this table. |
| 05 | `05_wikimedia_buck_conventions_schematic.png` (17,756 B, 960×379, sha256 `f6350d1de1201da4acf3f3a2e095b462811799291a3442a77768ea22084e5793`) | Wikimedia's PNG render of https://commons.wikimedia.org/wiki/File:Buck_conventions.svg, fetched from https://upload.wikimedia.org/wikipedia/commons/thumb/f/f0/Buck_conventions.svg/960px-Buck_conventions.svg.png | **CC BY-SA 3.0** (https://creativecommons.org/licenses/by-sa/3.0/), checked through the Commons imageinfo API. Author: Cyril BUTTAY (Commons user CyrilB). Description: "Naming conventions for the components, current and voltage in a buck converter". This is Fig. 3 of the Wikipedia article. | **Byte-identical** to Wikimedia's own 960 px PNG rasterisation of the SVG. The packet author did no conversion. |

## Why these sources

- 02 and 03 describe **the same worked design**: the TPS54331 typical application / TPS54331EVM-232 at 7–28 V in, 3.3 V / 3 A out, 570 kHz, with 6.8 µH and 2 × 47 µF. They use different reference-designator conventions and label things differently.
- 01 is a vendor-neutral set of formulas (ΔIL, fS, η), and uses vocabulary different from 02 (ILPP, FSW, KIND).
- 04 and 05 give the textbook topology in academic notation (S, D, L, C, R, Vi, Vo) and add an explicit resistive load R.

## Not used

- The WebSearch tool was used only to find the SLVU247A document number. Its results were not used as content.
- LM2596, TPS5430 and TPS54160 datasheets were downloaded as candidates but not included.
